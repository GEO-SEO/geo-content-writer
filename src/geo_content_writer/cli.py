from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

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
    discover_prompt_candidates,
    build_fanout_backlog,
    load_fanout_backlog,
    save_fanout_backlog,
    select_backlog_items,
    daily_publish_ready_package,
    first_asset_draft,
    new_content_brief,
    publish_ready_article,
    prompt_deep_dive,
    prompt_gap_report,
    topic_watchlist,
    weekly_exec_brief,
)
from .wordpress import WordPressClient, markdown_to_basic_html


def _default_output_schema_path() -> Path:
    return Path(__file__).resolve().parents[2] / "schemas" / "output_schema.json"


def _default_brand_kb_schema_path() -> Path:
    return Path(__file__).resolve().parents[2] / "schemas" / "brand_knowledge_base_schema.json"


def _default_fanout_backlog_path() -> Path:
    return default_fanout_backlog_path()


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
    backlog_parser.add_argument("--max-prompts", type=int, default=20, help="How many prompt candidates to inspect")
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
        help="Generate a publish-ready article from the top article asset using the project's fixed writing policy",
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
        "--output-file",
        default=None,
        help="Optional file path to write the publish-ready article output",
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
        backlog = build_fanout_backlog(
            client,
            days=args.days,
            brand_kb_file=args.brand_kb_file,
            max_prompts=args.max_prompts,
        )
        save_fanout_backlog(backlog, args.output_file)
        print(json.dumps(backlog, ensure_ascii=False, indent=2))
        return

    if args.command == "select-backlog-items":
        backlog = load_fanout_backlog(args.input_file)
        print(
            json.dumps(
                select_backlog_items(backlog, limit=args.top_n, status=args.status),
                ensure_ascii=False,
                indent=2,
            )
        )
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
        emit_output(
            publish_ready_article(
                client=DagenoClient(api_key=args.api_key, base_url=args.base_url),
                days=args.days,
                prompt_id=args.prompt_id,
                prompt_text=args.prompt_text,
                asset_id=args.asset_id,
                brand_kb_file=args.brand_kb_file,
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
        package = daily_publish_ready_package(
            client=dclient,
            days=args.days,
            count=args.count,
            brand_kb_file=args.brand_kb_file,
        )
        results = []
        for item in package:
            output_path = output_dir / f"{item['slug']}.md"
            output_path.write_text(item["markdown"], encoding="utf-8")
            post = wp_client.create_post(
                title=item["title"],
                content=markdown_to_basic_html(item["markdown"]),
                status=args.status,
                slug=item["slug"],
            )
            results.append(
                {
                    "asset_id": item["asset_id"],
                    "title": item["title"],
                    "file": str(output_path),
                    "wordpress_post_id": post.get("id"),
                    "status": post.get("status"),
                    "link": post.get("link"),
                }
            )
        print(json.dumps({"count": len(results), "items": results}, ensure_ascii=False, indent=2))
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
