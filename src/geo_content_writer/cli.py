from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import time
from datetime import datetime, timezone

from jsonschema import ValidationError, validate

from .client import DagenoClient
from .workflows import (
    backlink_opportunity_brief,
    brand_snapshot,
    citation_source_brief,
    community_opportunity_brief,
    content_pack,
    content_opportunity_brief,
    content_pack_compact_json,
    content_pack_json,
    default_brand_kb_path,
    default_fanout_backlog_path,
    default_published_registry_path,
    default_citation_learnings_path,
    discover_prompt_candidates,
    build_fanout_backlog,
    load_fanout_backlog,
    save_fanout_backlog,
    load_published_registry,
    published_keys_from_registry,
    add_published_item,
    save_published_registry,
    select_backlog_items,
    article_generation_payload,
    article_generation_payload_from_backlog_row,
    draft_article_from_payload,
    save_citation_learning,
    first_asset_draft,
    legacy_publish_ready_article,
    new_content_brief,
    prompt_deep_dive,
    prompt_gap_report,
    topic_watchlist,
    weekly_exec_brief,
)
from .citation_crawl import analyze_citation_patterns, crawl_citation_pages
from .wordpress import WordPressClient, markdown_to_basic_html


def _retry(label: str, attempts: int, func, *, delay: float = 1.0):
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return func()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt == attempts:
                break
            time.sleep(delay * attempt)
    if last_exc:
        raise last_exc
    raise RuntimeError(f"{label} failed without raising an exception")  # pragma: no cover


def _generate_and_check(
    payload: dict,
    *,
    min_words: int = 1200,
    auto_revise: bool = False,
    max_iterations: int = 2,
    quality_mode: str = "strict",
) -> tuple[str, dict]:
    """Generate an article, optionally auto-revise until quality passes."""
    iterations = 0
    working_payload = payload
    while True:
        article_markdown = draft_article_from_payload(working_payload)
        quality = _article_quality_report(article_markdown, min_words=min_words, mode=quality_mode)
        iterations += 1
        if quality["passed"]:
            return article_markdown, quality
        if not auto_revise or iterations >= max_iterations:
            return article_markdown, quality
        # add a simple revise hint to encourage variation
        working_payload = dict(working_payload)
        goal = working_payload.get("content_goal", "")
        working_payload["content_goal"] = (
            goal
            + " Revise to satisfy quality gate: add missing required sections, add concrete decision rules, rankings, and enough 'not ideal' boundaries; ensure >=5 references."
        )
def _default_output_schema_path() -> Path:
    return Path(__file__).resolve().parents[2] / "schemas" / "output_schema.json"


def _default_brand_kb_schema_path() -> Path:
    return Path(__file__).resolve().parents[2] / "schemas" / "brand_knowledge_base_schema.json"


def _default_fanout_backlog_path() -> Path:
    return default_fanout_backlog_path()


def _default_citation_learnings_path() -> Path:
    return default_citation_learnings_path()


def _parse_taxonomy_ids(raw: str | None) -> list[int]:
    if not raw:
        return []
    values: list[int] = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        values.append(int(item))
    return values


def _derive_title_and_slug(markdown_text: str) -> tuple[str, str]:
    first_heading = ""
    for line in markdown_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            first_heading = stripped[2:].strip()
            break
    title = first_heading or "Untitled Draft"
    slug = (
        title.lower()
        .replace("?", "")
        .replace("'", "")
    )
    slug = "-".join(part for part in re.split(r"[^a-z0-9]+", slug) if part)
    return title, slug or "untitled-draft"


def _extract_publishable_markdown(markdown_text: str) -> str:
    marker = "\n## Article\n"
    if marker in markdown_text:
        return markdown_text.split(marker, 1)[1].lstrip()
    return markdown_text


def _word_count(markdown_text: str) -> int:
    return len([word for word in re.findall(r"\b\w+\b", markdown_text)])


def _extract_section(markdown_text: str, heading: str) -> str:
    marker = f"\n## {heading}\n"
    if marker not in markdown_text:
        return ""
    tail = markdown_text.split(marker, 1)[1]
    parts = re.split(r"\n## [^\n]+\n", tail, maxsplit=1)
    return parts[0]


def _article_quality_report(markdown_text: str, min_words: int = 1200, mode: str = "strict") -> dict:
    required_sections = [
        "App-by-App Trade-Off Snapshot",
        "Decision Engine (If X -> Choose Y)",
        "Default Ranking (If You Force a Single Starting Order)",
        "If You Only Remember One Thing",
    ]
    missing_sections = [section for section in required_sections if f"## {section}" not in markdown_text]

    references_section = _extract_section(markdown_text, "References")
    reference_lines = [line for line in references_section.splitlines() if line.strip().startswith("- http")]
    not_ideal_count = len(re.findall(r"\bnot ideal\b", markdown_text.lower()))

    decision_engine = _extract_section(markdown_text, "Decision Engine (If X -> Choose Y)")
    decision_rules = [line for line in decision_engine.splitlines() if line.strip().startswith("- If ")]

    ranking_section = _extract_section(markdown_text, "Default Ranking (If You Force a Single Starting Order)")
    ranking_lines = [line for line in ranking_section.splitlines() if re.match(r"^\s*\d+\.\s", line)]

    checks = {
        "min_words": _word_count(markdown_text) >= min_words,
        "required_sections": not missing_sections,
        "references_at_least_5": len(reference_lines) >= 5,
        "exclusion_boundaries_present": not_ideal_count >= 2,
        "decision_rules_present": len(decision_rules) >= 2,
        "default_ranking_present": len(ranking_lines) >= 2,
    }
    if mode == "warn":
        passed = checks["min_words"] and checks["references_at_least_5"]
    else:
        passed = all(checks.values())
    return {
        "passed": passed,
        "checks": checks,
        "metrics": {
            "word_count": _word_count(markdown_text),
            "min_words_required": min_words,
            "missing_sections": missing_sections,
            "reference_count": len(reference_lines),
            "not_ideal_count": not_ideal_count,
            "decision_rule_count": len(decision_rules),
            "default_ranking_count": len(ranking_lines),
            "head_to_head_row_count": len(h2h_rows),
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GEO Content Writer CLI")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--api-key", default=None, help="Override DAGENO_API_KEY")
    common.add_argument("--base-url", default="https://api.dageno.ai/business/api")
    common.add_argument("--days", type=int, default=1, help="Time window for date-based workflows; defaults to today")
    common.add_argument("--limit", type=int, default=5, help="How many rows to show")

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("brand-snapshot", parents=[common], help="Show brand context from Dageno")
    subparsers.add_parser("topic-watchlist", parents=[common], help="List top GEO topics")
    subparsers.add_parser("prompt-gap", parents=[common], help="List high-value prompts")
    subparsers.add_parser("citation-brief", parents=[common], help="Summarize citation domains and URLs")
    subparsers.add_parser("content-opportunities", parents=[common], help="List top content opportunities")
    subparsers.add_parser("backlink-opportunities", parents=[common], help="List top backlink opportunities")
    subparsers.add_parser("community-opportunities", parents=[common], help="List top community opportunities")
    subparsers.add_parser("weekly-brief", parents=[common], help="Generate a combined executive brief")
    discover_prompts_parser = subparsers.add_parser(
        "discover-prompts",
        parents=[common],
        help="List high-value prompt candidates for fanout extraction",
    )
    discover_prompts_parser.add_argument("--max-prompts", type=int, default=20, help="How many prompt candidates to return")
    backlog_parser = subparsers.add_parser(
        "build-fanout-backlog",
        parents=[common],
        help="Extract real fanout from high-value prompts and save a backlog file",
    )
    backlog_parser.add_argument(
        "--brand-kb-file",
        default=str(default_brand_kb_path()),
        help="Brand knowledge base JSON file. Default project path: knowledge/brand/brand-knowledge-base.json",
    )
    backlog_parser.add_argument("--max-prompts", type=int, default=100, help="How many prompt candidates to inspect (default 100)")
    backlog_parser.add_argument(
        "--published-file",
        default=str(default_published_registry_path()),
        help="Published registry JSON used to avoid re-adding already published topics",
    )
    backlog_parser.add_argument(
        "--allow-exploratory-fallback",
        action="store_true",
        help="If write_now items are insufficient, add exploratory fallback candidates (still non-publishable by default)",
    )
    backlog_parser.add_argument(
        "--exploratory-min-write-now",
        type=int,
        default=5,
        help="Trigger fallback when write_now count is below this threshold",
    )
    backlog_parser.add_argument(
        "--exploratory-max-items",
        type=int,
        default=20,
        help="Maximum fallback exploratory rows to add in one run",
    )
    backlog_parser.add_argument(
        "--exploratory-per-prompt",
        type=int,
        default=3,
        help="How many fallback exploratory candidates to derive per prompt",
    )
    backlog_parser.add_argument(
        "--output-file",
        default=str(_default_fanout_backlog_path()),
        help="Where to write the fanout backlog JSON",
    )
    select_backlog_parser = subparsers.add_parser(
        "select-backlog-items",
        help="Select the next backlog items for drafting",
    )
    select_backlog_parser.add_argument(
        "--input-file",
        default=str(_default_fanout_backlog_path()),
        help="Backlog JSON file to read; defaults to knowledge/backlog/fanout-backlog.json",
    )
    select_backlog_parser.add_argument("--status", default="write_now", help="Which backlog status to select from")
    select_backlog_parser.add_argument("--top-n", type=int, default=10, help="How many items to return")
    select_backlog_parser.add_argument(
        "--published-file",
        default=str(default_published_registry_path()),
        help="Published registry JSON file used to avoid re-writing the same fanout",
    )
    select_backlog_parser.add_argument(
        "--include-published",
        action="store_true",
        help="Include items even if they already appear in the published registry",
    )

    mark_published_parser = subparsers.add_parser(
        "mark-published",
        help="Add one item to the published registry to prevent future duplicates",
    )
    mark_published_parser.add_argument(
        "--published-file",
        default=str(default_published_registry_path()),
        help="Published registry JSON file to update",
    )
    mark_published_parser.add_argument("--backlog-id", default=None, help="Optional backlog_id to record")
    mark_published_parser.add_argument("--fanout-text", default=None, help="Optional fanout text to canonicalize")
    mark_published_parser.add_argument("--canonical-key", default=None, help="Optional canonical key override")
    mark_published_parser.add_argument("--url", default=None, help="Optional published URL to record")
    content_pack_parser = subparsers.add_parser(
        "content-pack",
        aliases=["pack"],
        parents=[common],
        help="Generate a content pack from one GEO opportunity",
    )
    content_pack_parser.add_argument("--prompt-id", default=None, help="Optional prompt ID to target")
    content_pack_parser.add_argument("--prompt-text", default=None, help="Optional prompt text to target")
    content_pack_parser.add_argument(
        "--brand-kb-file",
        default=str(default_brand_kb_path()),
        help="Brand knowledge base JSON file. Default project path: knowledge/brand/brand-knowledge-base.json",
    )
    content_pack_parser.add_argument(
        "--output-json",
        action="store_true",
        help="Output machine-readable JSON matching schemas/output_schema.json",
    )
    content_pack_parser.add_argument(
        "--compact",
        action="store_true",
        help="Use a shorter markdown format for lower token usage",
    )
    content_pack_parser.add_argument(
        "--compact-json",
        action="store_true",
        help="Output a shorter JSON summary for lower token usage; use --output-json without this flag for the full schema payload",
    )
    content_pack_parser.add_argument(
        "--output-file",
        default=None,
        help="Optional file path to write the content pack output",
    )
    first_asset_parser = subparsers.add_parser(
        "first-asset-draft",
        aliases=["draft-first"],
        parents=[common],
        help="Generate the first draft from the top content-pack asset",
    )
    first_asset_parser.add_argument("--prompt-id", default=None, help="Optional prompt ID to target")
    first_asset_parser.add_argument("--prompt-text", default=None, help="Optional prompt text to target")
    first_asset_parser.add_argument("--asset-id", default=None, help="Optional asset row ID such as A1")
    first_asset_parser.add_argument(
        "--brand-kb-file",
        default=str(default_brand_kb_path()),
        help="Brand knowledge base JSON file. Default project path: knowledge/brand/brand-knowledge-base.json",
    )
    first_asset_parser.add_argument(
        "--output-file",
        default=None,
        help="Optional file path to write the first-asset draft output",
    )
    publish_ready_parser = subparsers.add_parser(
        "publish-ready-article",
        parents=[common],
        help="Official path: build the backlog-row-first payload and writer prompt for one publish-ready article",
    )
    publish_ready_parser.add_argument("--backlog-id", default=None, help="Optional backlog row id to target")
    publish_ready_parser.add_argument(
        "--backlog-file",
        default=str(_default_fanout_backlog_path()),
        help="Optional backlog JSON file; defaults to knowledge/backlog/fanout-backlog.json",
    )
    publish_ready_parser.add_argument("--prompt-id", default=None, help="Optional prompt ID to target")
    publish_ready_parser.add_argument("--prompt-text", default=None, help="Optional prompt text to target")
    publish_ready_parser.add_argument("--asset-id", default=None, help="Optional asset row ID such as A1")
    publish_ready_parser.add_argument(
        "--brand-kb-file",
        default=str(default_brand_kb_path()),
        help="Brand knowledge base JSON file. Default project path: knowledge/brand/brand-knowledge-base.json",
    )
    publish_ready_parser.add_argument(
        "--allow-brand-mismatch",
        action="store_true",
        help="Proceed even if local brand KB and remote snapshot differ (adds warning)",
    )
    publish_ready_parser.add_argument(
        "--output-file",
        default=None,
        help="Optional file path to write the article-generation payload output",
    )
    legacy_article_parser = subparsers.add_parser(
        "legacy-publish-ready-article",
        parents=[common],
        help="Deprecated: legacy direct article generator kept only for backward compatibility",
    )
    legacy_article_parser.add_argument("--prompt-id", default=None, help="Optional prompt ID to target")
    legacy_article_parser.add_argument("--prompt-text", default=None, help="Optional prompt text to target")
    legacy_article_parser.add_argument("--asset-id", default=None, help="Optional asset row ID such as A1")
    legacy_article_parser.add_argument(
        "--brand-kb-file",
        default=str(default_brand_kb_path()),
        help="Brand knowledge base JSON file. Default project path: knowledge/brand/brand-knowledge-base.json",
    )
    legacy_article_parser.add_argument(
        "--allow-brand-mismatch",
        action="store_true",
        help="Proceed even if brand KB differs from remote snapshot",
    )
    legacy_article_parser.add_argument(
        "--output-file",
        default=None,
        help="Optional file path to write the legacy article output",
    )
    payload_parser = subparsers.add_parser(
        "article-generation-payload",
        parents=[common],
        help="Build a structured writing payload for one selected article item",
    )
    payload_parser.add_argument("--backlog-id", default=None, help="Optional backlog row id to target")
    payload_parser.add_argument(
        "--backlog-file",
        default=str(_default_fanout_backlog_path()),
        help="Optional backlog JSON file; defaults to knowledge/backlog/fanout-backlog.json",
    )
    payload_parser.add_argument("--prompt-id", default=None, help="Optional prompt ID to target")
    payload_parser.add_argument("--prompt-text", default=None, help="Optional prompt text to target")
    payload_parser.add_argument("--asset-id", default=None, help="Optional asset row ID such as A1")
    payload_parser.add_argument(
        "--brand-kb-file",
        default=str(default_brand_kb_path()),
        help="Brand knowledge base JSON file. Default project path: knowledge/brand/brand-knowledge-base.json",
    )
    payload_parser.add_argument("--citation-limit", type=int, default=5, help="How many citation pages to inspect")
    payload_parser.add_argument(
        "--allow-brand-mismatch",
        action="store_true",
        help="Proceed even if brand KB differs from remote snapshot",
    )
    payload_parser.add_argument(
        "--brand-mode",
        default="strict",
        choices=["strict", "warn", "ignore"],
        help="Brand alignment mode (default strict).",
    )
    draft_payload_parser = subparsers.add_parser(
        "draft-article-from-payload",
        help="Generate one article draft from a saved payload JSON file",
    )
    draft_payload_parser.add_argument("input_file", help="Payload JSON file")
    draft_payload_parser.add_argument("--output-file", default=None, help="Optional file path to write the drafted article")
    draft_payload_parser.add_argument(
        "--auto-revise",
        action="store_true",
        help="Auto-revise and re-check if the article fails the quality gate.",
    )
    draft_payload_parser.add_argument(
        "--revise-iterations",
        type=int,
        default=2,
        help="Maximum auto-revise iterations when quality fails (default 2).",
    )
    draft_payload_parser.add_argument(
        "--quality-mode",
        default="strict",
        choices=["strict", "warn"],
        help="Quality mode: strict (all gates) or warn (wordcount+references must pass, others warn).",
    )
    quality_parser = subparsers.add_parser(
        "check-article-quality",
        help="One-click quality gate for a generated markdown article",
    )
    quality_parser.add_argument("input_file", help="Markdown article file to validate")
    quality_parser.add_argument("--min-words", type=int, default=1200, help="Minimum word count required")
    quality_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON report")
    quality_parser.add_argument(
        "--quality-mode",
        default="strict",
        choices=["strict", "warn"],
        help="Quality mode: strict (all gates) or warn (wordcount+references must pass, others warn).",
    )
    new_content_parser = subparsers.add_parser(
        "new-content-brief",
        parents=[common],
        help="Turn one real content opportunity into a new-content brief",
    )
    new_content_parser.add_argument("--prompt-id", default=None, help="Optional prompt ID to target")
    new_content_parser.add_argument("--prompt-text", default=None, help="Optional prompt text to target")

    prompt_parser = subparsers.add_parser("prompt-deep-dive", parents=[common], help="Inspect one prompt in detail")
    prompt_parser.add_argument("prompt_id", help="Prompt ID from the prompts endpoint")

    validate_parser = subparsers.add_parser(
        "validate-output",
        aliases=["validate-pack"],
        help="Validate a JSON output file against the output schema",
    )
    validate_parser.add_argument("input_file", help="JSON file to validate")
    validate_parser.add_argument(
        "--schema-file",
        default=str(_default_output_schema_path()),
        help="Optional schema file path; defaults to schemas/output_schema.json",
    )
    brand_kb_parser = subparsers.add_parser(
        "validate-brand-kb",
        aliases=["validate-kb"],
        help="Validate a brand knowledge base JSON file against its schema",
    )
    brand_kb_parser.add_argument("input_file", help="Brand knowledge base JSON file to validate")
    brand_kb_parser.add_argument(
        "--schema-file",
        default=str(_default_brand_kb_schema_path()),
        help="Optional schema file path; defaults to schemas/brand_knowledge_base_schema.json",
    )
    wp_parser = subparsers.add_parser(
        "publish-wordpress",
        help="Publish a markdown draft to WordPress as a draft or published post",
    )
    wp_parser.add_argument("input_file", help="Markdown file to publish")
    wp_parser.add_argument("--site-url", default=None, help="WordPress site URL")
    wp_parser.add_argument("--username", default=None, help="WordPress username")
    wp_parser.add_argument("--app-password", default=None, help="WordPress application password")
    wp_parser.add_argument("--client-id", default=None, help="WordPress.com OAuth client ID")
    wp_parser.add_argument("--client-secret", default=None, help="WordPress.com OAuth client secret")
    wp_parser.add_argument("--status", default="draft", choices=["draft", "publish", "private"], help="Post status")
    wp_parser.add_argument("--post-id", type=int, default=None, help="Optional existing WordPress post ID to update instead of creating a new post")
    wp_parser.add_argument("--title", default=None, help="Optional title override")
    wp_parser.add_argument("--slug", default=None, help="Optional slug override")
    wp_parser.add_argument("--excerpt", default=None, help="Optional excerpt")
    wp_parser.add_argument("--categories", default=None, help="Optional comma-separated WordPress category IDs")
    wp_parser.add_argument("--tags", default=None, help="Optional comma-separated WordPress tag IDs")
    wp_parser.add_argument(
        "--brand-mode",
        default="strict",
        choices=["strict", "warn", "ignore"],
        help="Brand alignment mode. strict blocks on mismatch; warn continues with warning; ignore skips the check.",
    )
    wp_parser.add_argument(
        "--auto-revise",
        action="store_true",
        help="Auto-revise and re-check if the article fails the quality gate.",
    )
    wp_parser.add_argument(
        "--revise-iterations",
        type=int,
        default=2,
        help="Maximum auto-revise iterations when quality fails (default 2).",
    )

    batch_parser = subparsers.add_parser(
        "daily-wordpress-batch",
        parents=[common],
        help="Generate multiple publish-ready articles for the daily window and publish them to WordPress drafts",
    )
    batch_parser.add_argument("--count", type=int, default=3, help="How many article posts to generate and publish")
    batch_parser.add_argument(
        "--brand-kb-file",
        default=str(default_brand_kb_path()),
        help="Brand knowledge base JSON file. Default project path: knowledge/brand/brand-knowledge-base.json",
    )
    batch_parser.add_argument("--site-url", default=None, help="WordPress site URL")
    batch_parser.add_argument("--username", default=None, help="WordPress username")
    batch_parser.add_argument("--app-password", default=None, help="WordPress application password")
    batch_parser.add_argument("--client-id", default=None, help="WordPress.com OAuth client ID")
    batch_parser.add_argument("--client-secret", default=None, help="WordPress.com OAuth client secret")
    batch_parser.add_argument("--status", default="draft", choices=["draft", "publish", "private"], help="Post status")
    batch_parser.add_argument(
        "--output-dir",
        default="examples/daily-wordpress-batch",
        help="Directory to write generated article files before publishing",
    )
    batch_parser.add_argument(
        "--allow-brand-mismatch",
        action="store_true",
        help="Proceed even if brand KB differs from remote snapshot",
    )
    batch_parser.add_argument(
        "--brand-mode",
        default="warn",
        choices=["strict", "warn", "ignore"],
        help="Brand alignment mode for batch runs (default warn).",
    )
    batch_parser.add_argument(
        "--auto-revise",
        action="store_true",
        help="Auto-revise and re-check if an article fails quality.",
    )
    batch_parser.add_argument(
        "--revise-iterations",
        type=int,
        default=2,
        help="Maximum auto-revise iterations when quality fails (default 2).",
    )
    batch_parser.add_argument(
        "--max-retries",
        type=int,
        default=2,
        help="Maximum per-article retries for batch generation (default 2).",
    )
    batch_parser.add_argument(
        "--output-state",
        default=None,
        help="Optional path to write batch state/checkpoint JSON.",
    )

    batch_run_parser = subparsers.add_parser(
        "batch-run",
        parents=[common],
        help="Pure batch generation with retries, quality loop, and structured JSON output (no WordPress publish).",
    )
    batch_run_parser.add_argument(
        "--input-file",
        default=str(default_fanout_backlog_path()),
        help="Backlog JSON file to read; defaults to knowledge/backlog/fanout-backlog.json",
    )
    batch_run_parser.add_argument("--status", default="write_now", help="Backlog status bucket to select from")
    batch_run_parser.add_argument(
        "--brand-kb-file",
        default=str(default_brand_kb_path()),
        help="Brand knowledge base JSON file. Default project path: knowledge/brand/brand-knowledge-base.json",
    )
    batch_run_parser.add_argument(
        "--brand-mode",
        default="warn",
        choices=["strict", "warn", "ignore"],
        help="Brand alignment mode for batch runs (default warn).",
    )
    batch_run_parser.add_argument(
        "--allow-brand-mismatch",
        action="store_true",
        help="Proceed even if brand KB differs from remote snapshot (maps to brand-mode warn).",
    )
    batch_run_parser.add_argument(
        "--auto-revise",
        action="store_true",
        help="Auto-revise and re-check if the article fails the quality gate.",
    )
    batch_run_parser.add_argument(
        "--revise-iterations",
        type=int,
        default=2,
        help="Maximum auto-revise iterations when quality fails (default 2).",
    )
    batch_run_parser.add_argument(
        "--max-retries",
        type=int,
        default=2,
        help="Maximum per-article retries (default 2).",
    )
    batch_run_parser.add_argument(
        "--resume-state",
        default=None,
        help="Optional state file to resume from; will be updated after run.",
    )
    batch_run_parser.add_argument(
        "--quality-mode",
        default="strict",
        choices=["strict", "warn"],
        help="Quality mode for batch runs.",
    )

    keyword_batch_parser = subparsers.add_parser(
        "batch-run-keywords",
        parents=[common],
        help="Run the single-article pipeline over a keyword list with retries and summary JSON",
    )
    keyword_batch_parser.add_argument(
        "--keywords-file",
        required=True,
        help="Text file with one keyword per line",
    )
    keyword_batch_parser.add_argument(
        "--max-retries",
        type=int,
        default=1,
        help="Per-keyword retries (default 1)",
    )
    keyword_batch_parser.add_argument(
        "--output",
        default=None,
        help="Where to write summary JSON; prints to stdout if omitted",
    )
    keyword_batch_parser.add_argument(
        "--auto-revise",
        action="store_true",
        help="Auto-revise and re-check if quality fails",
    )
    keyword_batch_parser.add_argument(
        "--revise-iterations",
        type=int,
        default=2,
        help="Maximum auto-revise iterations when quality fails (default 2)",
    )
    keyword_batch_parser.add_argument(
        "--brand-kb-file",
        default=str(default_brand_kb_path()),
        help="Brand knowledge base JSON file. Default project path: knowledge/brand/brand-knowledge-base.json",
    )
    keyword_batch_parser.add_argument(
        "--brand-mode",
        default="warn",
        choices=["strict", "warn", "ignore"],
        help="Brand alignment mode (default warn).",
    )
    keyword_batch_parser.add_argument(
        "--allow-brand-mismatch",
        action="store_true",
        help="Proceed even if brand KB differs from remote snapshot (maps to brand-mode warn).",
    )
    keyword_batch_parser.add_argument(
        "--resume",
        default=None,
        help="Resume from a previous results JSON (skips keywords already successful)",
    )
    keyword_batch_parser.add_argument(
        "--quality-mode",
        default="strict",
        choices=["strict", "warn"],
        help="Quality mode for keyword batch runs.",
    )

    citation_parser = subparsers.add_parser(
        "analyze-citation-patterns",
        parents=[common],
        help="Fetch top citation pages for one prompt and summarize their content structure",
    )
    citation_parser.add_argument("--prompt-id", default=None, help="Optional prompt ID to target")
    citation_parser.add_argument("--prompt-text", default=None, help="Optional prompt text to target")
    citation_parser.add_argument(
        "--brand-kb-file",
        default=str(default_brand_kb_path()),
        help="Brand knowledge base JSON file. Default project path: knowledge/brand/brand-knowledge-base.json",
    )
    citation_parser.add_argument(
        "--save-learning",
        action="store_true",
        help="Save the citation pattern summary into the local citation learnings file",
    )
    citation_parser.add_argument(
        "--learning-file",
        default=str(_default_citation_learnings_path()),
        help="Where to store citation learnings if --save-learning is used",
    )

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    def emit_output(payload: str) -> None:
        if getattr(args, "output_file", None):
            output_path = Path(args.output_file).expanduser()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(payload, encoding="utf-8")
        print(payload)

    if args.command in {"validate-output", "validate-pack"}:
        input_path = Path(args.input_file).expanduser()
        schema_path = Path(args.schema_file).expanduser()
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        payload = json.loads(input_path.read_text(encoding="utf-8"))
        try:
            validate(instance=payload, schema=schema)
        except ValidationError as exc:
            parser.exit(1, f"Schema validation failed: {exc.message}\n")
        print(f"Schema validation passed: {input_path}")
        return

    if args.command in {"validate-brand-kb", "validate-kb"}:
        input_path = Path(args.input_file).expanduser()
        schema_path = Path(args.schema_file).expanduser()
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        payload = json.loads(input_path.read_text(encoding="utf-8"))
        try:
            validate(instance=payload, schema=schema)
        except ValidationError as exc:
            parser.exit(1, f"Brand knowledge base validation failed: {exc.message}\n")
        print(f"Brand knowledge base validation passed: {input_path}")
        return

    if args.command == "discover-prompts":
        client = DagenoClient(api_key=args.api_key, base_url=args.base_url)
        print(
            json.dumps(
                discover_prompt_candidates(client, days=args.days, max_prompts=args.max_prompts),
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    if args.command == "build-fanout-backlog":
        client = DagenoClient(api_key=args.api_key, base_url=args.base_url)
        published_keys = published_keys_from_registry(load_published_registry(args.published_file))
        backlog = build_fanout_backlog(
            client,
            days=args.days,
            brand_kb_file=args.brand_kb_file,
            max_prompts=args.max_prompts,
            published_keys=published_keys,
            allow_exploratory_fallback=args.allow_exploratory_fallback,
            exploratory_min_write_now=args.exploratory_min_write_now,
            exploratory_max_items=args.exploratory_max_items,
            exploratory_per_prompt=args.exploratory_per_prompt,
        )
        save_fanout_backlog(backlog, args.output_file)
        print(json.dumps(backlog, ensure_ascii=False, indent=2))
        return

    if args.command == "analyze-citation-patterns":
        client = DagenoClient(api_key=args.api_key, base_url=args.base_url)
        from .workflows import _build_content_pack_context

        context = _build_content_pack_context(
            client,
            args.days,
            prompt_id=args.prompt_id,
            prompt_text=args.prompt_text,
            brand_kb_file=args.brand_kb_file,
            detail_limit=1,
        )
        urls = [item.get("url") for item in context.get("citations", []) if item.get("url")]
        pages = crawl_citation_pages(urls, limit=args.limit)
        patterns = analyze_citation_patterns(pages)
        payload = {"pages": pages, "patterns": patterns}
        if args.save_learning:
            save_citation_learning(
                {
                    "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                    "prompt_text": context.get("selected_opportunity", {}).get("prompt"),
                    "brand_context_summary": context.get("brand_context", {}),
                    "patterns": patterns,
                },
                args.learning_file,
            )
            payload["learning_file"] = args.learning_file
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    if args.command == "select-backlog-items":
        backlog = load_fanout_backlog(args.input_file)
        published_keys = None
        if not args.include_published:
            published_keys = published_keys_from_registry(load_published_registry(args.published_file))
        print(
            json.dumps(
                select_backlog_items(backlog, limit=args.top_n, status=args.status, published_keys=published_keys),
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    if args.command == "mark-published":
        registry = load_published_registry(args.published_file)
        registry = add_published_item(
            registry,
            backlog_id=args.backlog_id,
            canonical_key=args.canonical_key,
            fanout_text=args.fanout_text,
            published_url=args.url,
        )
        save_published_registry(registry, args.published_file)
        print(json.dumps(registry, ensure_ascii=False, indent=2))
        return

    if args.command == "article-generation-payload":
        client = DagenoClient(api_key=args.api_key, base_url=args.base_url)
        brand_mode = args.brand_mode
        if getattr(args, "allow_brand_mismatch", False) and brand_mode == "strict":
            brand_mode = "warn"
        print(
            json.dumps(
                article_generation_payload(
                    client,
                    days=args.days,
                    backlog_id=args.backlog_id,
                    backlog_file=args.backlog_file,
                    prompt_id=args.prompt_id,
                    prompt_text=args.prompt_text,
                    asset_id=args.asset_id,
                    brand_kb_file=args.brand_kb_file,
                    citation_limit=args.citation_limit,
                    brand_mode=brand_mode,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    if args.command == "draft-article-from-payload":
        input_path = Path(args.input_file).expanduser()
        payload = json.loads(input_path.read_text(encoding="utf-8"))
        min_words = int(payload.get("min_word_count", 0) or 1200)
        article_markdown, quality = _generate_and_check(
            payload,
            min_words=min_words,
            auto_revise=args.auto_revise,
            max_iterations=args.revise_iterations,
            quality_mode=args.quality_mode,
        )
        if args.output_file:
            Path(args.output_file).expanduser().write_text(article_markdown, encoding="utf-8")
        emit_output(article_markdown)
        if args.auto_revise:
            print(json.dumps({"quality": quality}, ensure_ascii=False, indent=2))
        return

    if args.command == "check-article-quality":
        input_path = Path(args.input_file).expanduser()
        markdown_text = input_path.read_text(encoding="utf-8")
        report = _article_quality_report(markdown_text, min_words=args.min_words, mode=args.quality_mode)
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            status = "PASS" if report["passed"] else "FAIL"
            print(f"Quality Gate: {status}")
            for name, ok in report["checks"].items():
                print(f"- {name}: {'PASS' if ok else 'FAIL'}")
            metrics = report["metrics"]
            print(f"- word_count: {metrics['word_count']} (min {metrics['min_words_required']})")
            print(f"- reference_count: {metrics['reference_count']}")
            print(f"- not_ideal_count: {metrics['not_ideal_count']}")
            if metrics["missing_sections"]:
                print("- missing_sections:")
                for section in metrics["missing_sections"]:
                    print(f"  - {section}")
        if not report["passed"]:
            parser.exit(1, "Article quality gate failed.\n")
        return

    if args.command == "publish-wordpress":
        input_path = Path(args.input_file).expanduser()
        markdown_text = input_path.read_text(encoding="utf-8")
        publishable_markdown = _extract_publishable_markdown(markdown_text)
        inferred_title, inferred_slug = _derive_title_and_slug(markdown_text)
        client = WordPressClient(
            site_url=args.site_url,
            username=args.username,
            app_password=args.app_password,
            client_id=args.client_id,
            client_secret=args.client_secret,
        )
        html_content = markdown_to_basic_html(publishable_markdown)
        if args.post_id:
            result = client.update_post(
                args.post_id,
                title=args.title or inferred_title,
                content=html_content,
                status=args.status,
                slug=args.slug or inferred_slug,
                excerpt=args.excerpt,
                categories=_parse_taxonomy_ids(args.categories),
                tags=_parse_taxonomy_ids(args.tags),
            )
        else:
            result = client.create_post(
                title=args.title or inferred_title,
                content=html_content,
                status=args.status,
                slug=args.slug or inferred_slug,
                excerpt=args.excerpt,
                categories=_parse_taxonomy_ids(args.categories),
                tags=_parse_taxonomy_ids(args.tags),
            )
        print(
            json.dumps(
                {
                    "id": result.get("id"),
                    "status": result.get("status"),
                    "link": result.get("link"),
                    "slug": result.get("slug"),
                    "title": ((result.get("title") or {}).get("rendered") if isinstance(result.get("title"), dict) else result.get("title")),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    if args.command == "publish-ready-article":
        brand_mode = args.brand_mode
        if args.allow_brand_mismatch and brand_mode == "strict":
            brand_mode = "warn"
        emit_output(
            json.dumps(
                article_generation_payload(
                    client=DagenoClient(api_key=args.api_key, base_url=args.base_url),
                    days=args.days,
                    backlog_id=args.backlog_id,
                    backlog_file=args.backlog_file,
                    prompt_id=args.prompt_id,
                    prompt_text=args.prompt_text,
                    asset_id=args.asset_id,
                    brand_kb_file=args.brand_kb_file,
                    allow_brand_mismatch=args.allow_brand_mismatch,
                    brand_mode=brand_mode,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    if args.command == "legacy-publish-ready-article":
        brand_mode = args.brand_mode
        if args.allow_brand_mismatch and brand_mode == "strict":
            brand_mode = "warn"
        emit_output(
            legacy_publish_ready_article(
                client=DagenoClient(api_key=args.api_key, base_url=args.base_url),
                days=args.days,
                prompt_id=args.prompt_id,
                prompt_text=args.prompt_text,
                asset_id=args.asset_id,
                brand_kb_file=args.brand_kb_file,
                allow_brand_mismatch=args.allow_brand_mismatch,
                brand_mode=brand_mode,
            )
        )
        return

    if args.command == "daily-wordpress-batch":
        dclient = DagenoClient(api_key=args.api_key, base_url=args.base_url)
        wp_client = WordPressClient(
            site_url=args.site_url,
            username=args.username,
            app_password=args.app_password,
            client_id=args.client_id,
            client_secret=args.client_secret,
        )
        output_dir = Path(args.output_dir).expanduser()
        output_dir.mkdir(parents=True, exist_ok=True)
        brand_mode = args.brand_mode
        if args.allow_brand_mismatch and brand_mode == "strict":
            brand_mode = "warn"
        backlog = _retry(
            "build_fanout_backlog",
            attempts=2,
            func=lambda: build_fanout_backlog(
                dclient,
                days=args.days,
                brand_kb_file=args.brand_kb_file,
                max_prompts=max(args.count * 2, 10),
                allow_exploratory_fallback=False,
            ),
        )
        selected_rows = select_backlog_items(backlog, limit=args.count, status="write_now")["items"]
        results = []
        per_item_attempts = 3
        per_item_delay = 1.2
        min_words_floor = 1200
        for row in selected_rows:
            last_exc = None
            for attempt in range(1, per_item_attempts + 1):
                try:
                    payload = article_generation_payload_from_backlog_row(
                        dclient,
                        row,
                        days=args.days,
                        brand_kb_file=args.brand_kb_file,
                        backlog_rows=backlog.get("fanout_backlog", []),
                        allow_brand_mismatch=args.allow_brand_mismatch,
                        brand_mode=brand_mode,
                    )
                    min_word_count = max(min_words_floor, int(payload.get("min_word_count", 0) or 0))
                    article_markdown, quality = _generate_and_check(
                        payload,
                        min_words=min_word_count,
                        auto_revise=args.auto_revise,
                        max_iterations=args.revise_iterations,
                        quality_mode=getattr(args, "quality_mode", "strict"),
                    )
                    actual_word_count = quality["metrics"]["word_count"]
                    slug = row.get("backlog_id") or _derive_title_and_slug(article_markdown)[1]
                    title = (payload.get("title_options") or [row.get("normalized_title", "Untitled Article")])[0]
                    output_path = output_dir / f"{slug}.md"
                    output_path.write_text(article_markdown, encoding="utf-8")
                    if not quality["passed"]:
                        if attempt < per_item_attempts:
                            time.sleep(per_item_delay * attempt)
                            continue
                        results.append(
                            {
                                "backlog_id": row.get("backlog_id"),
                                "title": title,
                                "file": str(output_path),
                                "status": "quality_fail",
                                "quality": quality,
                            }
                        )
                        break
                    post = _retry(
                        "wordpress_create_post",
                        attempts=2,
                        delay=per_item_delay,
                        func=lambda: wp_client.create_post(
                            title=title,
                            content=markdown_to_basic_html(article_markdown),
                            status=args.status,
                            slug=slug,
                        ),
                    )
                    results.append(
                        {
                            "backlog_id": row.get("backlog_id"),
                            "title": title,
                            "file": str(output_path),
                            "wordpress_post_id": post.get("id"),
                            "status": post.get("status"),
                            "link": post.get("link"),
                            "actual_word_count": actual_word_count,
                            "min_word_count": min_word_count,
                            "quality": quality,
                        }
                    )
                    break
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
                    if attempt < per_item_attempts:
                        time.sleep(per_item_delay * attempt)
                        continue
                    results.append(
                        {
                            "backlog_id": row.get("backlog_id"),
                            "title": row.get("normalized_title", "Untitled Article"),
                            "status": "error",
                            "error": str(last_exc),
                        }
                    )
                    break
        print(json.dumps({"count": len(results), "items": results}, ensure_ascii=False, indent=2))
        return

    if args.command == "batch-run":
        dclient = DagenoClient(api_key=args.api_key, base_url=args.base_url)
        backlog = load_fanout_backlog(args.input_file)
        selected_rows = select_backlog_items(backlog, limit=args.limit, status=args.status)["items"]
        processed_ids = set()
        if args.resume_state and Path(args.resume_state).exists():
            try:
                state = json.loads(Path(args.resume_state).read_text(encoding="utf-8"))
                processed_ids = set(state.get("processed_ids", []))
            except Exception:
                processed_ids = set()
        brand_mode = args.brand_mode
        if args.allow_brand_mismatch and brand_mode == "strict":
            brand_mode = "warn"
        per_item_attempts = max(1, args.max_retries)
        min_words_floor = 1200
        results = []
        for row in selected_rows:
            row_id = row.get("backlog_id") or row.get("id")
            if row_id in processed_ids:
                continue
            status = "pass"
            last_exc = None
            quality = {}
            article_markdown = ""
            publish_state = False
            for attempt in range(1, per_item_attempts + 1):
                try:
                    payload = article_generation_payload_from_backlog_row(
                        dclient,
                        row,
                        days=args.days,
                        brand_kb_file=args.brand_kb_file,
                        backlog_rows=backlog.get("fanout_backlog", []),
                        allow_brand_mismatch=args.allow_brand_mismatch,
                        brand_mode=brand_mode,
                    )
                    min_word_count = max(min_words_floor, int(payload.get("min_word_count", 0) or 0))
                    article_markdown, quality = _generate_and_check(
                        payload,
                        min_words=min_word_count,
                        auto_revise=args.auto_revise,
                        max_iterations=args.revise_iterations,
                        quality_mode=args.quality_mode,
                    )
                    if quality.get("passed"):
                        status = "pass"
                        break
                    status = "quality_fail"
                    if attempt < per_item_attempts:
                        time.sleep(1.0 * attempt)
                        continue
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
                    status = "error"
                    if attempt < per_item_attempts:
                        time.sleep(1.0 * attempt)
                        continue
            results.append(
                {
                    "backlog_id": row_id,
                    "title": row.get("normalized_title"),
                    "keyword": row.get("fanout_text") or row.get("prompt_text"),
                    "status": status,
                    "quality": quality,
                    "published": publish_state,
                    "error": str(last_exc) if last_exc else None,
                }
            )
            processed_ids.add(row_id)
            if args.resume_state:
                Path(args.resume_state).write_text(
                    json.dumps({"processed_ids": sorted(processed_ids), "items": results}, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
        total = len(selected_rows)
        success = len([r for r in results if r["status"] == "pass"])
        failed = total - success
        failed_ids = [r["backlog_id"] for r in results if r["status"] != "pass"]
        output = {
            "total": total,
            "success": success,
            "failed": failed,
            "failed_ids": failed_ids,
            "results": results,
        }
        if args.resume_state:
            Path(args.resume_state).write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return

    if args.command == "batch-run-keywords":
        keywords_path = Path(args.keywords_file).expanduser()
        if not keywords_path.exists():
            raise FileNotFoundError(f"keywords file not found: {keywords_path}")
        keywords = [line.strip() for line in keywords_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not keywords:
            print(json.dumps({"total": 0, "success": 0, "failed": 0, "results": []}, ensure_ascii=False, indent=2))
            return

        resume_ok = set()
        if args.resume and Path(args.resume).exists():
            try:
                prev = json.loads(Path(args.resume).read_text(encoding="utf-8"))
                for item in prev.get("results", []):
                    if item.get("success"):
                        resume_ok.add(item.get("keyword"))
            except Exception:
                resume_ok = set()

        brand_mode = args.brand_mode
        if args.allow_brand_mismatch and brand_mode == "strict":
            brand_mode = "warn"
        per_item_attempts = max(1, args.max_retries)
        min_words_floor = 1200
        results = []
        total = len(keywords)
        success = 0
        for kw in keywords:
            if kw in resume_ok:
                results.append({"keyword": kw, "success": True, "attempts": 0, "status": "skipped_resume"})
                success += 1
                continue
            attempts = 0
            success_flag = False
            last_exc = None
            quality = {}
            for attempt in range(1, per_item_attempts + 1):
                attempts = attempt
                try:
                    # Use existing pipeline: discover prompt -> build payload from keyword seed
                    payload = article_generation_payload(
                        client=DagenoClient(api_key=args.api_key, base_url=args.base_url),
                        days=args.days,
                        prompt_text=kw,
                        brand_kb_file=args.brand_kb_file,
                        brand_mode=brand_mode,
                        allow_brand_mismatch=args.allow_brand_mismatch,
                    )
                    min_word_count = max(min_words_floor, int(payload.get("min_word_count", 0) or 0))
                    article_markdown, quality = _generate_and_check(
                        payload,
                        min_words=min_word_count,
                        auto_revise=args.auto_revise,
                        max_iterations=args.revise_iterations,
                    )
                    success_flag = quality.get("passed", False)
                    if success_flag:
                        break
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
            results.append(
                {
                    "keyword": kw,
                    "success": success_flag,
                    "attempts": attempts,
                    "status": "pass" if success_flag else ("error" if last_exc else "quality_fail"),
                    "quality": quality,
                    "error": str(last_exc) if last_exc else None,
                }
            )
            if success_flag:
                success += 1
        failed = total - success
        output = {"total": total, "success": success, "failed": failed, "results": results}
        if args.output:
            Path(args.output).expanduser().write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return

    client = DagenoClient(api_key=args.api_key, base_url=args.base_url)

    if args.command == "brand-snapshot":
        print(brand_snapshot(client))
    elif args.command == "topic-watchlist":
        print(topic_watchlist(client, days=args.days, limit=args.limit))
    elif args.command == "prompt-gap":
        print(prompt_gap_report(client, days=args.days, limit=args.limit))
    elif args.command == "citation-brief":
        print(citation_source_brief(client, days=args.days, limit=args.limit))
    elif args.command == "content-opportunities":
        print(content_opportunity_brief(client, days=args.days, limit=args.limit))
    elif args.command == "backlink-opportunities":
        print(backlink_opportunity_brief(client, days=args.days, limit=args.limit))
    elif args.command == "community-opportunities":
        print(community_opportunity_brief(client, days=args.days, limit=args.limit))
    elif args.command in {"content-pack", "pack"}:
        if args.compact_json:
            emit_output(
                json.dumps(
                    content_pack_compact_json(
                        client,
                        days=args.days,
                        prompt_id=args.prompt_id,
                        prompt_text=args.prompt_text,
                        brand_kb_file=args.brand_kb_file,
                    ),
                    ensure_ascii=False,
                    indent=2,
                )
            )
        elif args.output_json:
            emit_output(
                json.dumps(
                    content_pack_json(
                        client,
                        days=args.days,
                        prompt_id=args.prompt_id,
                        prompt_text=args.prompt_text,
                        brand_kb_file=args.brand_kb_file,
                    ),
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            emit_output(
                content_pack(
                    client,
                    days=args.days,
                    limit=args.limit,
                    prompt_id=args.prompt_id,
                    prompt_text=args.prompt_text,
                    brand_kb_file=args.brand_kb_file,
                    compact=args.compact,
                )
            )
    elif args.command in {"first-asset-draft", "draft-first"}:
        emit_output(
            first_asset_draft(
                client,
                days=args.days,
                prompt_id=args.prompt_id,
                prompt_text=args.prompt_text,
                asset_id=args.asset_id,
                brand_kb_file=args.brand_kb_file,
            )
        )
    elif args.command == "new-content-brief":
        print(
            new_content_brief(
                client,
                days=args.days,
                limit=args.limit,
                prompt_id=args.prompt_id,
                prompt_text=args.prompt_text,
            )
        )
    elif args.command == "prompt-deep-dive":
        print(prompt_deep_dive(client, prompt_id=args.prompt_id, days=args.days, limit=args.limit))
    elif args.command == "weekly-brief":
        print(weekly_exec_brief(client, days=args.days, limit=args.limit))
    else:
        parser.error(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
