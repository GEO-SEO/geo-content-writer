from __future__ import annotations

from collections import Counter
from difflib import get_close_matches
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Tuple

from .client import DagenoClient


def date_window(days: int) -> Tuple[str, str]:
    end_at = datetime.now(timezone.utc).replace(microsecond=0)
    start_at = end_at - timedelta(days=days)
    return (
        start_at.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        end_at.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
    )


def default_brand_kb_path() -> Path:
    return Path(__file__).resolve().parents[2] / "knowledge" / "brand" / "brand-knowledge-base.json"


def _fmt_number(value: Any, digits: int = 2) -> str:
    if value is None:
        return "-"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _normalize_gap_score(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    return numeric * 100 if 0 <= numeric <= 1 else numeric


def _fmt_gap(value: Any) -> str:
    normalized = _normalize_gap_score(value)
    if normalized == int(normalized):
        return f"{int(normalized)}%"
    return f"{normalized:.2f}%"


def _top(items: Iterable[Dict[str, Any]], key: str, limit: int) -> List[Dict[str, Any]]:
    return sorted(items, key=lambda item: item.get(key) or 0, reverse=True)[:limit]


def _collect_all(fetch_page, *, page_size: int = 100, max_pages: int = 20) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    page = 1
    while page <= max_pages:
        resp = fetch_page(page=page, page_size=page_size)
        page_items = resp.get("data", {}).get("items", [])
        items.extend(page_items)
        pagination = resp.get("meta", {}).get("pagination", {})
        total_pages = pagination.get("totalPages", page)
        if page >= total_pages or not page_items:
            break
        page += 1
    return items


def _normalize_text(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def _pick_best_content_opportunity(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    ranked = sorted(
        items,
        key=lambda item: (
            item.get("brandGap") or 0,
            item.get("sourceGap") or 0,
            item.get("totalResponseCount") or 0,
            item.get("totalSourceCount") or 0,
        ),
        reverse=True,
    )
    return ranked[0] if ranked else {}


def _opportunity_score(item: Dict[str, Any]) -> float:
    brand_gap = _normalize_gap_score(item.get("brandGap"))
    source_gap = _normalize_gap_score(item.get("sourceGap"))
    responses = float(item.get("totalResponseCount") or 0)
    sources = float(item.get("totalSourceCount") or 0)
    return brand_gap * 0.35 + source_gap * 0.25 + min(responses, 100) * 0.30 + min(sources, 100) * 0.10


def _opportunity_tier(item: Dict[str, Any]) -> str:
    brand_gap = _normalize_gap_score(item.get("brandGap"))
    source_gap = _normalize_gap_score(item.get("sourceGap"))
    responses = float(item.get("totalResponseCount") or 0)
    score = _opportunity_score(item)
    if score >= 70 and brand_gap >= 80 and source_gap >= 70 and responses >= 10:
        return "High"
    if score >= 40:
        return "Medium"
    return "Low"


def _publish_surface_from_asset_type(asset_type: str) -> str:
    mapping = {
        "article": "website_blog",
        "landing_page": "landing_page",
        "docs": "docs_page",
        "comparison": "comparison_page",
        "community": "community_post",
        "third_party": "third_party_article",
    }
    return mapping.get(asset_type, "website_blog")


def _normalize_intention_label(item: Dict[str, Any]) -> str:
    return item.get("intention") or item.get("i") or "-"


def _primary_intention(intentions: List[Dict[str, Any]]) -> str:
    if not intentions:
        return "-"
    def score(item: Dict[str, Any]) -> float:
        raw = item.get("score")
        if raw is None:
            raw = item.get("s")
        try:
            return float(raw)
        except (TypeError, ValueError):
            return 0.0
    best = sorted(intentions, key=score, reverse=True)[0]
    return _normalize_intention_label(best)


def _fanout_prompt_guesses(prompt_text: str, topic: str, primary_intent: str) -> List[str]:
    base = prompt_text.strip()
    topic_part = topic.strip() if topic else "the topic"
    return [
        f"what is {base.lower()}",
        f"best {topic_part.lower()} platforms for enterprises",
        f"how to evaluate {topic_part.lower()} solutions",
        f"{topic_part.lower()} software for enterprise teams",
        f"how to measure results from {topic_part.lower()}",
    ]


def _keyword_cluster_guesses(prompt_text: str, topic: str) -> List[str]:
    seed = prompt_text.lower()
    topic_key = topic.lower() if topic else "topic"
    variants = [
        seed,
        f"enterprise {topic_key} solutions",
        f"{topic_key} platform",
        f"{topic_key} software",
        f"{topic_key} tools",
        f"{topic_key} for enterprise brands",
    ]
    seen = []
    for item in variants:
        item = " ".join(item.split())
        if item not in seen:
            seen.append(item)
    return seen


def _dedupe_keep_order(values: List[str]) -> List[str]:
    seen = set()
    output: List[str] = []
    for value in values:
        key = value.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(value.strip())
    return output


def _page_type_family(citations: List[Dict[str, Any]]) -> str:
    page_types = [c.get("pageType") or "Unknown" for c in citations]
    if not page_types:
        return "Unknown"
    return Counter(page_types).most_common(1)[0][0]


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower())
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-")
    return cleaned or "untitled"


def _publish_target_type(asset_type: str) -> str:
    mapping = {
        "article": "editorial",
        "landing_page": "commercial",
        "docs": "editorial",
        "comparison": "commercial",
        "community": "community",
    }
    return mapping.get(asset_type, "editorial")


def _target_site_section(asset_type: str, publish_surface: str) -> str:
    if publish_surface == "community_post":
        return "community"
    if publish_surface == "third_party_article":
        return "external-contributions"
    if asset_type == "landing_page":
        return "solutions"
    return "blog"


def _required_content_blocks(asset_type: str, target_intent: str) -> List[str]:
    blocks = ["direct_answer", "proof_points", "faq"]
    if asset_type == "landing_page":
        return ["direct_answer", "proof_points", "comparison_table", "cta", "faq"]
    if target_intent in {"Commercial", "Transactional"}:
        blocks.insert(1, "evaluation_framework")
    else:
        blocks.insert(1, "definition")
    return blocks


def _schema_type(asset_type: str, publish_surface: str) -> str:
    if publish_surface == "community_post":
        return "DiscussionForumPosting"
    if asset_type == "landing_page":
        return "WebPage + FAQPage"
    if publish_surface == "third_party_article":
        return "Article"
    return "Article + FAQPage"


def _cta_goal(asset_type: str, target_intent: str) -> str:
    if asset_type == "landing_page":
        return "demo_request"
    if target_intent in {"Commercial", "Transactional"}:
        return "commercial_consideration"
    return "newsletter_or_retargeting"


def _asset_rows(
    *,
    prompt_text: str,
    opportunity_tier: str,
    topic: str,
    primary_intent: str,
    dominant_page_type: str,
    brand_context: Dict[str, Any] | None = None,
) -> List[Dict[str, Any]]:
    topic_l = topic or "topic"
    intent = primary_intent if primary_intent != "-" else "Informational"
    derived_common = ["high_brand_gap", "high_source_gap", "repeated_response_framing"]
    rows = [
        {
            "asset_id": "A1",
            "asset_title": f"What Is an Enterprise {topic_l} Solution?",
            "asset_type": "article",
            "recommended_publish_surface": "website_blog",
            "target_intent": "Informational",
            "primary_angle": "Define the category and frame the enterprise problem clearly.",
            "why_exists": "AI answers repeatedly define the topic before recommending anything else.",
            "derived_from": derived_common + ["dominant_article_citations"],
            "writing_inputs": ["top_response_details", "top_citation_urls", "dageno_product_positioning"],
            "priority": "high",
        },
        {
            "asset_id": "A2",
            "asset_title": f"How to Evaluate Enterprise {topic_l} Platforms",
            "asset_type": "article",
            "recommended_publish_surface": "website_blog",
            "target_intent": "Commercial",
            "primary_angle": "Turn the prompt into a buyer-side evaluation framework.",
            "why_exists": "The prompt is close to purchase-stage evaluation and solution selection.",
            "derived_from": derived_common + ["high_transactional_intent", "fanout_prompt_cluster"],
            "writing_inputs": ["top_response_details", "top_entities_in_mentions", "fanout_prompt_set", "keyword_cluster"],
            "priority": "high",
        },
        {
            "asset_id": "A3",
            "asset_title": f"Best Enterprise {topic_l} Solutions for Brand Authority",
            "asset_type": "article",
            "recommended_publish_surface": "third_party_article" if dominant_page_type == "Listicle" else "website_blog",
            "target_intent": intent,
            "primary_angle": "Compete directly with the landscape that AI is already citing.",
            "why_exists": "Citation patterns show that the market already rewards roundup and recommendation-style content.",
            "derived_from": derived_common + ["dominant_listicle_citations", "keyword_search_demand"],
            "writing_inputs": ["top_citation_urls", "top_entities_in_mentions", "fanout_prompt_set", "keyword_cluster"],
            "priority": "high",
        },
        {
            "asset_id": "A4",
            "asset_title": f"How to Measure Brand Authority in AI Answers",
            "asset_type": "article",
            "recommended_publish_surface": "website_blog",
            "target_intent": "Commercial",
            "primary_angle": "Translate brand authority into measurable AI visibility and citation metrics.",
            "why_exists": "The answer space talks about authority, but buyers still need measurable evaluation criteria.",
            "derived_from": derived_common + ["response_metric_gap", "fanout_prompt_cluster"],
            "writing_inputs": ["top_response_details", "top_citation_urls", "dageno_product_positioning"],
            "priority": "medium",
        },
        {
            "asset_id": "A5",
            "asset_title": f"Enterprise {topic_l} Platform for Brand Authority",
            "asset_type": "landing_page",
            "recommended_publish_surface": "landing_page",
            "target_intent": intent,
            "primary_angle": "Commercial landing page for future conversion capture.",
            "why_exists": "The prompt is BOFU and should leave room for future landing-page generation.",
            "derived_from": derived_common + ["future_landing_page_branch"],
            "writing_inputs": ["dageno_product_positioning", "keyword_cluster", "top_citation_urls"],
            "priority": "medium",
        },
    ]
    for row in rows:
        row["source_prompt"] = prompt_text
        row["opportunity_tier"] = opportunity_tier
        row["publish_target_type"] = _publish_target_type(row["asset_type"])
        row["target_site_section"] = _target_site_section(
            row["asset_type"], row["recommended_publish_surface"]
        )
        row["target_url_slug"] = _slugify(row["asset_title"])
        row["target_query_cluster"] = topic_l
        row["required_content_blocks"] = _required_content_blocks(
            row["asset_type"], row["target_intent"]
        )
        row["schema_type"] = _schema_type(
            row["asset_type"], row["recommended_publish_surface"]
        )
        row["cta_goal"] = _cta_goal(row["asset_type"], row["target_intent"])
        row["status"] = "planned"
        row["notes"] = ""
    return rows


def _find_prompt_match(
    prompt_items: List[Dict[str, Any]],
    *,
    prompt_id: str | None = None,
    prompt_text: str | None = None,
) -> Dict[str, Any]:
    if prompt_id:
        for item in prompt_items:
            if item.get("id") == prompt_id:
                return item

    normalized_map = {
        _normalize_text(item.get("prompt", "")): item for item in prompt_items if item.get("prompt")
    }
    if prompt_text:
        normalized = _normalize_text(prompt_text)
        if normalized in normalized_map:
            return normalized_map[normalized]
        matches = get_close_matches(normalized, list(normalized_map.keys()), n=1, cutoff=0.75)
        if matches:
            return normalized_map[matches[0]]

    return {}


def _choose_asset_type(
    *,
    prompt_volume: float | int | None,
    brand_gap: float | int | None,
    source_gap: float | int | None,
    response_count: float | int | None,
) -> str:
    pv = prompt_volume or 0
    bg = _normalize_gap_score(brand_gap)
    sg = _normalize_gap_score(source_gap)
    rc = response_count or 0
    if (bg >= 80 and sg >= 60) or (pv >= 20 and rc >= 20):
        return "Pillar"
    if bg >= 40 or sg >= 40 or rc >= 8 or pv >= 5:
        return "Standard"
    return "Lightweight"


def _format_intentions(intentions: List[Dict[str, Any]]) -> str:
    if not intentions:
        return "-"
    bits = []
    for item in intentions:
        intention = item.get("intention") or item.get("i") or "-"
        score = item.get("score")
        if score is None:
            score = item.get("s")
        bits.append(f"{intention} ({score})" if score is not None else intention)
    return ", ".join(bits)


def _response_preview(text: str, limit: int = 420) -> str:
    flat = " ".join((text or "").strip().split())
    return flat[:limit] + ("..." if len(flat) > limit else "")


def _summarize_mentions(detail: Dict[str, Any], limit: int = 5) -> List[str]:
    mentions = detail.get("mentions") or []
    lines: List[str] = []
    for item in mentions[:limit]:
        brand = item.get("brandName") or item.get("domain") or "-"
        domain = item.get("domain")
        position = item.get("position")
        sentiment = item.get("sentimentScore")
        extras = []
        if domain:
            extras.append(domain)
        if position is not None:
            extras.append(f"position {position}")
        if sentiment is not None:
            extras.append(f"sentiment {sentiment}")
        suffix = f" ({', '.join(extras)})" if extras else ""
        lines.append(f"- {brand}{suffix}")
    return lines


def _content_angles(selected: Dict[str, Any], detail: Dict[str, Any], citation_urls: List[Dict[str, Any]]) -> List[str]:
    angles: List[str] = []
    topic = selected.get("topic")
    if topic:
        angles.append(f"Define the topic clearly and claim category relevance around `{topic}`.")
    mentions = detail.get("mentions") or []
    competitor_mentions = [m for m in mentions if m.get("brandName")]
    if competitor_mentions:
        brands = ", ".join(
            sorted({m.get("brandName") for m in competitor_mentions if m.get("brandName")})
        )
        angles.append(f"Address competitor-framed expectations directly, especially against {brands}.")
    if citation_urls:
        page_types = [item.get("pageType") for item in citation_urls if item.get("pageType")]
        if page_types:
            types = ", ".join(sorted(set(page_types))[:3])
            angles.append(f"Mirror citation-friendly structure seen in cited sources, especially {types} pages.")
        else:
            angles.append("Use a citation-friendly structure: definition first, short sections, and source-backed claims.")
    if not angles:
        angles.append("Write a direct, definition-first article with strong evidence blocks and extractable subheadings.")
    return angles[:4]


def _render_asset_table(rows: List[Dict[str, Any]]) -> List[str]:
    header = [
        "| asset_id | source_prompt | opportunity_tier | asset_title | asset_type | publish_target_type | recommended_publish_surface | target_site_section | target_url_slug | target_intent | target_query_cluster | primary_angle | why_exists | derived_from | writing_inputs | required_content_blocks | schema_type | cta_goal | priority | status | notes |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    lines = header[:]
    for row in rows:
        lines.append(
            "| {asset_id} | {source_prompt} | {opportunity_tier} | {asset_title} | {asset_type} | {publish_target_type} | {recommended_publish_surface} | {target_site_section} | {target_url_slug} | {target_intent} | {target_query_cluster} | {primary_angle} | {why_exists} | {derived_from} | {writing_inputs} | {required_content_blocks} | {schema_type} | {cta_goal} | {priority} | {status} | {notes} |".format(
                asset_id=row["asset_id"],
                source_prompt=row["source_prompt"].replace("|", "/"),
                opportunity_tier=row["opportunity_tier"],
                asset_title=row["asset_title"].replace("|", "/"),
                asset_type=row["asset_type"],
                publish_target_type=row["publish_target_type"],
                recommended_publish_surface=row["recommended_publish_surface"],
                target_site_section=row["target_site_section"],
                target_url_slug=row["target_url_slug"],
                target_intent=row["target_intent"],
                target_query_cluster=row["target_query_cluster"].replace("|", "/"),
                primary_angle=row["primary_angle"].replace("|", "/"),
                why_exists=row["why_exists"].replace("|", "/"),
                derived_from=", ".join(row["derived_from"]).replace("|", "/"),
                writing_inputs=", ".join(row["writing_inputs"]).replace("|", "/"),
                required_content_blocks=", ".join(row["required_content_blocks"]).replace("|", "/"),
                schema_type=row["schema_type"],
                cta_goal=row["cta_goal"],
                priority=row["priority"],
                status=row["status"],
                notes=row["notes"] or "-",
            )
        )
    return lines


def _resolve_brand_kb_path(brand_kb_file: str | None) -> Path:
    return Path(brand_kb_file).expanduser() if brand_kb_file else default_brand_kb_path()


def _load_brand_kb(brand_kb_file: str | None) -> Dict[str, Any]:
    path = _resolve_brand_kb_path(brand_kb_file)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _brand_kb_status(brand_kb_file: str | None) -> Dict[str, Any]:
    path = _resolve_brand_kb_path(brand_kb_file)
    loaded = path.exists()
    return {
        "path": str(path),
        "loaded": loaded,
        "message": (
            "Brand knowledge base loaded from the standard project location."
            if loaded
            else "Brand knowledge base missing. Create one at the standard project location or pass --brand-kb-file."
        ),
    }


def _merged_brand_context(client: DagenoClient, brand_kb_file: str | None = None) -> Dict[str, Any]:
    local_kb = _load_brand_kb(brand_kb_file)
    if local_kb:
        return local_kb

    try:
        return client.brand_info().get("data", {})
    except Exception:
        return {}


def _brand_context_summary(brand_context: Dict[str, Any]) -> Dict[str, Any]:
    if not brand_context:
        return {}
    return {
        "brand_name": brand_context.get("brand_name") or brand_context.get("name") or "",
        "category": brand_context.get("category") or "",
        "one_liner": brand_context.get("one_liner") or brand_context.get("tagline") or "",
        "differentiators": (brand_context.get("differentiators") or [])[:5],
        "preferred_cta": brand_context.get("preferred_cta") or "",
    }


def _brand_context_compact_lines(brand_context: Dict[str, Any]) -> List[str]:
    if not brand_context:
        return []
    lines: List[str] = []
    name = brand_context.get("brand_name") or brand_context.get("name")
    if name:
        lines.append(f"- Brand: `{name}`")
    one_liner = brand_context.get("one_liner") or brand_context.get("tagline")
    if one_liner:
        lines.append(f"- Positioning: {one_liner}")
    differentiators = brand_context.get("differentiators") or []
    if differentiators:
        lines.append(f"- Key differentiators: {', '.join(differentiators[:3])}")
    prohibited_claims = brand_context.get("prohibited_claims") or []
    if prohibited_claims:
        lines.append(f"- Avoid claims: {', '.join(prohibited_claims[:3])}")
    return lines


def _priority_rank(priority: str) -> int:
    return {"high": 0, "medium": 1, "low": 2}.get((priority or "").lower(), 9)


def _pick_asset_row(rows: List[Dict[str, Any]], asset_id: str | None = None) -> Dict[str, Any]:
    if asset_id:
        for row in rows:
            if row.get("asset_id") == asset_id:
                return row
    ordered = sorted(rows, key=lambda row: (_priority_rank(row.get("priority", "")), row.get("asset_id", "")))
    return ordered[0] if ordered else {}


def _top_citation_lines(citations: List[Dict[str, Any]], limit: int = 3) -> List[str]:
    lines: List[str] = []
    for item in _top(citations, "citationCount", limit):
        lines.append(
            "- {domain} | {page_type} | citations `{count}`".format(
                domain=item.get("domain", "-"),
                page_type=item.get("pageType", "-"),
                count=_fmt_number(item.get("citationCount")),
            )
        )
    return lines


def _faq_items(asset: Dict[str, Any], topic: str, prompt_text: str) -> List[Tuple[str, str]]:
    category = topic or "the category"
    title = asset.get("asset_title", "this topic")
    return [
        (
            f"What is {category}?",
            f"{category} is the set of tools, workflows, and measurement practices teams use to improve how their brand appears in AI-generated answers.",
        ),
        (
            f"Why does {title.lower()} matter?",
            "It helps teams move from vague AI visibility concerns to a concrete framework they can evaluate, implement, and improve over time.",
        ),
        (
            f"How should teams evaluate {category} vendors or approaches?",
            "Start with answer coverage, citation quality, tracking depth, workflow fit, and whether the platform can connect visibility insights to content and conversion actions.",
        ),
    ]


def _draft_body_paragraphs(asset: Dict[str, Any], selected: Dict[str, Any], context: Dict[str, Any]) -> List[str]:
    topic = selected.get("topic", "the category")
    prompt_text = selected.get("prompt", "the prompt")
    mention_counter: Counter[str] = context.get("mention_counter", Counter())
    recurring_entities = ", ".join(name for name, _ in mention_counter.most_common(5)) or "third-party vendors"
    page_type = context.get("dominant_page_type", "Article")

    intro = (
        f"{topic} matters because AI systems are already answering prompts like \"{prompt_text}\" even when the brand is missing. "
        f"That creates a real content opportunity: if teams publish a clearer category definition, evaluation framework, and proof-oriented page structure, they have a better chance of being included in future AI answers."
    )
    problem = (
        f"Right now the answer landscape is shaped mostly by {page_type.lower()}-style sources and recurring entities such as {recurring_entities}. "
        "That means buyers are learning the market from third-party framing before they ever see the brand's own explanation."
    )
    action = (
        f"The first asset should therefore explain {topic} directly, define what a strong solution looks like, and give readers a simple way to compare approaches. "
        "This makes the page useful for human readers and easier for AI systems to extract into standalone answer blocks."
    )
    return [intro, problem, action]


def _brand_context_lines(brand_context: Dict[str, Any]) -> List[str]:
    if not brand_context:
        return []
    lines: List[str] = []
    name = brand_context.get("brand_name") or brand_context.get("name")
    if name:
        lines.append(f"- Brand name: `{name}`")
    category = brand_context.get("category")
    if category:
        lines.append(f"- Category: `{category}`")
    one_liner = brand_context.get("one_liner") or brand_context.get("tagline")
    if one_liner:
        lines.append(f"- One-line positioning: {one_liner}")
    differentiators = brand_context.get("differentiators") or []
    if differentiators:
        lines.append(f"- Differentiators: {', '.join(differentiators[:5])}")
    proof_points = brand_context.get("proof_points") or []
    if proof_points:
        lines.append(f"- Proof points: {', '.join(proof_points[:5])}")
    preferred_cta = brand_context.get("preferred_cta")
    if preferred_cta:
        lines.append(f"- Preferred CTA: {preferred_cta}")
    prohibited_claims = brand_context.get("prohibited_claims") or []
    if prohibited_claims:
        lines.append(f"- Avoid saying: {', '.join(prohibited_claims[:5])}")
    return lines


def first_asset_draft(
    client: DagenoClient,
    days: int = 30,
    *,
    prompt_id: str | None = None,
    prompt_text: str | None = None,
    asset_id: str | None = None,
    brand_kb_file: str | None = None,
) -> str:
    context = _build_content_pack_context(
        client,
        days,
        prompt_id=prompt_id,
        prompt_text=prompt_text,
        brand_kb_file=brand_kb_file,
        detail_limit=1,
    )
    if context["empty"]:
        return "# First Asset Draft\n\nNo content opportunities were returned for the selected window."

    selected = context["selected_opportunity"]
    asset = _pick_asset_row(context["asset_rows"], asset_id=asset_id)
    if not asset:
        return "# First Asset Draft\n\nNo asset row was available for drafting."
    brand_context = context.get("brand_context", {})
    context["brand_context"] = brand_context
    brand_kb = context.get("brand_kb", {})

    topic = selected.get("topic", "-")
    prompt_text_value = selected.get("prompt", "-")
    top_detail = context.get("response_details", [{}])[0] if context.get("response_details") else {}
    angles = _content_angles(selected, top_detail, context.get("citations", []))
    faq_items = _faq_items(asset, topic, prompt_text_value)
    citation_lines = _top_citation_lines(context.get("citations", []))

    lines = [
        f"# First Asset Draft: {asset.get('asset_title', '-')}",
        "",
        "## Why This Draft Exists",
        "",
        f"- Business goal: start publishing against the prompt `{prompt_text_value}` instead of leaving the answer space to third-party sources.",
        f"- Chosen asset: `{asset.get('asset_id', '-')}` because it is the highest-priority row that can define the category clearly.",
        f"- Publish target: `{asset.get('recommended_publish_surface', '-')}` -> `{asset.get('target_site_section', '-')}`",
        "",
        "## Draft Brief",
        "",
        f"- Working title: {asset.get('asset_title', '-')}",
        f"- Search intent: `{asset.get('target_intent', '-')}`",
        f"- Primary angle: {asset.get('primary_angle', '-')}",
        f"- Why now: {asset.get('why_exists', '-')}",
        f"- Required blocks: {', '.join(asset.get('required_content_blocks', [])) or '-'}",
        f"- CTA goal: `{asset.get('cta_goal', '-')}`",
        "",
        "## Brand Knowledge Base",
        "",
        f"- Path: `{brand_kb.get('path', '-')}`",
        f"- Loaded: `{brand_kb.get('loaded', False)}`",
        f"- Reminder: {brand_kb.get('message', '-')}",
        "",
    ]
    brand_lines = _brand_context_compact_lines(brand_context)
    if brand_lines:
        lines.extend(
            [
                "## Brand Context To Keep Consistent",
                "",
            ]
        )
        lines.extend(brand_lines)
        lines.extend([""])

    lines.extend(
        [
            "## Evidence To Respect",
            "",
            f"- Source prompt: `{prompt_text_value}`",
            f"- Topic: `{topic}`",
            f"- Opportunity tier: `{asset.get('opportunity_tier', '-')}`",
            f"- Brand gap: `{_fmt_gap(selected.get('brandGap'))}`",
            f"- Source gap: `{_fmt_gap(selected.get('sourceGap'))}`",
            f"- Dominant page type in citations: `{context.get('dominant_page_type', '-')}`",
        ]
    )
    if citation_lines:
        lines.extend(["- Top citation patterns:"])
        lines.extend(citation_lines)
    if top_detail:
        lines.extend(
            [
                f"- Response preview: {_response_preview(top_detail.get('contentMd', '')) or '-'}",
            ]
        )

    lines.extend(["", "## Suggested Outline", ""])
    lines.append(f"- H1: {asset.get('asset_title', '-')}")
    for angle in angles:
        lines.append(f"- H2 angle: {angle}")
    lines.extend(
        [
            f"- H2 angle: What teams should look for in a strong {topic} solution",
            f"- H2 angle: Common mistakes teams make when approaching {topic}",
            "- H2 angle: FAQ",
            "",
            "## Draft",
            "",
            asset.get("asset_title", "-"),
            "",
        ]
    )
    for paragraph in _draft_body_paragraphs(asset, selected, context):
        lines.extend([paragraph, ""])

    lines.extend(
        [
            f"## What Is {topic}?",
            "",
            f"{topic} is not only about monitoring mentions in AI systems. A strong {topic} workflow helps teams understand which prompts matter commercially, which third-party sources shape the answers, and what content assets should be published so the brand becomes easier to cite and recommend.",
            "",
            f"## What Teams Should Look For in a Strong {topic} Solution",
            "",
            "Teams should look for prompt-level visibility data, source and citation analysis, answer tracking across major AI platforms, and a practical path from insight to execution. In other words, the best solution does not stop at reporting. It should help the team decide what to publish next and why that asset matters.",
            "",
            f"## Common Mistakes Teams Make When Approaching {topic}",
            "",
            "A common mistake is treating AI visibility like a generic SEO dashboard problem. Another is publishing only one broad article without building a sequence of supporting assets. The better approach is to define the category clearly, create evaluation-oriented content, and then add a commercial page that captures buyer intent once the narrative foundation is in place.",
            "",
            "## FAQ",
            "",
        ]
    )
    for question, answer in faq_items:
        lines.extend([f"### {question}", "", answer, ""])

    lines.extend(
        [
            "## CTA Direction",
            "",
            "Close with a next step that matches the article type and user intent. For traffic-oriented articles, prefer a soft CTA such as related reading, newsletter signup, or product evaluation framework. Use direct demo language only when the article is clearly commercial or transactional.",
        ]
    )
    return "\n".join(lines)


def _build_content_pack_context(
    client: DagenoClient,
    days: int,
    *,
    prompt_id: str | None = None,
    prompt_text: str | None = None,
    brand_kb_file: str | None = None,
    detail_limit: int = 1,
) -> Dict[str, Any]:
    brand_context = _merged_brand_context(client, brand_kb_file=brand_kb_file)
    brand_kb = _brand_kb_status(brand_kb_file)
    start_at, end_at = date_window(days)
    opportunities = _collect_all(
        lambda **kwargs: client.content_opportunities(start_at, end_at, **kwargs),
        page_size=100,
    )
    if not opportunities:
        return {
            "empty": True,
            "selected_opportunity": {},
            "selected_prompt_id": None,
            "tier_buckets": {"High": [], "Medium": [], "Low": []},
            "responses": [],
            "citations": [],
            "mention_counter": Counter(),
            "dominant_page_type": "Unknown",
            "fanout_prompts": [],
            "keyword_cluster": [],
            "keyword_volume_rows": [],
            "primary_intent": "-",
            "tier": "-",
            "asset_rows": [],
            "response_details": [],
            "brand_context": brand_context,
            "brand_kb": brand_kb,
        }

    tier_buckets: Dict[str, List[Dict[str, Any]]] = {"High": [], "Medium": [], "Low": []}
    for item in opportunities:
        tier_buckets[_opportunity_tier(item)].append(item)
    for tier in tier_buckets:
        tier_buckets[tier] = sorted(tier_buckets[tier], key=_opportunity_score, reverse=True)

    prompts = _collect_all(
        lambda **kwargs: client.prompts(start_at, end_at, **kwargs),
        page_size=100,
    )
    selected_prompt = _find_prompt_match(prompts, prompt_id=prompt_id, prompt_text=prompt_text)

    selected_opportunity: Dict[str, Any] = {}
    if selected_prompt:
        normalized = _normalize_text(selected_prompt.get("prompt", ""))
        selected_opportunity = next(
            (item for item in opportunities if _normalize_text(item.get("prompt", "")) == normalized),
            {},
        )
    elif prompt_text:
        normalized = _normalize_text(prompt_text)
        selected_opportunity = next(
            (item for item in opportunities if _normalize_text(item.get("prompt", "")) == normalized),
            {},
        )

    if not selected_opportunity:
        selected_opportunity = (
            tier_buckets["High"][0] if tier_buckets["High"] else _pick_best_content_opportunity(opportunities)
        )
    if not selected_prompt:
        selected_prompt = _find_prompt_match(prompts, prompt_text=selected_opportunity.get("prompt"))

    selected_prompt_id = selected_prompt.get("id") if selected_prompt else None
    responses: List[Dict[str, Any]] = []
    response_details: List[Dict[str, Any]] = []
    citations: List[Dict[str, Any]] = []
    mention_counter: Counter[str] = Counter()

    if selected_prompt_id:
        responses = _collect_all(
            lambda **kwargs: client.prompt_responses(selected_prompt_id, start_at, end_at, **kwargs),
            page_size=100,
        )
        responses = sorted(responses, key=lambda item: item.get("createdAt") or item.get("date") or "", reverse=True)
        for response in responses[: min(detail_limit, len(responses))]:
            if response.get("id"):
                detail = client.prompt_response_detail(selected_prompt_id, response["id"]).get("data", {})
                response_details.append(detail)
                for mention in detail.get("mentions") or []:
                    brand = mention.get("brandName")
                    if brand:
                        mention_counter[brand] += 1
        citations = _collect_all(
            lambda **kwargs: client.prompt_citation_urls(selected_prompt_id, start_at, end_at, **kwargs),
            page_size=100,
        )

    primary_intent = _primary_intention((selected_prompt or {}).get("intentions") or [])
    tier = _opportunity_tier(selected_opportunity)
    dominant_page_type = _page_type_family(citations)
    guessed_fanout = _fanout_prompt_guesses(
        selected_opportunity.get("prompt", ""),
        selected_opportunity.get("topic", ""),
        primary_intent,
    )
    api_fanout: List[str] = []
    if selected_prompt_id:
        try:
            fanout_items = _collect_all(
                lambda **kwargs: client.prompt_query_fanout(selected_prompt_id, start_at, end_at, **kwargs),
                page_size=100,
            )
            api_fanout = [item.get("name", "").strip() for item in fanout_items if item.get("name")]
        except Exception:
            api_fanout = []
    fanout_prompts = _dedupe_keep_order(api_fanout + guessed_fanout)

    keyword_cluster = _dedupe_keep_order(
        _keyword_cluster_guesses(selected_opportunity.get("prompt", ""), selected_opportunity.get("topic", ""))
        + fanout_prompts[:5]
    )
    keyword_volume_rows: List[Dict[str, Any]] = []
    if keyword_cluster:
        try:
            keyword_volume_rows = client.keyword_volume(keyword_cluster[:10]).get("data", [])
        except Exception:
            keyword_volume_rows = []
    asset_rows = _asset_rows(
        prompt_text=selected_opportunity.get("prompt", ""),
        opportunity_tier=tier,
        topic=selected_opportunity.get("topic", ""),
        primary_intent=primary_intent,
        dominant_page_type=dominant_page_type,
        brand_context=brand_context,
    )

    return {
        "empty": False,
        "selected_opportunity": selected_opportunity,
        "selected_prompt": selected_prompt or {},
        "selected_prompt_id": selected_prompt_id,
        "tier_buckets": tier_buckets,
        "responses": responses,
        "response_details": response_details,
        "citations": citations,
        "mention_counter": mention_counter,
        "dominant_page_type": dominant_page_type,
        "fanout_prompts": fanout_prompts,
        "keyword_cluster": keyword_cluster,
        "keyword_volume_rows": keyword_volume_rows,
        "primary_intent": primary_intent,
        "tier": tier,
        "asset_rows": asset_rows,
        "brand_context": brand_context,
        "brand_kb": brand_kb,
    }


def brand_snapshot(client: DagenoClient) -> str:
    payload = client.brand_info()["data"]
    socials = ", ".join(social["url"] for social in payload.get("socials", [])[:3]) or "-"
    return "\n".join(
        [
            "# Brand Snapshot",
            "",
            f"- Brand: `{payload.get('name', '-')}`",
            f"- Domain: `{payload.get('domain', '-')}`",
            f"- Website: `{payload.get('website', '-')}`",
            f"- Tagline: `{payload.get('tagline', '-')}`",
            f"- Socials: {socials}",
            "",
            "## Summary",
            "",
            payload.get("description", "-"),
        ]
    )


def topic_watchlist(client: DagenoClient, days: int = 30, limit: int = 5) -> str:
    start_at, end_at = date_window(days)
    items = client.topics(start_at, end_at, page_size=max(limit, 10))["data"]["items"]
    rows = _top(items, "visibility", limit)
    lines = [
        f"# Topic Watchlist ({days} days)",
        "",
        "| Topic | Visibility | Sentiment | Avg Position | Citation Rate | Volume |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for item in rows:
        lines.append(
            "| {topic} | {visibility} | {sentiment} | {avg_position} | {citation_rate} | {volume} |".format(
                topic=item.get("topic", "-"),
                visibility=_fmt_number(item.get("visibility")),
                sentiment=_fmt_number(item.get("sentiment")),
                avg_position=_fmt_number(item.get("avgPosition")),
                citation_rate=_fmt_number(item.get("citationRate")),
                volume=_fmt_number(item.get("volume")),
            )
        )
    return "\n".join(lines)


def prompt_gap_report(client: DagenoClient, days: int = 30, limit: int = 5) -> str:
    start_at, end_at = date_window(days)
    items = client.prompts(start_at, end_at, page_size=max(limit * 3, 15))["data"]["items"]
    ranked = sorted(
        items,
        key=lambda item: ((item.get("volume") or 0), (item.get("visibility") or 0), -1 * (item.get("citationRate") or 0)),
        reverse=True,
    )[:limit]
    lines = [
        f"# Prompt Gap Report ({days} days)",
        "",
        "| Prompt | Topic | Funnel | Visibility | Citation Rate | Volume |",
        "|---|---|---|---:|---:|---:|",
    ]
    for item in ranked:
        lines.append(
            "| {prompt} | {topic} | {funnel} | {visibility} | {citation_rate} | {volume} |".format(
                prompt=item.get("prompt", "-"),
                topic=item.get("topic", "-"),
                funnel=item.get("funnel", "-"),
                visibility=_fmt_number(item.get("visibility")),
                citation_rate=_fmt_number(item.get("citationRate")),
                volume=_fmt_number(item.get("volume")),
            )
        )
    return "\n".join(lines)


def citation_source_brief(client: DagenoClient, days: int = 30, limit: int = 5) -> str:
    start_at, end_at = date_window(days)
    domains = client.citation_domains(start_at, end_at, page_size=max(limit, 10))["data"]["items"]
    urls = client.citation_urls(start_at, end_at, page_size=max(limit, 10))["data"]["items"]

    lines = [
        f"# Citation Source Brief ({days} days)",
        "",
        "## Top Domains",
        "",
        "| Domain | Type | Citation Count | Citation Rate |",
        "|---|---|---:|---:|",
    ]
    for item in _top(domains, "citationCount", limit):
        lines.append(
            "| {domain} | {domain_type} | {citation_count} | {citation_rate} |".format(
                domain=item.get("domain", "-"),
                domain_type=item.get("domainType", "-"),
                citation_count=_fmt_number(item.get("citationCount")),
                citation_rate=_fmt_number(item.get("citationRate")),
            )
        )

    lines.extend(
        [
            "",
            "## Top URLs",
            "",
            "| URL | Domain | Citation Count | Page Type |",
            "|---|---|---:|---|",
        ]
    )
    for item in _top(urls, "citationCount", limit):
        lines.append(
            "| {url} | {domain} | {citation_count} | {page_type} |".format(
                url=item.get("url", "-"),
                domain=item.get("domain", "-"),
                citation_count=_fmt_number(item.get("citationCount")),
                page_type=item.get("pageType", "-"),
            )
        )
    return "\n".join(lines)


def content_opportunity_brief(client: DagenoClient, days: int = 30, limit: int = 5) -> str:
    start_at, end_at = date_window(days)
    items = client.content_opportunities(start_at, end_at, page_size=max(limit, 10))["data"]["items"]
    ranked = _top(items, "totalResponseCount", limit)
    lines = [
        f"# Content Opportunity Brief ({days} days)",
        "",
        "| Prompt | Topic | Brand Gap | Source Gap | Responses | Sources | Platforms |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for item in ranked:
        platforms = ", ".join(item.get("platforms", [])[:4])
        lines.append(
            "| {prompt} | {topic} | {brand_gap} | {source_gap} | {responses} | {sources} | {platforms} |".format(
                prompt=item.get("prompt", "-"),
                topic=item.get("topic", "-"),
                brand_gap=_fmt_number(item.get("brandGap")),
                source_gap=_fmt_number(item.get("sourceGap")),
                responses=_fmt_number(item.get("totalResponseCount")),
                sources=_fmt_number(item.get("totalSourceCount")),
                platforms=platforms or "-",
            )
        )
    return "\n".join(lines)


def backlink_opportunity_brief(client: DagenoClient, days: int = 30, limit: int = 5) -> str:
    start_at, end_at = date_window(days)
    items = client.backlink_opportunities(start_at, end_at, page_size=max(limit, 10))["data"]["items"]
    ranked = _top(items, "priority", limit)
    lines = [
        f"# Backlink Opportunity Brief ({days} days)",
        "",
        "| Domain | Type | Priority | Prompt Count | Chat Count |",
        "|---|---|---:|---:|---:|",
    ]
    for item in ranked:
        lines.append(
            "| {domain} | {domain_type} | {priority} | {prompt_count} | {chat_count} |".format(
                domain=item.get("domain", "-"),
                domain_type=item.get("domainType", "-"),
                priority=_fmt_number(item.get("priority")),
                prompt_count=_fmt_number(item.get("promptCount")),
                chat_count=_fmt_number(item.get("chatCount")),
            )
        )
    return "\n".join(lines)


def community_opportunity_brief(client: DagenoClient, days: int = 30, limit: int = 5) -> str:
    start_at, end_at = date_window(days)
    items = client.community_opportunities(start_at, end_at, page_size=max(limit, 10))["data"]["items"]
    ranked = _top(items, "priority", limit)
    lines = [
        f"# Community Opportunity Brief ({days} days)",
        "",
        "| Prompt | Domain | Type | Citations | Priority | Platforms |",
        "|---|---|---|---:|---:|---|",
    ]
    for item in ranked:
        lines.append(
            "| {prompt} | {domain} | {domain_type} | {citations} | {priority} | {platforms} |".format(
                prompt=item.get("prompt", "-"),
                domain=item.get("domain", "-"),
                domain_type=item.get("domainType", "-"),
                citations=_fmt_number(item.get("citations")),
                priority=_fmt_number(item.get("priority")),
                platforms=", ".join(item.get("platforms", [])[:4]) or "-",
            )
        )
    return "\n".join(lines)


def prompt_deep_dive(client: DagenoClient, prompt_id: str, days: int = 30, limit: int = 5) -> str:
    start_at, end_at = date_window(days)
    responses = client.prompt_responses(prompt_id, start_at, end_at, page_size=max(limit, 5))["data"]["items"]
    domains = client.prompt_citation_domains(prompt_id, start_at, end_at, page_size=max(limit, 5))["data"]["items"]
    urls = client.prompt_citation_urls(prompt_id, start_at, end_at, page_size=max(limit, 5))["data"]["items"]

    lines = [
        f"# Prompt Deep Dive: `{prompt_id}`",
        "",
        "## Recent Responses",
        "",
    ]
    for item in responses[:limit]:
        content = (item.get("contentMd") or "").strip().replace("\n", " ")
        lines.extend(
            [
                f"- Platform: `{item.get('platform', '-')}`",
                f"  Date: `{item.get('date', '-')}`",
                f"  Preview: {content[:220] or '-'}",
            ]
        )

    lines.extend(
        [
            "",
            "## Top Citation Domains",
            "",
            "| Domain | Citation Count | Citation Rate |",
            "|---|---:|---:|",
        ]
    )
    for item in _top(domains, "citationCount", limit):
        lines.append(
            "| {domain} | {citation_count} | {citation_rate} |".format(
                domain=item.get("domain", "-"),
                citation_count=_fmt_number(item.get("citationCount")),
                citation_rate=_fmt_number(item.get("citationRate")),
            )
        )

    lines.extend(
        [
            "",
            "## Top Citation URLs",
            "",
            "| URL | Domain | Citation Count |",
            "|---|---|---:|",
        ]
    )
    for item in _top(urls, "citationCount", limit):
        lines.append(
            "| {url} | {domain} | {citation_count} |".format(
                url=item.get("url", "-"),
                domain=item.get("domain", "-"),
                citation_count=_fmt_number(item.get("citationCount")),
            )
        )
    return "\n".join(lines)


def weekly_exec_brief(client: DagenoClient, days: int = 30, limit: int = 5) -> str:
    sections = [
        brand_snapshot(client),
        topic_watchlist(client, days=days, limit=limit),
        prompt_gap_report(client, days=days, limit=limit),
        citation_source_brief(client, days=days, limit=limit),
        content_opportunity_brief(client, days=days, limit=limit),
        backlink_opportunity_brief(client, days=days, limit=limit),
        community_opportunity_brief(client, days=days, limit=limit),
    ]
    return "\n\n".join(sections)


def new_content_brief(
    client: DagenoClient,
    days: int = 30,
    limit: int = 5,
    *,
    prompt_id: str | None = None,
    prompt_text: str | None = None,
) -> str:
    start_at, end_at = date_window(days)
    prompt_items = client.prompts(start_at, end_at, page_size=200)["data"]["items"]

    selected_prompt = _find_prompt_match(prompt_items, prompt_id=prompt_id, prompt_text=prompt_text)
    selected_prompt_id = selected_prompt.get("id") if selected_prompt else prompt_id

    if selected_prompt_id:
        opportunity_items = client.content_opportunities(
            start_at,
            end_at,
            page_size=max(limit * 5, 20),
            prompt_id=selected_prompt_id,
        )["data"]["items"]
        if not opportunity_items and selected_prompt.get("prompt"):
            all_items = client.content_opportunities(start_at, end_at, page_size=100)["data"]["items"]
            normalized = _normalize_text(selected_prompt.get("prompt", ""))
            opportunity_items = [
                item for item in all_items if _normalize_text(item.get("prompt", "")) == normalized
            ]
    else:
        opportunity_items = client.content_opportunities(start_at, end_at, page_size=100)["data"]["items"]

    if prompt_text and not selected_prompt:
        selected_prompt = _find_prompt_match(prompt_items, prompt_text=prompt_text)

    if not opportunity_items:
        return "# New Content Brief\n\nNo content opportunities were returned for the selected window."

    selected = _pick_best_content_opportunity(opportunity_items)
    if not selected_prompt:
        selected_prompt = _find_prompt_match(prompt_items, prompt_text=selected.get("prompt"))
        selected_prompt_id = selected_prompt.get("id") if selected_prompt else None

    responses: List[Dict[str, Any]] = []
    detail: Dict[str, Any] = {}
    citation_urls: List[Dict[str, Any]] = []
    if selected_prompt_id:
        responses = client.prompt_responses(selected_prompt_id, start_at, end_at, page_size=10)["data"]["items"]
        responses = sorted(responses, key=lambda item: item.get("createdAt") or item.get("date") or "", reverse=True)
        if responses and responses[0].get("id"):
            detail = client.prompt_response_detail(selected_prompt_id, responses[0]["id"]).get("data", {})
        citation_urls = client.prompt_citation_urls(selected_prompt_id, start_at, end_at, page_size=10)["data"]["items"]

    prompt_volume = (selected_prompt or {}).get("volume")
    intentions = (selected_prompt or {}).get("intentions") or []
    asset_type = _choose_asset_type(
        prompt_volume=prompt_volume,
        brand_gap=selected.get("brandGap"),
        source_gap=selected.get("sourceGap"),
        response_count=selected.get("totalResponseCount"),
    )

    lines = [
        f"# New Content Brief ({days} days)",
        "",
        "## Selected Opportunity",
        "",
        f"- Prompt: `{selected.get('prompt', '-')}`",
        f"- Topic: `{selected.get('topic', '-')}`",
        f"- Prompt ID: `{selected_prompt_id or '-'}`",
        f"- Brand Gap: `{_fmt_gap(selected.get('brandGap'))}`",
        f"- Source Gap: `{_fmt_gap(selected.get('sourceGap'))}`",
        f"- Responses: `{_fmt_number(selected.get('totalResponseCount'))}`",
        f"- Sources: `{_fmt_number(selected.get('totalSourceCount'))}`",
        f"- Platforms: {', '.join(selected.get('platforms', [])[:6]) or '-'}",
        "",
        "## Demand Summary",
        "",
        f"- Observed Prompt Volume: `{_fmt_number(prompt_volume)}`",
        f"- Intentions: {_format_intentions(intentions)}",
        "",
        "## Response Gap Summary",
        "",
    ]

    if detail:
        lines.extend(
            [
                f"- Platform: `{detail.get('platform', responses[0].get('platform') if responses else '-')}`",
                f"- Region: `{detail.get('region', responses[0].get('region') if responses else '-')}`",
                f"- Date: `{detail.get('date', responses[0].get('date') if responses else '-')}`",
                f"- Preview: {_response_preview(detail.get('contentMd', '')) or '-'}",
            ]
        )
        mention_lines = _summarize_mentions(detail)
        if mention_lines:
            lines.extend(["", "### Mentioned Brands", ""])
            lines.extend(mention_lines)
        if detail.get("sources"):
            lines.extend(["", f"- Sources in response detail: {', '.join(detail.get('sources', [])[:6])}"])
    else:
        lines.append("- Response detail unavailable. Check whether the selected prompt maps to a prompt ID in this date window.")

    lines.extend(["", "## Citation Summary", ""])
    if citation_urls:
        for item in _top(citation_urls, "citationCount", limit):
            lines.append(
                "- {url} ({domain}; citations {count}; page type {page_type})".format(
                    url=item.get("url", "-"),
                    domain=item.get("domain", "-"),
                    count=_fmt_number(item.get("citationCount")),
                    page_type=item.get("pageType", "-"),
                )
            )
    else:
        lines.append("- No prompt-level citation URLs returned for this window.")

    lines.extend(
        [
            "",
            "## Recommended New Asset",
            "",
            f"- Asset Type: `{asset_type}`",
            "- Reasoning:",
            f"  High-level gap signal comes from brand gap `{_fmt_gap(selected.get('brandGap'))}` and source gap `{_fmt_gap(selected.get('sourceGap'))}`.",
            f"  Demand signal comes from observed prompt volume `{_fmt_number(prompt_volume)}` and response count `{_fmt_number(selected.get('totalResponseCount'))}`.",
            "",
            "## Drafting Angles",
            "",
        ]
    )
    for angle in _content_angles(selected, detail, citation_urls):
        lines.append(f"- {angle}")

    lines.extend(
        [
            "",
            "## Suggested Blueprint",
            "",
            f"- Working Title: {selected.get('prompt', '-')}",
            f"- H1: {selected.get('prompt', '-')}",
            "- H2 ideas:",
            f"  What the topic means for `{selected.get('topic', '-')}`",
            "  Why current AI answers miss key brand-specific context",
            "  How teams should evaluate solutions or approaches",
            "  Implementation, evidence, or examples",
            "  FAQ",
        ]
    )

    return "\n".join(lines)


def content_pack(
    client: DagenoClient,
    days: int = 30,
    limit: int = 5,
    *,
    prompt_id: str | None = None,
    prompt_text: str | None = None,
    brand_kb_file: str | None = None,
    compact: bool = False,
) -> str:
    context = _build_content_pack_context(
        client,
        days,
        prompt_id=prompt_id,
        prompt_text=prompt_text,
        brand_kb_file=brand_kb_file,
        detail_limit=1,
    )
    if context["empty"]:
        return "# Content Pack\n\nNo content opportunities were returned for the selected window."

    tier_buckets = context["tier_buckets"]
    selected_opportunity = context["selected_opportunity"]
    selected_prompt = context["selected_prompt"]
    selected_prompt_id = context["selected_prompt_id"]
    responses = context["responses"]
    citations = context["citations"]
    mention_counter = context["mention_counter"]
    dominant_page_type = context["dominant_page_type"]
    fanout_prompts = context["fanout_prompts"]
    keyword_cluster = context["keyword_cluster"]
    keyword_volume_rows = context["keyword_volume_rows"]
    primary_intent = context["primary_intent"]
    tier = context["tier"]
    asset_rows = context["asset_rows"]
    brand_context = context["brand_context"]
    brand_kb = context["brand_kb"]

    lines = [
        f"# Content Pack ({days} days)",
        "",
    ]
    if not compact:
        lines.extend(
            [
                "## Opportunity Tiers",
                "",
                f"- High Opportunity: `{len(tier_buckets['High'])}`",
                f"- Medium Opportunity: `{len(tier_buckets['Medium'])}`",
                f"- Low Opportunity: `{len(tier_buckets['Low'])}`",
                "",
                "### High Opportunity Preview",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "## Opportunity Snapshot",
                "",
                f"- High: `{len(tier_buckets['High'])}` | Medium: `{len(tier_buckets['Medium'])}` | Low: `{len(tier_buckets['Low'])}`",
                "",
            ]
        )
    for item in tier_buckets["High"][: max(limit, 5)] if not compact else tier_buckets["High"][: min(limit, 3)]:
        lines.append(
            "- `{prompt}` | topic `{topic}` | brand gap `{brand_gap}` | source gap `{source_gap}` | responses `{responses}`".format(
                prompt=item.get("prompt", "-"),
                topic=item.get("topic", "-"),
                brand_gap=_fmt_gap(item.get("brandGap")),
                source_gap=_fmt_gap(item.get("sourceGap")),
                responses=_fmt_number(item.get("totalResponseCount")),
            )
        )

    lines.extend(
        [
            "",
            "## Selected Prompt",
            "",
            f"- Prompt: `{selected_opportunity.get('prompt', '-')}`",
            f"- Prompt ID: `{selected_prompt_id or '-'}`",
            f"- Tier: `{tier}`",
            f"- Topic: `{selected_opportunity.get('topic', '-')}`",
            f"- Brand Gap: `{_fmt_gap(selected_opportunity.get('brandGap'))}`",
            f"- Source Gap: `{_fmt_gap(selected_opportunity.get('sourceGap'))}`",
            f"- Responses: `{_fmt_number(selected_opportunity.get('totalResponseCount'))}`",
            f"- Prompt Volume: `{_fmt_number((selected_prompt or {}).get('volume'))}`",
            f"- Intentions: {_format_intentions((selected_prompt or {}).get('intentions') or [])}",
            f"- Funnel: `{(selected_prompt or {}).get('funnel', '-')}`",
            "",
            "## Brand Knowledge Base",
            "",
            f"- Path: `{brand_kb.get('path', '-')}`",
            f"- Loaded: `{brand_kb.get('loaded', False)}`",
            f"- Reminder: {brand_kb.get('message', '-')}",
            "",
        ]
    )
    brand_lines = _brand_context_compact_lines(brand_context)
    if brand_lines:
        lines.extend(["## Brand Context To Keep Consistent", ""])
        lines.extend(brand_lines)
        lines.extend([""])

    lines.extend(["## Evidence Layer", ""])
    lines.extend(
        [
            f"- Response Count: `{len(responses)}`",
            f"- Mentioned Brand Count: `{sum(1 for item in responses if item.get('mentioned'))}`",
            f"- Unmentioned Brand Count: `{sum(1 for item in responses if not item.get('mentioned'))}`",
            f"- Citation URL Count: `{len(citations)}`",
            f"- Dominant Page Type: `{dominant_page_type}`",
        ]
    )
    if not compact:
        lines.append(f"- Recurring Entities In Sample: {', '.join(name for name, _ in mention_counter.most_common(8)) or '-'}")
    else:
        lines.append(f"- Top Entities: {', '.join(name for name, _ in mention_counter.most_common(4)) or '-'}")
    lines.extend(["", "## Fanout Layer", ""])
    for prompt in fanout_prompts[:8]:
        lines.append(f"- {prompt}")
    if len(fanout_prompts) > 8:
        lines.append(f"- ... plus `{len(fanout_prompts) - 8}` more fanout prompts")

    lines.extend(["", "## SEO Layer", ""])
    lines.append(f"- Primary Keyword Candidate: `{keyword_cluster[0] if keyword_cluster else '-'}`")
    lines.append(f"- Keyword Cluster: {', '.join(keyword_cluster[:8]) or '-'}")
    if len(keyword_cluster) > 8:
        lines.append(f"- Additional Keyword Variants: `{len(keyword_cluster) - 8}` more")
    if keyword_volume_rows:
        lines.append("- Search Volume:")
        for row in keyword_volume_rows[:10]:
            lines.append(
                "  - `{keyword}` | vol `{vol}` | competition `{competition}` | cpc `{currency}{value}`".format(
                    keyword=row.get("keyword", "-"),
                    vol=_fmt_number(row.get("vol")),
                    competition=_fmt_number(row.get("competition")),
                    currency=(row.get("cpc") or {}).get("currency", ""),
                    value=(row.get("cpc") or {}).get("value", "-"),
                )
            )
    else:
        lines.append("- Search Volume + KD: pending connector")
    lines.append(f"- Primary Intention: `{primary_intent}`")

    lines.extend(["", "## Unified Asset + Publishing Target Table", ""])
    lines.extend(_render_asset_table(asset_rows))

    if not compact:
        lines.extend(
            [
                "",
                "## Creation Order",
                "",
                "- 1. Publish the category-defining article first.",
                "- 2. Publish the evaluation article second.",
                "- 3. Publish the roundup / landscape article third.",
                "- 4. Publish the measurement article next.",
                "- 5. Keep the landing page as a follow-up conversion asset.",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "## Creation Order",
                "",
                "- 1. A1",
                "- 2. A2",
                "- 3. A3",
                "- 4. A4",
                "- 5. A5",
            ]
        )
    return "\n".join(lines)


def content_pack_json(
    client: DagenoClient,
    days: int = 30,
    *,
    prompt_id: str | None = None,
    prompt_text: str | None = None,
    brand_kb_file: str | None = None,
) -> Dict[str, Any]:
    context = _build_content_pack_context(
        client,
        days,
        prompt_id=prompt_id,
        prompt_text=prompt_text,
        brand_kb_file=brand_kb_file,
        detail_limit=1,
    )
    if context["empty"]:
        return {
            "schema_version": "1.0.0",
            "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "time_window_days": days,
            "selected_prompt": "-",
            "brand_knowledge_base": context.get("brand_kb", {}),
            "assets": [],
        }

    asset_rows = []
    for row in context["asset_rows"]:
        normalized = dict(row)
        normalized["notes"] = normalized.get("notes") or ""
        asset_rows.append(normalized)

    return {
        "schema_version": "1.0.0",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "time_window_days": days,
        "selected_prompt": context["selected_opportunity"].get("prompt", "-") or "-",
        "brand_knowledge_base": {
            **context["brand_kb"],
            "brand_context_summary": _brand_context_summary(context.get("brand_context", {})),
        },
        "assets": asset_rows,
    }


def content_pack_compact_json(
    client: DagenoClient,
    days: int = 30,
    *,
    prompt_id: str | None = None,
    prompt_text: str | None = None,
    brand_kb_file: str | None = None,
) -> Dict[str, Any]:
    context = _build_content_pack_context(
        client,
        days,
        prompt_id=prompt_id,
        prompt_text=prompt_text,
        brand_kb_file=brand_kb_file,
        detail_limit=1,
    )
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    if context["empty"]:
        return {
            "schema_version": "1.0.0-compact",
            "generated_at": generated_at,
            "time_window_days": days,
            "selected_prompt": "-",
            "brand_knowledge_base": context.get("brand_kb", {}),
            "opportunity_summary": {"high": 0, "medium": 0, "low": 0},
            "evidence_summary": {},
            "seo_summary": {},
            "creation_order": [],
            "top_assets": [],
        }

    tier_buckets = context["tier_buckets"]
    selected = context["selected_opportunity"]
    compact_assets = []
    for row in context["asset_rows"][:5]:
        compact_assets.append(
            {
                "asset_id": row["asset_id"],
                "asset_title": row["asset_title"],
                "asset_type": row["asset_type"],
                "publish_surface": row["recommended_publish_surface"],
                "target_intent": row["target_intent"],
                "priority": row["priority"],
            }
        )

    return {
        "schema_version": "1.0.0-compact",
        "generated_at": generated_at,
        "time_window_days": days,
        "selected_prompt": selected.get("prompt", "-") or "-",
        "brand_knowledge_base": {
            "path": context["brand_kb"].get("path", ""),
            "loaded": context["brand_kb"].get("loaded", False),
            "brand_context_summary": _brand_context_summary(context.get("brand_context", {})),
        },
        "opportunity_summary": {
            "high": len(tier_buckets["High"]),
            "medium": len(tier_buckets["Medium"]),
            "low": len(tier_buckets["Low"]),
            "selected_tier": context["tier"],
            "brand_gap": _fmt_gap(selected.get("brandGap")),
            "source_gap": _fmt_gap(selected.get("sourceGap")),
        },
        "evidence_summary": {
            "response_count": len(context["responses"]),
            "citation_url_count": len(context["citations"]),
            "dominant_page_type": context["dominant_page_type"],
            "top_entities": [name for name, _ in context["mention_counter"].most_common(4)],
        },
        "seo_summary": {
            "primary_keyword_candidate": context["keyword_cluster"][0] if context["keyword_cluster"] else "-",
            "keyword_cluster_preview": context["keyword_cluster"][:6],
            "primary_intention": context["primary_intent"],
            "fanout_preview": context["fanout_prompts"][:6],
        },
        "creation_order": [row["asset_id"] for row in context["asset_rows"][:5]],
        "top_assets": compact_assets,
    }
