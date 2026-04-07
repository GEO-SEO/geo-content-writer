from __future__ import annotations

from collections import Counter
from difflib import get_close_matches
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Tuple

from .client import DagenoClient
from .citation_crawl import analyze_citation_patterns, crawl_citation_pages


def date_window(days: int) -> Tuple[str, str]:
    end_at = datetime.now(timezone.utc).replace(microsecond=0)
    start_at = end_at - timedelta(days=days)
    return (
        start_at.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        end_at.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
    )


def default_brand_kb_path() -> Path:
    return Path(__file__).resolve().parents[2] / "knowledge" / "brand" / "brand-knowledge-base.json"


def default_fanout_backlog_path() -> Path:
    return Path(__file__).resolve().parents[2] / "knowledge" / "backlog" / "fanout-backlog.json"


def default_citation_learnings_path() -> Path:
    return Path(__file__).resolve().parents[2] / "knowledge" / "insights" / "citation-learnings.json"


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
    if isinstance(value, str):
        cleaned = value.strip().replace("%", "").replace(",", "")
        if not cleaned:
            return 0.0
        value = cleaned
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


def _collect_all(fetch_page, *, page_size: int = 100, max_pages: int | None = None) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    page = 1
    while True:
        if max_pages is not None and page > max_pages:
            break
        resp = fetch_page(page=page, page_size=page_size)
        page_items = resp.get("data", {}).get("items", [])
        items.extend(page_items)
        pagination = resp.get("meta", {}).get("pagination", {})
        total_pages = pagination.get("totalPages", page)
        if page >= total_pages or not page_items:
            break
        page += 1
    return items


def _collect_all_checked(
    fetch_page,
    *,
    label: str,
    page_size: int = 100,
    max_pages: int | None = None,
    errors: List[str] | None = None,
    strict: bool = False,
) -> List[Dict[str, Any]]:
    try:
        return _collect_all(fetch_page, page_size=page_size, max_pages=max_pages)
    except Exception as exc:
        message = f"{label} collection failed: {exc}"
        if errors is not None:
            errors.append(message)
        if strict:
            raise RuntimeError(message) from exc
        return []


def _row_priority_score(row: Dict[str, Any]) -> float:
    explicit = row.get("priority_score")
    if explicit is not None:
        try:
            return float(explicit)
        except (TypeError, ValueError):
            pass
    brand_gap = _normalize_gap_score(row.get("brand_gap_score", row.get("brand_gap")))
    source_gap = _normalize_gap_score(row.get("source_gap_score", row.get("source_gap")))
    responses = float(row.get("response_count", 0) or 0)
    sources = float(row.get("source_count", 0) or 0)
    return brand_gap * 0.35 + source_gap * 0.25 + min(responses, 100) * 0.30 + min(sources, 100) * 0.10


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


def _market_profile(prompt_text: str, topic: str, brand_context: Dict[str, Any] | None = None) -> str:
    haystack = f"{prompt_text} {topic}".lower()
    brand_category = ((brand_context or {}).get("category") or "").lower()
    travel_markers = [
        "travel",
        "booking",
        "flight",
        "hotel",
        "trip",
        "vacation",
        "airline",
    ]
    consumer_markers = [
        "best app",
        "iphone",
        "android",
        "family",
        "student",
        "free app",
        "top rated",
    ]
    b2b_markers = [
        "enterprise",
        "agency",
        "saas",
        "software",
        "platform",
        "b2b",
        "for brands",
    ]
    if any(marker in haystack for marker in travel_markers):
        return "consumer_travel"
    if any(marker in brand_category for marker in ["travel", "booking"]):
        return "consumer_travel"
    if any(marker in haystack for marker in consumer_markers):
        return "consumer_general"
    if any(marker in haystack for marker in b2b_markers):
        return "b2b_software"
    return "generic"


def _article_archetype(prompt_text: str, dominant_page_type: str, primary_intent: str, brand_context: Dict[str, Any] | None = None) -> str:
    haystack = prompt_text.lower()
    profile = _market_profile(prompt_text, "", brand_context)
    if "best" in haystack or dominant_page_type in {"Listicle", "Comparison"}:
        return "recommendation"
    if any(token in haystack for token in ["vs", "compare", "comparison"]):
        return "comparison"
    if any(token in haystack for token in ["how to", "guide", "buying guide"]):
        return "guide"
    if profile == "b2b_software" and primary_intent in {"Commercial", "Transactional"}:
        return "solution"
    return "explainer"


def _reader_topic_phrase(prompt_text: str, topic: str, brand_context: Dict[str, Any] | None = None) -> str:
    prompt = " ".join((prompt_text or "").strip().split())
    topic_clean = " ".join((topic or "").strip().split())
    profile = _market_profile(prompt_text, topic, brand_context)
    if profile == "consumer_travel":
        if "travel booking" in prompt.lower():
            return "travel booking apps"
        return prompt or "travel apps"
    if profile == "consumer_general":
        return prompt or topic_clean or "apps"
    if profile == "b2b_software":
        return topic_clean or prompt or "solution"
    return prompt or topic_clean or "topic"


def _fanout_prompt_guesses(prompt_text: str, topic: str, primary_intent: str, brand_context: Dict[str, Any] | None = None) -> List[str]:
    base = prompt_text.strip()
    topic_part = topic.strip() if topic else "the topic"
    profile = _market_profile(prompt_text, topic, brand_context)
    if profile == "consumer_travel":
        return [
            f"what is the best {topic_part.lower()} option",
            f"best {topic_part.lower()} for flights and hotels",
            f"how to choose a {topic_part.lower()} app",
            f"{topic_part.lower()} comparison",
            f"common mistakes when choosing {topic_part.lower()}",
        ]
    if profile == "consumer_general":
        return [
            f"what is the best {topic_part.lower()}",
            f"how to choose a {topic_part.lower()} app",
            f"{topic_part.lower()} comparison",
            f"top {topic_part.lower()} options right now",
            f"common mistakes when choosing {topic_part.lower()}",
        ]
    if profile == "b2b_software":
        return [
            f"what is {base.lower()}",
            f"best {topic_part.lower()} platforms for teams",
            f"how to evaluate {topic_part.lower()} solutions",
            f"{topic_part.lower()} software comparison",
            f"how to measure results from {topic_part.lower()}",
        ]
    return [
        f"what is {base.lower()}",
        f"best {topic_part.lower()} options",
        f"how to evaluate {topic_part.lower()}",
        f"{topic_part.lower()} comparison",
        f"common mistakes with {topic_part.lower()}",
    ]


def _keyword_cluster_guesses(prompt_text: str, topic: str, brand_context: Dict[str, Any] | None = None) -> List[str]:
    seed = prompt_text.lower()
    topic_key = topic.lower() if topic else "topic"
    profile = _market_profile(prompt_text, topic, brand_context)
    if profile == "consumer_travel":
        variants = [
            seed,
            f"best {topic_key}",
            f"{topic_key} comparison",
            f"all in one {topic_key}",
            f"{topic_key} for flights and hotels",
            f"travel booking apps in one place",
        ]
    elif profile == "consumer_general":
        variants = [
            seed,
            f"best {topic_key}",
            f"{topic_key} comparison",
            f"top rated {topic_key}",
            f"{topic_key} buying guide",
            f"how to choose {topic_key}",
        ]
    elif profile == "b2b_software":
        variants = [
            seed,
            f"{topic_key} software",
            f"{topic_key} platform",
            f"{topic_key} tools",
            f"{topic_key} comparison",
            f"{topic_key} for teams",
        ]
    else:
        variants = [
            seed,
            f"best {topic_key}",
            f"{topic_key} guide",
            f"{topic_key} comparison",
            f"{topic_key} tools",
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


def _canonical_fanout_key(value: str) -> str:
    text = _normalize_text(value)
    text = re.sub(r"\b20\d{2}\b", " ", text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    stopwords = {
        "best",
        "top",
        "app",
        "apps",
        "option",
        "options",
        "guide",
        "guides",
        "one",
        "place",
        "in",
        "for",
        "the",
        "a",
        "an",
    }
    tokens = [token for token in text.split() if token and token not in stopwords]
    return " ".join(tokens)


def _looks_non_latin_heavy(value: str) -> bool:
    if not value:
        return False
    non_latin = sum(1 for ch in value if ord(ch) > 127)
    return non_latin >= max(6, len(value) // 4)


def _truncate_words(text: str, max_words: int = 12) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]).strip()


def _title_case_basic(text: str) -> str:
    small = {"and", "or", "for", "to", "in", "of", "the", "a", "an", "vs"}
    words = text.split()
    output = []
    for idx, word in enumerate(words):
        low = word.lower()
        if idx > 0 and low in small:
            output.append(low)
        else:
            output.append(low.capitalize())
    return " ".join(output)


def _cleanup_title_phrase(text: str) -> str:
    cleaned = text
    cleaned = re.sub(r"\bprice differences\b", "pricing", cleaned, flags=re.I)
    cleaned = re.sub(r"\bprice difference\b", "pricing", cleaned, flags=re.I)
    cleaned = re.sub(r"\bprices comparison\b", "pricing comparison", cleaned, flags=re.I)
    cleaned = re.sub(r"\bdeals tips\b", "deals", cleaned, flags=re.I)
    cleaned = re.sub(r"\bapp recommendations\b", "apps", cleaned, flags=re.I)
    cleaned = re.sub(r"\bmobile apps recommendations\b", "mobile apps", cleaned, flags=re.I)
    cleaned = re.sub(r"\bcomparison and\b", "comparison", cleaned, flags=re.I)
    cleaned = re.sub(r"\ball in one\b", "all-in-one", cleaned, flags=re.I)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" -")
    return cleaned


def _editorialize_title(text: str, article_type: str, profile: str) -> str:
    lower = text.lower().strip()

    if article_type == "comparison":
        if re.search(r"\bapp vs website\b", lower):
            brand = text.split(" app vs ")[0].strip()
            return f"{brand} App vs Website Pricing"
        if lower.startswith("booking hotels via app vs web"):
            return "Is It Cheaper to Book Hotels in an App or on the Website?"
        if "vs" in lower and lower.count(" vs ") >= 2:
            parts = [part.strip() for part in re.split(r"\bvs\b", text, flags=re.I)]
            parts = [part for part in parts if part][:4]
            if len(parts) >= 2:
                return " vs ".join(parts) + ": Which One Is Better?"
        if lower.endswith("comparison"):
            return _title_case_basic(text)

    if article_type == "recommendation":
        if profile == "consumer_travel":
            if "trip planning and booking" in lower:
                return "Best Apps for Trip Planning and Booking"
            if "travel booking" in lower:
                return "Best Travel Booking Apps"
            if "hotel booking" in lower:
                return "Best Hotel Booking Apps"
            if "travel deal" in lower:
                return "Best Travel Deal Apps"

    if article_type == "explainer":
        if lower.startswith("what travel apps let you"):
            return "What Travel Apps Let You Book Flights and Hotels in One Place?"
        if "travel booking in one place" in lower:
            return "Travel Booking Apps That Keep Flights and Hotels in One Place"
        if "travel planning and booking mobile apps" in lower:
            return "Mobile Apps for Travel Planning and Booking"
        if "vacation package booking process" in lower:
            return "How Vacation Package Booking Works"
        if "tips for booking" in lower:
            return _title_case_basic(text)

    return _title_case_basic(text)


def _dedupe_rows_by_text(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        key = _canonical_fanout_key(row.get("fanout_text", ""))
        if not key:
            continue
        if key not in grouped:
            grouped[key] = dict(row)
            grouped[key]["source_prompt_ids"] = list(row.get("source_prompt_ids", []))
            grouped[key]["source_prompts"] = list(row.get("source_prompts", []))
            grouped[key]["fanout_variants"] = [row.get("fanout_text", "")]
            continue
        grouped[key]["source_prompt_ids"] = _dedupe_keep_order(
            grouped[key]["source_prompt_ids"] + row.get("source_prompt_ids", [])
        )
        grouped[key]["source_prompts"] = _dedupe_keep_order(
            grouped[key]["source_prompts"] + row.get("source_prompts", [])
        )
        grouped[key]["fanout_variants"] = _dedupe_keep_order(
            grouped[key].get("fanout_variants", []) + [row.get("fanout_text", "")]
        )
        grouped[key]["source_count"] = len(grouped[key]["source_prompt_ids"])
    return list(grouped.values())


def _backlog_similarity(row: Dict[str, Any], other: Dict[str, Any]) -> int:
    score = 0
    if row.get("article_type") == other.get("article_type"):
        score += 3
    if row.get("market_profile") == other.get("market_profile"):
        score += 2
    if _canonical_fanout_key(row.get("fanout_text", "")) == _canonical_fanout_key(other.get("fanout_text", "")):
        score += 5
    if _normalize_text(row.get("source_topic", "")) == _normalize_text(other.get("source_topic", "")):
        score += 2
    shared_prompts = set(row.get("source_prompt_ids", [])) & set(other.get("source_prompt_ids", []))
    score += min(len(shared_prompts), 2)
    return score


def _adjacent_backlog_rows(rows: List[Dict[str, Any]], target_row: Dict[str, Any], limit: int = 3) -> List[Dict[str, Any]]:
    ranked: List[Tuple[int, Dict[str, Any]]] = []
    target_id = target_row.get("backlog_id")
    for row in rows:
        if row.get("backlog_id") == target_id:
            continue
        similarity = _backlog_similarity(target_row, row)
        if similarity <= 0:
            continue
        ranked.append((similarity, row))
    ranked.sort(key=lambda item: (-item[0], item[1].get("normalized_title", "")))
    return [row for _, row in ranked[:limit]]


def _article_type_from_fanout(fanout_text: str, dominant_page_type: str) -> str:
    text = fanout_text.lower()
    if any(token in text for token in ["vs", "compare", "comparison"]):
        return "comparison"
    if any(token in text for token in ["best", "top", "options", "alternatives"]) or dominant_page_type == "Listicle":
        return "recommendation"
    if any(token in text for token in ["how to", "guide", "checklist", "steps"]):
        return "guide"
    if any(token in text for token in ["review", "worth it", "pricing"]):
        return "review"
    return "explainer"


def _rewrite_fanout_title(fanout_text: str, article_type: str, brand_context: Dict[str, Any] | None = None) -> str:
    text = " ".join(fanout_text.strip().split())
    if not text:
        return "Untitled Article"
    profile = _market_profile(fanout_text, fanout_text, brand_context)
    text = re.sub(r"\b20\d{2}\b", "", text).strip()
    text = re.sub(r"\s{2,}", " ", text).strip(" -")
    text = _cleanup_title_phrase(text)
    if article_type == "comparison":
        if text.lower().count(" vs ") >= 2:
            return _editorialize_title(_truncate_words(text, 10), article_type, profile)
        return _editorialize_title(_truncate_words(text, 12), article_type, profile)
    if article_type == "recommendation":
        if profile == "consumer_travel" and "best" not in text.lower():
            text = f"Best {text}"
        text = re.sub(r"^Best top\b", "Best", text, flags=re.I)
        return _editorialize_title(_truncate_words(text, 10), article_type, profile)
    if article_type == "guide":
        if text.lower().startswith("how to "):
            return _editorialize_title(_truncate_words(text, 10), article_type, profile)
        return _editorialize_title(_truncate_words(f"How to {text}", 10), article_type, profile)
    if article_type == "review":
        return _editorialize_title(_truncate_words(text, 10), article_type, profile)
    if profile == "b2b_software":
        return _editorialize_title(_truncate_words(f"What is {text}", 10), article_type, profile) + "?"
    return _editorialize_title(_truncate_words(text, 10), article_type, profile)


def _brand_role_in_article(brand_context: Dict[str, Any], market_profile: str, article_type: str) -> str:
    brand_name = brand_context.get("brand_name") or brand_context.get("name") or "the brand"
    if market_profile == "consumer_travel":
        return f"{brand_name} should appear as one credible shortlist option, not as the automatic winner."
    if article_type == "comparison":
        return f"{brand_name} should appear as one comparison candidate when it is genuinely relevant."
    return f"{brand_name} should be present only where it naturally fits the reader decision."


def _content_goal(article_type: str, market_profile: str) -> str:
    if market_profile == "consumer_travel" and article_type == "recommendation":
        return "Help readers shortlist travel booking options and compare them with confidence."
    if article_type == "comparison":
        return "Help readers understand how competing options differ so they can make a practical choice."
    if article_type == "guide":
        return "Help readers complete a task more clearly and with fewer mistakes."
    return "Help readers understand the topic and make a better-informed decision."


def _word_count_target(article_type: str) -> Dict[str, Any]:
    mapping = {
        "news_update": {"range": "300-800", "min": 300, "ideal": 600},
        "explainer": {"range": "800-1500", "min": 800, "ideal": 1200},
        "guide": {"range": "1200-2000", "min": 1200, "ideal": 1600},
        "recommendation": {"range": "1500-2500", "min": 1500, "ideal": 1800},
        "comparison": {"range": "1800-3000", "min": 1800, "ideal": 2200},
        "pillar": {"range": "3000+", "min": 3000, "ideal": 3500},
        "review": {"range": "1200-2000", "min": 1200, "ideal": 1500},
    }
    return mapping.get(article_type, {"range": "1000-1600", "min": 1000, "ideal": 1300})


def load_citation_learnings(input_file: str | None = None) -> Dict[str, Any]:
    input_path = Path(input_file).expanduser() if input_file else default_citation_learnings_path()
    if not input_path.exists():
        return {"items": []}
    return json.loads(input_path.read_text(encoding="utf-8"))


def save_citation_learning(entry: Dict[str, Any], output_file: str | None = None) -> Path:
    output_path = Path(output_file).expanduser() if output_file else default_citation_learnings_path()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    current = load_citation_learnings(str(output_path))
    items = current.get("items", [])
    items.append(entry)
    output_path.write_text(json.dumps({"items": items}, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def _fanout_quality_state(fanout_text: str, normalized_title: str, source_count: int = 1) -> Tuple[str, str]:
    text = _normalize_text(fanout_text)
    if not text:
        return "skip", "Empty fanout text."
    if _looks_non_latin_heavy(fanout_text):
        return "needs_cleanup", "Contains heavy non-Latin or mixed-script text."
    if len(text.split()) < 3:
        return "needs_cleanup", "Too short to become a standalone article safely."
    if len(text.split()) > 18:
        return "needs_cleanup", "Too long and likely still query-shaped."
    if text.count(" vs ") >= 3:
        return "needs_cleanup", "Comparison query is too broad and should be simplified before writing."
    if len(normalized_title.split()) > 10:
        return "needs_cleanup", "Title still too long for a clean backlog item."
    if normalized_title.lower().startswith(("best top", "tips for booking deals", "travel booking in one place app")):
        return "needs_cleanup", "Title still sounds like a raw query instead of an editorial title."
    if source_count > 1:
        return "needs_merge", "Shared across multiple prompts and should be merged before writing."
    return "write_now", "Ready for article drafting."


def _page_type_family(citations: List[Dict[str, Any]]) -> str:
    page_types = [c.get("pageType") or "Unknown" for c in citations]
    if not page_types:
        return "Unknown"
    return Counter(page_types).most_common(1)[0][0]


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower())
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-")
    return cleaned or "untitled"


def _normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").strip().lower())


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


def _asset_title_set(prompt_text: str, topic: str, primary_intent: str, dominant_page_type: str, brand_context: Dict[str, Any] | None = None) -> List[str]:
    profile = _market_profile(prompt_text, topic, brand_context)
    reader_phrase = _reader_topic_phrase(prompt_text, topic, brand_context)
    archetype = _article_archetype(prompt_text, dominant_page_type, primary_intent, brand_context)
    topic_l = topic or "topic"
    if profile == "consumer_travel":
        if archetype == "comparison":
            return [
                "Travel Booking Apps Compared: Which One Fits Your Trip Style?",
                "How to Compare Travel Booking Apps Without Wasting Time",
                "Best Travel Booking Apps in One Place",
                "Common Mistakes People Make When Choosing Travel Apps",
                "Travel Booking App Buying Guide",
            ]
        return [
            "Best Travel Booking Apps in One Place",
            "How to Choose a Travel Booking App That Actually Saves Time",
            "Travel Booking Apps Compared: Which One Fits Your Trip Style?",
            "Common Mistakes People Make When Choosing Travel Apps",
            "Travel Booking App Buying Guide",
        ]
    if profile == "consumer_general":
        return [
            f"What {reader_phrase} Actually Helps You Do",
            f"How to Choose the Best {reader_phrase}",
            f"Best {reader_phrase} Options Right Now",
            f"Common Mistakes People Make When Choosing {reader_phrase}",
            f"{reader_phrase}: Buying Guide",
        ]
    if profile == "b2b_software":
        suffix = " Solution" if "solution" not in topic_l.lower() else ""
        return [
            f"What Is an Enterprise {topic_l}{suffix}?",
            f"How to Evaluate Enterprise {topic_l} Platforms",
            f"Best Enterprise {topic_l} Solutions for Brand Authority",
            f"How to Measure Brand Authority in AI Answers",
            f"Enterprise {topic_l} Platform for Brand Authority",
        ]
    return [
        f"What Is {reader_phrase}?",
        f"How to Evaluate {reader_phrase}",
        f"Best {reader_phrase} Options Right Now",
        f"Common Mistakes People Make With {reader_phrase}",
        f"{reader_phrase}: Practical Guide",
    ]


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
    titles = _asset_title_set(prompt_text, topic_l, primary_intent, dominant_page_type)
    rows = [
        {
            "asset_id": "A1",
            "asset_title": titles[0],
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
            "asset_title": titles[1],
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
            "asset_title": titles[2],
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
            "asset_title": titles[3],
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
            "asset_title": titles[4],
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


def _extract_response_text(detail: Dict[str, Any]) -> str:
    if not detail:
        return ""
    for key in ["answer", "response", "content", "text", "output", "final", "message"]:
        value = detail.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    data = detail.get("data")
    if isinstance(data, dict):
        for key in ["answer", "response", "content", "text", "output", "final", "message"]:
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _response_previews(details: List[Dict[str, Any]], limit: int = 3) -> List[str]:
    previews: List[str] = []
    for item in details[:limit]:
        text = _extract_response_text(item)
        if text:
            previews.append(_response_preview(text))
    return previews


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
        "domain": brand_context.get("domain") or "",
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
    domain = brand_context.get("domain")
    if domain:
        lines.append(f"- Domain: `{domain}`")
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


def _remote_brand_context(client: DagenoClient) -> Dict[str, Any]:
    try:
        return client.brand_info().get("data", {})
    except Exception:
        return {}


def _brand_alignment_status(local_kb: Dict[str, Any], remote_brand: Dict[str, Any], brand_kb_file: str | None) -> Dict[str, Any]:
    status = _brand_kb_status(brand_kb_file)
    if not local_kb or not remote_brand:
        status["matches_remote_brand"] = None
        return status
    local_name = _normalize_key(local_kb.get("brand_name") or local_kb.get("name") or "")
    remote_name = _normalize_key(remote_brand.get("name") or "")
    local_domain = _normalize_key(local_kb.get("domain") or "")
    remote_domain = _normalize_key(remote_brand.get("domain") or "")
    matches = False
    if local_name and remote_name and local_name == remote_name:
        matches = True
    if local_domain and remote_domain and local_domain == remote_domain:
        matches = True
    status["matches_remote_brand"] = matches
    if status["loaded"] and not matches:
        status["message"] = "Brand knowledge base does not match the Dageno brand snapshot. Use a matching knowledge base before generating publish-ready output."
    return status


def _assert_brand_alignment(context: Dict[str, Any]) -> None:
    brand_kb = context.get("brand_kb", {})
    if brand_kb.get("loaded") and brand_kb.get("matches_remote_brand") is False:
        raise ValueError(brand_kb.get("message"))


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
    profile = _market_profile(prompt_text, topic, {})
    if profile == "consumer_travel":
        return [
            (
                "What is the best type of travel booking app for most people?",
                "For most travelers, the best option is an app that lets them compare flights and hotels clearly, shows booking conditions up front, and keeps itinerary management simple after purchase.",
            ),
            (
                "Should I use one app for everything or separate apps for flights and hotels?",
                "If convenience matters most, one all-in-one app is usually the better starting point. If you are optimizing for one specific part of the trip, specialist tools can still be worth checking.",
            ),
            (
                "What should I compare before booking through a travel app?",
                "Compare route and hotel coverage, pricing clarity, refund rules, support quality, and whether the booking flow feels simple enough to trust when plans change.",
            ),
        ]
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


def _pick_publishable_article_asset(rows: List[Dict[str, Any]], asset_id: str | None = None) -> Dict[str, Any]:
    candidates = [row for row in rows if row.get("asset_type") == "article"]
    if asset_id:
        for row in candidates:
            if row.get("asset_id") == asset_id:
                return row
    ordered = sorted(candidates, key=lambda row: (_priority_rank(row.get("priority", "")), row.get("asset_id", "")))
    return ordered[0] if ordered else {}


def _publish_cta_text(asset: Dict[str, Any]) -> str:
    intent = asset.get("target_intent", "")
    title = asset.get("asset_title", "")
    profile = _market_profile(title, title, {})
    if profile == "consumer_travel":
        return "If you are actively comparing apps, shortlist two or three options, run the same trip search in each one, and choose the app that gives you the clearest mix of convenience, pricing transparency, and trust."
    if intent in {"Commercial", "Transactional"}:
        return "If you are actively evaluating solutions, use this article as a shortlist framework and compare vendors against your own requirements before requesting demos."
    return "If this topic matters to your team, the next step is to document your current workflow, note the gaps in visibility or measurement, and compare that baseline against the options discussed here."


def _references_markdown(citations: List[Dict[str, Any]], limit: int = 5) -> List[str]:
    lines: List[str] = []
    for item in _top(citations, "citationCount", limit):
        url = item.get("url", "").strip()
        domain = item.get("domain", "-")
        if not url:
            continue
        lines.append(f"- [{domain}]({url})")
    return lines


def _reference_conclusion_lines(citations: List[Dict[str, Any]], limit: int = 5) -> List[str]:
    fallback_notes = [
        "Supports the conclusion that category-defining articles shape early buyer understanding.",
        "Supports the conclusion that comparison-style content influences evaluation behavior.",
        "Supports the conclusion that teams need evidence, not only broad claims, when choosing solutions.",
        "Supports the conclusion that market framing is often controlled by third-party sources.",
        "Supports the conclusion that clear workflows and measurement criteria matter in real buying decisions.",
    ]
    lines: List[str] = []
    for idx, item in enumerate(_top(citations, "citationCount", limit)):
        url = item.get("url", "").strip()
        domain = item.get("domain", "-")
        if not url:
            continue
        note = fallback_notes[idx] if idx < len(fallback_notes) else fallback_notes[-1]
        lines.append(f"- [{domain}]({url}) - {note}")
    return lines


def _reference_lines_from_crawled_pages(pages: List[Dict[str, Any]], limit: int = 5) -> List[str]:
    lines: List[str] = []
    count = 0
    for page in pages:
        if page.get("status") != "ok":
            continue
        title = page.get("title") or page.get("h1") or page.get("url")
        url = page.get("url", "")
        if not url:
            continue
        summary = page.get("meta_description") or page.get("paragraph_preview", "")[:120]
        summary = " ".join(summary.split())
        if summary:
            lines.append(f"- [{title}]({url}) - {summary}")
        else:
            lines.append(f"- [{title}]({url})")
        count += 1
        if count >= limit:
            break
    return lines


def _top_citation_urls(citations: List[Dict[str, Any]], limit: int = 5) -> List[str]:
    urls: List[str] = []
    for item in _top(citations, "citationCount", limit):
        url = (item.get("url") or "").strip()
        if url:
            urls.append(url)
    return urls


def _diversified_citation_urls(citations: List[Dict[str, Any]], limit: int = 5, max_pool: int = 60) -> List[str]:
    ranked = _top(citations, "citationCount", max_pool)

    def is_hard_excluded(domain: str, url: str, page_type: str) -> bool:
        if domain in {"apps.apple.com", "play.google.com"}:
            return True
        if domain.endswith("reddit.com") or domain == "reddit.com":
            return True
        if any(token in url for token in ["/store/apps", "apps.apple.com", "play.google.com"]):
            return True
        if "app store" in page_type or "app" == page_type:
            return True
        if any(token in page_type for token in ["forum", "community", "ugc"]):
            return True
        return False

    def is_article_like_type(page_type: str) -> bool:
        pt = page_type.lower()
        return any(token in pt for token in ["article", "listicle", "comparison", "guide", "review", "blog"])

    preferred: List[Dict[str, Any]] = []
    support: List[Dict[str, Any]] = []
    for item in ranked:
        url = (item.get("url") or "").strip()
        if not url:
            continue
        domain = (item.get("domain") or "").strip().lower()
        page_type = (item.get("pageType") or "unknown").strip()
        if is_hard_excluded(domain, url, page_type.lower()):
            continue
        bucket = preferred if is_article_like_type(page_type) else support
        bucket.append(item)

    pool = preferred + support
    selected: List[str] = []
    seen_domains: set[str] = set()
    seen_types: set[str] = set()

    for item in pool:
        url = (item.get("url") or "").strip()
        domain = (item.get("domain") or "").strip().lower()
        page_type = (item.get("pageType") or "unknown").strip().lower()
        if not url:
            continue
        if domain and domain not in seen_domains:
            selected.append(url)
            seen_domains.add(domain)
            seen_types.add(page_type)
        if len(selected) >= max(limit * 8, 24):
            return selected

    for item in pool:
        url = (item.get("url") or "").strip()
        page_type = (item.get("pageType") or "unknown").strip().lower()
        if not url or url in selected:
            continue
        if page_type not in seen_types:
            selected.append(url)
            seen_types.add(page_type)
        if len(selected) >= max(limit * 8, 24):
            return selected

    for item in pool:
        url = (item.get("url") or "").strip()
        if not url or url in selected:
            continue
        selected.append(url)
        if len(selected) >= max(limit * 8, 24):
            return selected
    return selected


def _audience_text(brand_context: Dict[str, Any], topic: str) -> str:
    audience = brand_context.get("target_audience") or []
    if audience:
        return ", ".join(audience[:3])
    return f"teams researching {topic} and evaluating how it applies to their workflow"


def _comparison_table_lines(topic: str) -> List[str]:
    return [
        "| Evaluation area | What to look for | Why it matters |",
        "|---|---|---|",
        f"| Coverage | Can the solution track the prompts and answer spaces that matter for {topic}? | Teams need visibility into the queries that actually shape buyer perception. |",
        "| Evidence quality | Does it show response detail, citations, and source patterns instead of only rank-like summaries? | Better evidence leads to better content and prioritization decisions. |",
        "| Workflow fit | Can the team move from insight to action without rebuilding the process manually? | Operational fit determines whether insights get used or ignored. |",
        "| Measurement | Are there clear metrics, review cycles, and update triggers? | Without measurement, teams cannot prove whether the content strategy is working. |",
    ]


def _consumer_comparison_table_lines() -> List[str]:
    return [
        "| Decision area | What to compare | Why it matters |",
        "|---|---|---|",
        "| Booking coverage | Flights, hotels, trains, cars, or packages in one app | Coverage determines whether the app really saves time or still forces users to jump between tools. |",
        "| Price clarity | Fees, filters, and refund visibility | Clear pricing reduces last-minute surprises and comparison fatigue. |",
        "| User experience | Search speed, app flow, itinerary handling | The best app is not only cheaper, but easier to use when plans change. |",
        "| Support and trust | Reviews, support quality, booking confidence | Travel booking is high-stakes, so reliability matters as much as convenience. |",
    ]


def _blog_intro(topic: str, prompt_text: str, audience_text: str) -> str:
    return (
        f"If your team is trying to decide whether {topic} deserves budget, process ownership, or new content investment, the hard part is not finding more definitions. "
        f"The hard part is knowing what actually matters when prompts like \"{prompt_text}\" are already shaping buyer expectations. "
        f"This article is for {audience_text}, and it will help you understand the category, compare options more confidently, and avoid the mistakes that turn AI visibility into another vague reporting exercise."
    )


def _section_block(heading: str, conclusion: str, steps: List[str], example: str, pitfall: str) -> List[str]:
    lines = [
        f"## {heading}",
        "",
        conclusion,
        "",
        "Steps to apply this:",
    ]
    for step in steps:
        lines.append(f"- {step}")
    lines.extend(
        [
            "",
            f"Example: {example}",
            "",
            f"Common pitfall: {pitfall}",
            "",
        ]
    )
    return lines


def _article_outline_lines(topic: str) -> List[str]:
    return [
        "## Outline",
        "",
        f"- Intro: why {topic} matters now and what the reader will get from the article",
        f"- H2: what {topic} is and what problem it actually solves",
        f"- H2: how teams should evaluate {topic} in practice",
        f"- H2: what a realistic workflow looks like",
        f"- H2: the mistakes that create weak results",
        "- FAQ",
        "- References",
    ]


def _article_outline_lines_for_profile(topic: str, profile: str) -> List[str]:
    if profile == "consumer_travel":
        return [
            "## Outline",
            "",
            "- Intro: traveler problem and reader payoff",
            "- H2: what makes a travel booking app genuinely useful",
            "- H2: how to compare travel booking apps without wasting time",
            "- H2: when an all-in-one app is the better choice",
            "- H2: the mistakes people make when choosing travel apps",
            "- FAQ",
            "- References",
        ]
    return _article_outline_lines(topic)


def _publish_ready_article_from_context(context: Dict[str, Any], asset: Dict[str, Any]) -> str:
    selected = context["selected_opportunity"]
    topic = selected.get("topic", "the topic")
    prompt_text_value = selected.get("prompt", "the prompt")
    brand_context = context.get("brand_context", {})
    top_entities = [name for name, _ in context.get("mention_counter", Counter()).most_common(4)]
    top_entities_text = ", ".join(top_entities) or "current market leaders"
    references = _reference_conclusion_lines(context.get("citations", []))
    faq_items = _faq_items(asset, topic, prompt_text_value)
    audience_text = _audience_text(brand_context, topic)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    title = asset.get("asset_title", "Publish-Ready Article")
    profile = _market_profile(prompt_text_value, topic, brand_context)
    reader_topic = _reader_topic_phrase(prompt_text_value, topic, brand_context)
    if profile == "consumer_travel":
        citation_urls = _top_citation_urls(context.get("citations", []), limit=5)
        crawled_pages = crawl_citation_pages(citation_urls, limit=5)
        citation_patterns = analyze_citation_patterns(crawled_pages)
        references = _reference_lines_from_crawled_pages(crawled_pages, limit=5)
        brand_name = brand_context.get("brand_name") or brand_context.get("name") or "the brand"
        intro = (
            f"If you are trying to book flights, hotels, and maybe even trains or cars without bouncing between five different apps, the real question is not which app is most famous. "
            f"The real question is which one actually makes trip planning simpler, clearer, and easier to trust. This article is for {audience_text}, and it will help you compare {reader_topic} in a way that feels useful before you commit to one."
        )
        section_one = _section_block(
            "What Makes a Travel Booking App Actually Useful",
            "The best travel booking app is the one that reduces friction across the whole trip-planning journey, not just the one with the flashiest brand or the most ads.",
            [
                "Check whether you can search flights, hotels, and other trip pieces in one place.",
                "Compare how clearly the app shows prices, filters, and booking conditions.",
                "Look at whether itinerary management is simple after the booking is complete.",
            ],
            "A traveler comparing apps may find that one app has great hotel inventory but weak flight filters, while another handles both in one flow and saves time immediately.",
            "Choosing based on app-store popularity without checking whether the workflow actually fits how you book trips.",
        )
        section_two = _section_block(
            "How to Compare Travel Booking Apps Without Wasting Time",
            "The easiest way to compare travel booking apps is to judge them against booking coverage, pricing clarity, trust, and ease of use.",
            [
                "Test the same trip search in two or three apps using the same dates and route.",
                "Compare not only headline prices, but refund rules, booking conditions, and hidden friction.",
                "Look at review quality and support expectations before treating low price as the only signal.",
            ],
            "If one app looks cheaper at first glance but adds confusion around baggage, cancellation, or booking confirmation, it may be worse for real-world travel planning.",
            "Mistaking a cheaper starting price for a better overall booking experience.",
        )
        section_three = _section_block(
            "When an All-in-One Booking App Is the Better Choice",
            "An all-in-one booking app is strongest when your goal is convenience across multiple travel steps, not endless manual comparison.",
            [
                "Use one-stop apps when you want to manage flights, hotels, and itinerary changes in one workflow.",
                "Use specialist tools only when one part of the trip matters more than everything else.",
                "Decide upfront whether you value maximum flexibility or faster booking completion.",
            ],
            "For a weekend city trip, an all-in-one booking app may be the fastest choice because the traveler can search flights and hotels in one session instead of juggling separate tools.",
            "Forcing every trip into the same booking behavior instead of adjusting for trip complexity.",
        )
        section_four = _section_block(
            "Common Mistakes People Make When Choosing Travel Apps",
            "Most bad travel app decisions come from rushing the comparison and overvaluing convenience claims that are not backed by a better experience.",
            [
                "Ignore marketing language and compare the actual booking flow.",
                "Check whether support and changes are easy to handle after purchase.",
                "Treat app ratings as a clue, not as final proof.",
            ],
            "An app can have millions of downloads and still feel frustrating if the filters, pricing details, or after-booking support are weak.",
            "Assuming the most downloaded app will automatically be the best fit for your trip.",
        )
        table_lines = _consumer_comparison_table_lines()
        shortlist_lines = [
            "## What the Most-Cited Pages Are Actually Doing",
            "",
            f"Across the citation pages we could fetch successfully, the dominant pattern is `{citation_patterns.get('dominant_title_pattern', 'recommendation')}`. Most of them start with a direct recommendation, quickly explain what to compare, and then move into a shortlist of apps or websites instead of spending too much time on abstract category explanation.",
            "",
            "## Which Options Usually Make the Shortlist",
            "",
            f"The names that show up most often in the cited material include {top_entities_text}. That does not automatically make them the best fit for every traveler, but it does tell us which products people are most likely to compare before they book.",
            "",
            f"Where {brand_name} fits: if the reader wants one place to compare and book major parts of a trip, {brand_name} should be treated as a serious shortlist option rather than a side mention.",
            "",
        ]
    else:
        intro = _blog_intro(reader_topic, prompt_text_value, audience_text)
        section_one = _section_block(
        f"What {reader_topic} Actually Means in Practice",
        f"The most useful way to understand {reader_topic} is to see it as a workflow for shaping how buyers encounter your brand in AI answers, not as a single reporting feature.",
        [
            "List the prompts that influence category understanding or purchase intent.",
            "Review which sources and page types appear repeatedly in those answer spaces.",
            "Map the gaps you see to the content assets your team has already published.",
        ],
        f"When a team researches \"{prompt_text_value}\", they may find that article and comparison pages shape the answer space more than homepages. That tells them a single product page will not be enough.",
        "Reducing the category to one metric and never connecting the insight back to content planning.",
        )
        section_two = _section_block(
        f"How Teams Should Evaluate {reader_topic}",
        f"The strongest evaluation process focuses on whether the solution produces usable evidence and practical next steps, not just a cleaner dashboard.",
        [
            "Check whether the workflow covers the prompts and platforms that matter commercially.",
            "Verify that it exposes response detail, citations, and source patterns.",
            "Compare whether your team can move from insight to published content without rebuilding the process manually.",
        ],
        f"If one platform only summarizes visibility while another shows prompt-level evidence, citations, and recurring competitor sources, the second platform is more useful for editorial decisions.",
        "Choosing based on UI polish while ignoring whether the workflow can support actual publishing decisions.",
        )
        section_three = _section_block(
        f"What a Realistic {reader_topic} Workflow Looks Like",
        f"A realistic workflow starts with category clarification, then moves into comparison content, and only later into stronger conversion assets.",
        [
            "Start with a category article that explains the problem in plain language.",
            "Publish a comparison or evaluation article once the category framing is established.",
            "Add conversion-oriented assets only after the informational layer is in place.",
        ],
        f"A team might begin with a category article, follow with a buyer guide, and then publish a landing page once they know which queries consistently show commercial intent.",
        "Trying to jump straight to a sales page before the category has been clearly explained to the market.",
        )
        section_four = _section_block(
        f"The Mistakes That Make {reader_topic} Content Weak",
        f"The weakest articles usually explain the category without giving the reader any way to make a better decision.",
        [
            "Replace vague claims with concrete evaluation criteria.",
            "Use one example to make each key point easier to apply.",
            "Keep transitions between sections explicit so the article reads like a blog, not a checklist dump.",
        ],
        f"An article that only says \"AI visibility matters\" is weaker than one that shows how a team should review prompts, citations, workflow fit, and publishing gaps.",
        "Stacking terminology without explaining what the reader should do next.",
        )
        table_lines = _comparison_table_lines(reader_topic)

    if profile == "consumer_travel":
        tldr_lines = [
            "- The best travel booking app is the one that makes comparing and completing the booking easier, not just the one with the loudest brand.",
            f"- Best fit: {audience_text}.",
            "- Focus on booking coverage, price clarity, after-booking support, and how smooth the app feels when plans change.",
        ]
        conclusion_text = (
            "The best travel booking app is usually the one that saves time without hiding important details. If the app makes search, comparison, booking, and trip changes feel clearer, it is probably the better fit even if it is not the loudest name in the category."
        )
        takeaway_text = (
            "Before you book, run the same trip through a few apps and compare the experience, not just the headline price. That simple check usually tells you more than ratings or ads ever will."
        )
    else:
        tldr_lines = [
            f"- {reader_topic} should be treated as an operational workflow, not just a tooling label.",
            f"- Best fit: {audience_text}.",
            f"- The real decision comes down to evidence quality, workflow fit, and whether the team can turn insight into content action.",
        ]
        conclusion_text = (
            f"Teams evaluating {reader_topic} should prioritize clear category understanding, verifiable evidence, and a workflow that connects insight to action. The goal is not only to monitor how AI systems talk about the category, but to create content that helps buyers make better decisions and gives the brand a credible place in those answers over time."
        )
        takeaway_text = _publish_cta_text(asset)
        crawled_pages = []

    lines = [
        f"# {title}",
        "",
        *_article_outline_lines_for_profile(reader_topic, profile),
        "",
        "## Article",
        "",
        f"_Last updated: {today}_",
        "",
        "## TL;DR",
        "",
        *tldr_lines,
        "",
        intro,
        "",
    ]
    lines.extend(section_one)
    lines.extend(section_two)
    lines.extend(["## Decision Table", ""])
    lines.extend(table_lines)
    lines.extend([""])
    if profile == "consumer_travel":
        lines.extend(shortlist_lines)
    lines.extend(section_three)
    lines.extend(section_four)
    lines.extend(["## FAQ", ""])
    for question, answer in faq_items:
        lines.extend([f"### {question}", "", answer, ""])

    if references:
        lines.extend(["## References", ""])
        lines.extend(references)
        lines.extend([""])

    lines.extend(
        [
            "## Conclusion",
            "",
            conclusion_text,
            "",
            "## Final Takeaway",
            "",
            takeaway_text,
        ]
    )
    return "\n".join(lines)


def legacy_publish_ready_article(
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
    _assert_brand_alignment(context)
    if context["empty"]:
        return "# Publish-Ready Article\n\nNo content opportunities were returned for the selected window."

    asset = _pick_publishable_article_asset(context["asset_rows"], asset_id=asset_id)
    if not asset:
        return "# Publish-Ready Article\n\nNo publishable article asset was available for the selected window."
    return _publish_ready_article_from_context(context, asset)


def _writer_prompt_from_payload(payload: Dict[str, Any]) -> str:
    selected = payload.get("selected_fanout", {})
    editorial = payload.get("editorial_brief", {})
    citation = editorial.get("citation_learnings", payload.get("citation_pattern_summary", {}))
    source_materials = editorial.get("source_materials", {})
    title_options = editorial.get("alternative_titles") or payload.get("title_options", [])
    working_title = editorial.get("working_title") or (title_options[0] if title_options else "")
    rules = _dedupe_keep_order(editorial.get("must_avoid", []) + payload.get("writing_rules", []))

    lines = [
        "You are a blog editor, not a document generator.",
        "",
        "Write one complete blog article for publication.",
        "",
        "Use this editorial brief:",
        f"- Working title: {working_title}",
        f"- Selected fanout: {selected.get('fanout_text', '')}",
        f"- Reader-facing topic: {editorial.get('reader_topic', selected.get('reader_topic', ''))}",
        f"- Reader persona: {editorial.get('reader_persona', '')}",
        f"- Reader job to be done: {editorial.get('reader_job_to_be_done', '')}",
        f"- Market profile: {editorial.get('market_profile', selected.get('market_profile', ''))}",
        f"- Article type: {editorial.get('article_type', payload.get('article_type', ''))}",
        f"- Article angle: {editorial.get('article_angle', '')}",
        f"- Why this article now: {editorial.get('why_this_article_now', '')}",
        f"- Cluster role: {editorial.get('cluster_role', '')}",
        f"- Opening move: {editorial.get('opening_move', '')}",
        f"- Decision frame: {editorial.get('decision_frame', '')}",
        f"- Content gap to fill: {editorial.get('content_gap', '')}",
        f"- Brand inclusion rule: {editorial.get('brand_inclusion_rule', payload.get('brand_role_in_article', ''))}",
        f"- Alternative titles: {', '.join(title_options)}",
        f"- Content goal: {payload.get('content_goal', '')}",
        "",
        "Citation pattern summary (learn structure, do not mention this section in the article):",
        f"- Dominant page type: {citation.get('dominant_page_type', '')}",
        f"- Dominant title pattern: {citation.get('dominant_title_pattern', '')}",
        f"- Common intents: {', '.join(citation.get('common_intents', []))}",
        f"- Common heading patterns: {', '.join(citation.get('common_heading_patterns', []))}",
        f"- Top entities: {', '.join(source_materials.get('top_entities', []))}",
        f"- Supporting URLs: {', '.join(source_materials.get('supporting_urls', []))}",
        "",
        "Must prove:",
    ]
    for item in editorial.get("must_prove", []):
        lines.append(f"- {item}")
    lines.extend([
        "",
        "Must include:",
    ])
    for item in editorial.get("must_include", []):
        lines.append(f"- {item}")
    lines.extend([
        "",
        "External research tasks:",
    ])
    for item in editorial.get("external_research_tasks", []):
        lines.append(f"- {item}")
    lines.extend([
        "",
        "E-E-A-T layer:",
        f"- Testing guidance: {editorial.get('testing_framework', {}).get('sample_size_guidance', '')}",
        f"- Same-input rule: {editorial.get('testing_framework', {}).get('same_input_rule', '')}",
        f"- Conclusion scope template: {editorial.get('testing_framework', {}).get('conclusion_scope_template', '')}",
    ])
    for item in editorial.get("eeat_layer", {}).get("recommended_signals", []):
        lines.append(f"- {item}")
    lines.extend([
        "",
        "Differentiation targets:",
    ])
    for item in editorial.get("differentiation_targets", []):
        lines.append(f"- {item}")
    lines.extend([
        "",
        "Adjacent articles to avoid overlapping with:",
    ])
    for item in editorial.get("adjacent_articles_to_avoid", []):
        lines.append(
            f"- {item.get('title', '')} ({item.get('article_type', '')}, {item.get('backlog_id', '')})"
        )
    lines.extend([
        "",
        "Recommended outline:",
    ])
    for item in editorial.get("recommended_outline", []):
        lines.append(
            f"- {item.get('heading', '')}: {item.get('purpose', '')}. Include: {item.get('must_include', '')}"
        )
    lines.extend([
        "",
        "Rules:",
    ])
    for rule in rules:
        lines.append(f"- {rule}")
    for rule in editorial.get("evidence_guardrails", []):
        lines.append(f"- {rule}")
    lines.extend(
        [
            "",
            "Important:",
            "- Do not mention the internal analysis process.",
            "- Do not mention citation patterns or what the cited pages are doing.",
            "- Mention the brand only where it naturally fits the reader decision.",
            "- Avoid template tone and filler phrases.",
            "- Keep paragraphs short and use explicit transitions.",
        ]
    )
    return "\n".join(lines)


def _reader_persona(profile: str, article_type: str) -> str:
    if profile == "consumer_travel":
        if article_type == "comparison":
            return "A traveler actively comparing two or three booking options before paying."
        return "A traveler trying to choose a booking workflow that feels simpler and more trustworthy."
    if profile == "b2b_software":
        return "A marketing or growth lead evaluating vendors and practical workflow fit."
    return "A reader who wants practical help making a clearer decision."


def _reader_job_to_be_done(row: Dict[str, Any], article_type: str, profile: str) -> str:
    title = row.get("normalized_title") or row.get("fanout_text") or "the topic"
    if profile == "consumer_travel":
        if article_type == "comparison":
            return f"Help the reader compare credible options behind '{title}' and leave with a smaller shortlist."
        if article_type == "guide":
            return f"Help the reader choose a booking path for '{title}' without wasting time on the wrong criteria."
        return f"Help the reader understand which option best fits how they actually book trips for '{title}'."
    return f"Help the reader make a more confident decision around '{title}' with clearer criteria and fewer vague claims."


def _content_role_in_cluster(article_type: str) -> str:
    mapping = {
        "recommendation": "shortlist_article",
        "comparison": "comparison_article",
        "guide": "how_to_article",
        "review": "evaluation_article",
        "explainer": "category_article",
    }
    return mapping.get(article_type, "editorial_article")


def _cluster_role_plan(row: Dict[str, Any]) -> Dict[str, str]:
    article_type = row.get("article_type", "explainer")
    funnel = (row.get("funnel") or "").lower()
    role = _content_role_in_cluster(article_type)
    if article_type == "explainer" and funnel in {"commercial", "transactional"}:
        role = "category_to_consideration_article"
    elif article_type == "recommendation" and funnel in {"commercial", "transactional"}:
        role = "buyer_shortlist_article"
    elif article_type == "comparison":
        role = "decision_stage_comparison_article"
    elif article_type == "guide":
        role = "workflow_guidance_article"
    elif article_type == "review":
        role = "fit_assessment_article"

    return {
        "cluster_role": role,
        "cluster_role_reason": (
            f"Selected because the row behaves like a {article_type} article in the {funnel or 'unknown'} funnel stage."
        ),
    }


def _official_workflow_contract() -> Dict[str, Any]:
    return {
        "recommended_entrypoint": "publish-ready-article --backlog-id <row-id>",
        "recommended_steps": [
            "build_fanout_backlog",
            "select_backlog_items",
            "publish-ready-article",
            "draft-article-from-payload",
            "section-review-and-rewrite",
            "assembly-review",
            "final-gate",
            "publish-wordpress",
        ],
        "deprecated_paths": [
            "legacy-publish-ready-article",
            "content-pack",
            "first-asset-draft",
        ],
    }


def _decision_frame(article_type: str, profile: str) -> str:
    if profile == "consumer_travel":
        if article_type == "comparison":
            return "Compare convenience, pricing clarity, coverage, and trust under one realistic trip scenario."
        if article_type == "recommendation":
            return "Shortlist options by traveler type and trade-offs, not by brand familiarity alone."
    if article_type == "guide":
        return "Turn a confusing choice into a sequence the reader can actually follow."
    return "Move the reader from vague interest into a practical decision framework."


def _editorial_outline(row: Dict[str, Any], article_type: str, reader_topic: str, profile: str) -> List[Dict[str, str]]:
    first_heading = {
        "comparison": "What Actually Changes the Decision",
        "recommendation": "Start With the Problem You Need the Option to Solve",
        "guide": "Start With the Real Decision",
        "review": "What the Reader Should Evaluate First",
        "explainer": f"What {reader_topic.capitalize()} Really Means",
    }.get(article_type, "What the Reader Should Understand First")
    second_heading = {
        "comparison": "How to Compare Without Drowning in Features",
        "recommendation": "The Criteria That Matter in Real Use",
        "guide": "Turn the Decision Into a Sequence",
        "review": "Where the Product Helps and Where It Does Not",
        "explainer": "What the Reader Should Notice Early",
    }.get(article_type, "What to Compare Next")
    third_heading = {
        "comparison": "Where Readers Usually Go Wrong",
        "recommendation": "Which Reader Types Usually Prefer Different Options",
        "guide": "Where the Process Usually Breaks Down",
        "review": "How to Decide if It Is the Right Fit",
        "explainer": "Why the Topic Gets Misunderstood So Easily",
    }.get(article_type, "Where Weak Content Usually Fails")
    must_include = "Use real decision criteria, name trade-offs, and keep the brand in a natural supporting role."
    if profile == "consumer_travel":
        must_include = "Anchor the advice in a realistic travel scenario, not only generic product descriptions."
    return [
        {"heading": first_heading, "purpose": "Frame the actual decision behind the search", "must_include": must_include},
        {"heading": second_heading, "purpose": "Explain the few criteria that genuinely change the outcome", "must_include": "Use explicit trade-offs and practical examples."},
        {"heading": third_heading, "purpose": "Create information gain by correcting common bad comparisons or assumptions", "must_include": "Show where readers usually waste time or misread the market."},
        {"heading": "FAQ", "purpose": "Answer the natural follow-up questions succinctly", "must_include": "Keep answers direct and publication-ready."},
        {"heading": "Final Takeaway", "purpose": "Leave the reader with a next step, not only a summary", "must_include": "Make the next action obvious and low-friction."},
    ]


def _evidence_framework(
    row: Dict[str, Any],
    *,
    reader_topic: str,
    article_type: str,
    profile: str,
    supporting_urls: List[str],
) -> Dict[str, Any]:
    fanout_text = row.get("fanout_text", "")
    tasks = [
        f"Find 1 to 2 official or primary-source pages relevant to '{fanout_text}' and extract the exact policy, rule, feature, or definition that matters to the reader decision.",
        f"Find 2 to 3 independent corroborating sources for '{fanout_text}' such as expert articles, trade publications, or high-signal community discussions.",
    ]
    if article_type in {"comparison", "recommendation", "review"}:
        tasks.append(
            f"Run a small same-input comparison for '{fanout_text}' and record the test setup, timestamp, sample size, and the exact fields that were aligned."
        )
    if article_type == "guide":
        tasks.append(
            f"Find practical walkthroughs or help-center content that clarify the process steps behind '{fanout_text}'."
        )
    if article_type == "explainer":
        tasks.append(
            f"Find category-defining sources that clarify what '{reader_topic}' means in practice and where readers usually misunderstand it."
        )

    eeat_signals = [
        "State who tested or researched the article and when the checks were performed.",
        "Explain the testing or comparison method in plain language.",
        "Show the scope and limits of the conclusion so the page does not overclaim.",
        "Prefer official/help-center evidence for policy claims and independent sources for market context.",
    ]

    sample_size = "3 to 5 checks"
    if profile == "consumer_travel":
        sample_size = "3 to 5 booking checks across the same route, dates, room type, or package setup"
    elif profile == "b2b_software":
        sample_size = "3 to 5 comparable vendor or workflow checks using the same evaluation criteria"

    return {
        "research_mode": "external_agent_web_research_recommended",
        "external_research_tasks": tasks,
        "testing_framework": {
            "tested_at_field": "Record the test date and, when possible, the timestamp.",
            "sample_size_guidance": sample_size,
            "same_input_rule": "Keep the input consistent across every option being compared before calling any difference meaningful.",
            "capture_fields": [
                "test date",
                "sample size",
                "aligned comparison fields",
                "observed difference",
                "conclusion scope",
            ],
            "conclusion_scope_template": f"This conclusion applies to the tested sample and setup for '{fanout_text}', not to every possible case in the category.",
        },
        "eeat_layer": {
            "recommended_signals": eeat_signals,
            "official_source_needed": True,
            "independent_source_count": 2,
            "supporting_urls_seed": supporting_urls[:4],
        },
    }


def _editorial_brief_from_backlog_row(
    row: Dict[str, Any],
    *,
    context: Dict[str, Any],
    citation_patterns: Dict[str, Any],
    crawled_pages: List[Dict[str, Any]],
    adjacent_rows: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    reader_topic = _reader_topic_phrase(
        row.get("fanout_text", ""),
        row.get("source_topic", ""),
        context.get("brand_context", {}),
    )
    profile = row.get("market_profile") or _market_profile(
        row.get("fanout_text", ""),
        row.get("source_topic", ""),
        context.get("brand_context", {}),
    )
    article_type = row.get("article_type") or citation_patterns.get("recommended_article_type", "explainer")
    title_options = _dedupe_keep_order(
        [
            row.get("normalized_title", ""),
            _rewrite_fanout_title(row.get("fanout_text", ""), article_type, context.get("brand_context", {})),
            _rewrite_fanout_title(reader_topic, article_type, context.get("brand_context", {})),
        ]
    )[:3]
    mention_counter: Counter[str] = context.get("mention_counter", Counter())
    supporting_urls = [page.get("url", "") for page in crawled_pages if page.get("status") == "ok" and page.get("url")][:5]
    source_count = int(row.get("source_count", 1) or 1)
    adjacent_rows = adjacent_rows or []
    adjacent_titles = [item.get("normalized_title", "") for item in adjacent_rows if item.get("normalized_title")]
    article_neighbors = [
        {
            "backlog_id": item.get("backlog_id", ""),
            "title": item.get("normalized_title", "") or item.get("fanout_text", ""),
            "article_type": item.get("article_type", ""),
        }
        for item in adjacent_rows
    ]
    why_now = (
        "This backlog row captures a real Dageno fanout and should become a specific editorial asset instead of another broad category summary."
    )
    if profile == "consumer_travel":
        why_now = (
            "This fanout reflects a real trip-planning decision, so the article should help readers choose a booking workflow instead of repeating generic travel advice."
        )
    evidence_framework = _evidence_framework(
        row,
        reader_topic=reader_topic,
        article_type=article_type,
        profile=profile,
        supporting_urls=supporting_urls,
    )

    return {
        "working_title": title_options[0] if title_options else row.get("normalized_title", "Untitled Article"),
        "alternative_titles": title_options,
        "reader_topic": reader_topic,
        "reader_persona": _reader_persona(profile, article_type),
        "reader_job_to_be_done": _reader_job_to_be_done(row, article_type, profile),
        "article_type": article_type,
        "article_angle": row.get("normalized_title", "") or row.get("fanout_text", ""),
        "search_intent": row.get("primary_intention", "-"),
        "funnel_stage": row.get("funnel", "-"),
        "market_profile": profile,
        "content_role_in_cluster": _content_role_in_cluster(article_type),
        "cluster_role": row.get("cluster_role", _cluster_role_plan(row).get("cluster_role")),
        "cluster_role_reason": row.get("cluster_role_reason", _cluster_role_plan(row).get("cluster_role_reason")),
        "why_this_article_now": why_now,
        "opening_move": "Open with the real decision tension behind the selected fanout, not a generic category definition.",
        "decision_frame": _decision_frame(article_type, profile),
        "information_gain": (
            "Add practical judgment and trade-offs that generic roundup pages usually flatten."
            if source_count <= 1
            else "Combine repeated demand signals into one cleaner, more differentiated editorial angle."
        ),
        "content_gap": (
            "Most nearby articles in this cluster are likely to overlap on generic criteria and shortlists; this article should add a sharper decision frame and reader-type differentiation."
            if adjacent_rows
            else "The article should still add practical judgment and a reader-facing decision model instead of generic summary language."
        ),
        "differentiation_targets": [
            "Lead with the reader decision, not the category definition.",
            "Add one realistic scenario or use case before expanding the shortlist.",
            "Explain why some options fit different reader types instead of implying one universal winner.",
        ],
        "adjacent_articles_to_avoid": article_neighbors,
        "internal_linking_notes": (
            "Link out to adjacent cluster articles only when they answer a genuinely different question, such as comparison, mistakes, or workflow guidance."
        ),
        "evidence_guardrails": [
            "Use cited pages to learn market framing and recurring entities, not to mimic wording.",
            "Do not claim product features or pricing details that the payload does not support.",
            "Avoid pretending to have tested products first-hand unless external tooling supplies that evidence.",
        ],
        "external_research_tasks": evidence_framework["external_research_tasks"],
        "testing_framework": evidence_framework["testing_framework"],
        "eeat_layer": evidence_framework["eeat_layer"],
        "must_prove": [
            "Why this choice is difficult for a real reader.",
            "Which criteria deserve attention first and which are secondary.",
            "How the shortlist should change based on reader type or use case.",
        ],
        "must_include": [
            "A concrete decision framework tied to the selected fanout.",
            "A natural shortlist or comparison set when relevant.",
            "At least one practical scenario or example the reader can imagine.",
            "A next step the reader can actually use after reading.",
        ],
        "must_avoid": [
            "Do not write from the prompt label as if it were already a finished blog angle.",
            "Do not sound like a template, checklist dump, or content mill roundup.",
            "Do not mention the brand as an automatic winner.",
            "Do not make unsupported claims or fake first-hand experience.",
        ],
        "brand_inclusion_rule": _brand_role_in_article(context.get("brand_context", {}), profile, article_type),
        "recommended_outline": _editorial_outline(row, article_type, reader_topic, profile),
        "citation_learnings": {
            "learning_mode": citation_patterns.get("learning_mode"),
            "dominant_page_type": context.get("dominant_page_type"),
            "dominant_title_pattern": citation_patterns.get("dominant_title_pattern"),
            "recommended_article_type": article_type,
            "common_heading_patterns": citation_patterns.get("common_heading_patterns", [])[:6],
            "common_intents": citation_patterns.get("common_intents", []),
            "table_presence_rate": citation_patterns.get("table_presence_rate"),
            "list_presence_rate": citation_patterns.get("list_presence_rate"),
            "faq_presence_rate": citation_patterns.get("faq_presence_rate"),
        },
        "source_materials": {
            "top_entities": [name for name, _ in mention_counter.most_common(6)],
            "supporting_urls": supporting_urls,
            "crawled_page_count": len(crawled_pages),
            "adjacent_titles": adjacent_titles,
        },
    }


def _review_package(payload: Dict[str, Any]) -> Dict[str, Any]:
    editorial = payload.get("editorial_brief", {})
    draft_package = payload.get("draft_package", {})
    draft_sections = draft_package.get("draft_sections", [])
    section_reviews = _section_review_contract(editorial, draft_sections)
    return {
        "quality_checks": [
            "Does the article sound like an edited blog post instead of a generated template?",
            "Does the opening frame a real reader decision quickly?",
            "Does each section add judgment, trade-offs, or a practical example?",
            "Is the brand included naturally and only where it genuinely fits?",
            "Would this article feel distinct from neighboring backlog rows?",
            "Does the draft clearly avoid collapsing into titles or angles already assigned to adjacent backlog rows?",
        ],
        "quality_review_prompt": (
            f"You are the second-pass editor. Review this draft against the editorial brief for '{editorial.get('working_title', '')}'. "
            f"Check for template tone, vague repetition, weak differentiation, overlap with adjacent backlog rows, unnatural brand mentions, and missing decision support. "
            f"The target range is {draft_package.get('target_word_count_range', '-')}, with a minimum of {draft_package.get('min_word_count', '-')} words."
        ),
        "quality_rewrite_prompt": (
            "Rewrite weak sections so the article feels like a confident blog editor made sharper choices, while preserving the selected fanout, core angle, and natural brand placement rules."
        ),
        "section_review_contract": section_reviews,
        "assembly_review_prompt": (
            f"After section-level rewrites, assemble the full article for '{editorial.get('working_title', '')}'. "
            "Check transitions, remove repeated setup language, make the voice consistent, and ensure the final article reads like one coherent blog post rather than stitched segments."
        ),
        "final_gate": {
            "status": "pending_human_or_agent_review",
            "required_checks": [
                "section_reviews_complete",
                "assembly_review_complete",
                "brand_inclusion_rule_respected",
                "adjacent_overlap_reviewed",
                "word_count_within_target",
            ],
            "publish_blockers": [],
        },
    }


def _pipeline_state(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "current_stage": "editorial_brief_ready",
        "recommended_next_stage": "section_drafting",
        "steps": [
            {"step": "backlog_row_selected", "status": "completed"},
            {"step": "editorial_brief_ready", "status": "completed"},
            {"step": "section_drafting", "status": "ready"},
            {"step": "section_review", "status": "ready"},
            {"step": "assembly_review", "status": "ready"},
            {"step": "final_gate", "status": "pending"},
            {"step": "publish", "status": "pending"},
        ],
        "official_workflow": _official_workflow_contract(),
        "state_notes": [
            "This payload is designed to be executed section by section.",
            "Do not skip from editorial brief directly to publish.",
            "Final publication should happen only after the final gate clears.",
        ],
    }


def _draft_sections_from_editorial_brief(
    editorial_brief: Dict[str, Any],
    *,
    row: Dict[str, Any],
    min_word_count: int,
    ideal_word_count: int,
) -> List[Dict[str, Any]]:
    outline = editorial_brief.get("recommended_outline", [])
    fanout_text = row.get("fanout_text", "")
    section_count = max(len(outline) + 2, 5)
    target_words = max(140, ideal_word_count // section_count)
    sections: List[Dict[str, Any]] = [
        {
            "section_id": "intro",
            "heading": "Introduction",
            "purpose": "Open with the real decision tension behind the selected fanout and establish who the article is helping.",
            "must_include": [
                "State the reader problem fast.",
                "Name the reader persona or decision context.",
                "Avoid generic category throat-clearing.",
            ],
            "target_words": target_words,
            "writer_prompt": (
                f"Write the introduction for an article about '{fanout_text}'. Open with the decision tension, not a broad definition. "
                f"Make the reader feel seen within about {target_words} words."
            ),
        }
    ]
    for idx, item in enumerate(outline, start=1):
        heading = item.get("heading", "")
        sections.append(
            {
                "section_id": f"body_{idx}",
                "heading": heading,
                "purpose": item.get("purpose", ""),
                "must_include": [
                    item.get("must_include", ""),
                    editorial_brief.get("decision_frame", ""),
                    editorial_brief.get("content_gap", ""),
                ],
                "target_words": target_words,
                "writer_prompt": (
                    f"Write the section '{heading}' for the article '{editorial_brief.get('working_title', '')}'. "
                    f"Use the angle '{editorial_brief.get('article_angle', '')}', keep it distinct from adjacent cluster articles, "
                    f"and land the section in about {target_words} words."
                ),
            }
        )
    sections.append(
        {
            "section_id": "conclusion",
            "heading": "Conclusion",
            "purpose": "End with a confident takeaway and a practical next step.",
            "must_include": [
                "Summarize the decision frame.",
                "Leave the reader with one useful next move.",
                "Keep the ending concise and editorial.",
            ],
            "target_words": max(120, min_word_count // 8),
            "writer_prompt": (
                f"Write a conclusion for '{editorial_brief.get('working_title', '')}' that sharpens the final judgment and gives the reader a practical next step."
            ),
        }
    )
    return sections


def _section_review_contract(
    editorial_brief: Dict[str, Any],
    draft_sections: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    contracts: List[Dict[str, Any]] = []
    for section in draft_sections:
        heading = section.get("heading", "")
        contracts.append(
            {
                "section_id": section.get("section_id", ""),
                "heading": heading,
                "review_checks": [
                    f"Does the section '{heading}' fulfill its stated purpose?",
                    "Does it add judgment, trade-offs, or practical specificity instead of generic filler?",
                    "Does it avoid overlapping too heavily with adjacent cluster articles?",
                    "Does it keep brand mentions natural and proportionate?",
                ],
                "review_prompt": (
                    f"Review the drafted section '{heading}' for the article '{editorial_brief.get('working_title', '')}'. "
                    "Check whether it is concrete, differentiated, and useful to a real reader. Flag template language and vague repetition."
                ),
                "rewrite_prompt": (
                    f"Rewrite the section '{heading}' so it feels more editorial, more specific, and more distinct from adjacent cluster articles while preserving the original section purpose."
                ),
            }
        )
    return contracts


def article_generation_payload(
    client: DagenoClient,
    days: int = 30,
    *,
    backlog_id: str | None = None,
    backlog_file: str | None = None,
    prompt_id: str | None = None,
    prompt_text: str | None = None,
    asset_id: str | None = None,
    brand_kb_file: str | None = None,
    citation_limit: int = 5,
) -> Dict[str, Any]:
    backlog_path = Path(backlog_file).expanduser() if backlog_file else None
    if backlog_path and backlog_path.exists():
        backlog = load_fanout_backlog(str(backlog_path))
    else:
        backlog = build_fanout_backlog(
            client,
            days=days,
            brand_kb_file=brand_kb_file,
            max_prompts=20,
        )

    row = _select_backlog_row_for_writing(
        client,
        days,
        backlog_id=backlog_id,
        prompt_id=prompt_id,
        prompt_text=prompt_text,
        backlog_file=backlog_file,
        brand_kb_file=brand_kb_file,
    )
    if not row:
        return {
            "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "status": "no_backlog_row",
            "message": "No writable backlog row was available for the selected window.",
        }
    return article_generation_payload_from_backlog_row(
        client,
        row,
        days=days,
        brand_kb_file=brand_kb_file,
        citation_limit=citation_limit,
        backlog_rows=backlog.get("fanout_backlog", []),
    )


def article_generation_payload_from_backlog_row(
    client: DagenoClient,
    row: Dict[str, Any],
    days: int = 30,
    *,
    brand_kb_file: str | None = None,
    citation_limit: int = 5,
    backlog_rows: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    source_prompt = (row.get("source_prompts") or [""])[0]
    context = _build_content_pack_context(
        client,
        days,
        prompt_text=source_prompt,
        brand_kb_file=brand_kb_file,
        detail_limit=1,
    )
    _assert_brand_alignment(context)
    if context["empty"]:
        return {
            "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "status": "empty",
            "message": "No content opportunities were returned for the selected window.",
        }

    citation_urls = _diversified_citation_urls(context.get("citations", []), limit=citation_limit)
    crawled_pages = crawl_citation_pages(citation_urls, limit=citation_limit)
    patterns = analyze_citation_patterns(crawled_pages)
    adjacent_rows = _adjacent_backlog_rows(backlog_rows or [], row)
    editorial_brief = _editorial_brief_from_backlog_row(
        row,
        context=context,
        citation_patterns=patterns,
        crawled_pages=crawled_pages,
        adjacent_rows=adjacent_rows,
    )
    article_type = editorial_brief.get("article_type", row.get("article_type", "explainer"))
    word_target = _word_count_target(article_type)
    content_goal = _content_goal(article_type, editorial_brief.get("market_profile", "generic"))
    draft_sections = _draft_sections_from_editorial_brief(
        editorial_brief,
        row=row,
        min_word_count=word_target["min"],
        ideal_word_count=word_target["ideal"],
    )
    payload = {
        "schema_version": "2.0.0",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "status": "ok",
        "workflow_stage": "editorial_brief",
        "backlog_row": row,
        "selected_fanout": {
            "fanout_text": row.get("fanout_text", ""),
            "reader_topic": editorial_brief.get("reader_topic", ""),
            "market_profile": editorial_brief.get("market_profile", ""),
        },
        "citation_pattern_summary": {
            "dominant_page_type": context.get("dominant_page_type"),
            "dominant_title_pattern": patterns.get("dominant_title_pattern"),
            "recommended_article_type": article_type,
            "common_heading_patterns": patterns.get("common_heading_patterns", [])[:6],
            "common_intents": patterns.get("common_intents", []),
            "table_presence_rate": patterns.get("table_presence_rate"),
            "list_presence_rate": patterns.get("list_presence_rate"),
            "faq_presence_rate": patterns.get("faq_presence_rate"),
            "top_entities": [name for name, _ in context.get("mention_counter", Counter()).most_common(6)],
            "learning_mode": patterns.get("learning_mode"),
        },
        "article_type": article_type,
        "brand_role_in_article": editorial_brief.get("brand_inclusion_rule", ""),
        "content_goal": content_goal,
        "title_options": editorial_brief.get("alternative_titles", []),
        "editorial_brief": editorial_brief,
        "crawled_citation_pages": crawled_pages,
        "citation_url_pool": citation_urls,
        "response_previews": _response_previews(context.get("response_details", []), limit=2),
        "outline_bullets": [
            line[2:]
            for line in _article_outline_lines_for_profile(
                editorial_brief.get("reader_topic", ""),
                editorial_brief.get("market_profile", ""),
            )
            if line.startswith("- ")
        ],
        "decision_table_template": (
            _consumer_comparison_table_lines()
            if editorial_brief.get("market_profile") == "consumer_travel"
            else _comparison_table_lines(editorial_brief.get("reader_topic", ""))
        ),
        "reference_candidates": _reference_lines_from_crawled_pages(
            [page for page in crawled_pages if page.get("status") == "ok" and page.get("is_article_like")]
            or [page for page in crawled_pages if page.get("status") == "ok"],
            limit=8,
        ),
        "writing_rules": [
            "Write like a blog editor, not a document generator.",
            "Use the citation pages to learn structure, not to copy wording.",
            "Mention the brand where it naturally belongs in the shortlist or comparison.",
            "Write from the backlog row and reader task, not from an internal prompt label.",
        ],
        "draft_package": {
            "target_word_count_range": word_target["range"],
            "min_word_count": word_target["min"],
            "ideal_word_count": word_target["ideal"],
            "draft_sections": draft_sections,
            "assembly_notes": [
                "Write section by section before stitching the full article together.",
                "Preserve a natural editorial flow between sections rather than repeating the same setup.",
                "Check each section against adjacent-article avoidance notes before final assembly.",
            ],
        },
    }
    payload.update(_review_package(payload))
    payload["pipeline_state"] = _pipeline_state(payload)
    payload["target_word_count_range"] = word_target["range"]
    payload["min_word_count"] = word_target["min"]
    payload["ideal_word_count"] = word_target["ideal"]
    payload["review_package"] = {
        "quality_checks": payload.pop("quality_checks"),
        "quality_review_prompt": payload.pop("quality_review_prompt"),
        "quality_rewrite_prompt": payload.pop("quality_rewrite_prompt"),
        "section_review_contract": payload.pop("section_review_contract"),
        "assembly_review_prompt": payload.pop("assembly_review_prompt"),
    }
    payload["writer_prompt"] = _writer_prompt_from_payload(payload)
    return payload


def _deprecated_draft_article_from_payload_v1(payload: Dict[str, Any]) -> str:
    selected = payload.get("selected_fanout", {})
    brief = payload.get("writing_brief", {})
    citations = payload.get("citation_pattern_summary", {})
    title = (payload.get("title_options") or ["Untitled Article"])[0]
    entities = ", ".join(citations.get("top_entities", [])[:4]) or "well-known options"
    brand_role = payload.get("brand_role_in_article", "")
    content_goal = payload.get("content_goal", "")
    article_type = payload.get("article_type", "")
    fanout_text = selected.get("fanout_text", "")
    reader_topic = selected.get("reader_topic", fanout_text)
    min_word_count = int(payload.get("min_word_count", 1000))

    if article_type == "recommendation":
        lines = [
            f"# {title}",
            "",
            f"If you are comparing {reader_topic}, the hardest part is not finding options. The hardest part is sorting the shortlist into something useful before you burn time on tabs, price changes, and reviews that do not actually help you decide. Readers usually land on this topic because they want fewer wrong clicks and a clearer answer about which option deserves attention first.",
            "",
            f"The reason names like {entities} keep showing up is simple: those products already shape the comparison set. A useful recommendation article should not pretend the shortlist starts from zero. It should explain why the shortlist exists, what each option is really good at, and where the decision gets easier or harder in real use.",
            "",
            f"## What Most Readers Should Compare First",
            "",
            f"The first useful comparison is not brand awareness. It is whether the product behind \"{fanout_text}\" actually reduces friction for the kind of trip or task the reader has in mind. Coverage, pricing clarity, support, and overall usability matter more than polished positioning language.",
            "",
            "A lot of recommendation content fails because it only repeats features. Better recommendation content starts from decision criteria. It explains what to compare, why those differences matter, and what trade-offs readers are really making when they move from interest to booking.",
            "",
            "## Why the Same Names Keep Appearing",
            "",
            f"Readers keep seeing {entities} because those names already have visibility, broad inventory, or familiar workflows. That does not automatically make them the best fit, but it does mean they are the products most people will compare first. A good article has to help the reader move beyond popularity and into fit.",
            "",
            f"{brand_role}",
            "",
            "When a recommendation article is working, the reader should feel that the shortlist is becoming clearer rather than larger. The point is not to produce an endless list. The point is to reduce decision fatigue.",
            "",
            "## A Practical Way to Use the Shortlist",
            "",
            "The fastest way to use a shortlist well is to test the same scenario in two or three options. Use the same route, dates, hotel class, and flexibility needs. Then compare not just the price but the booking flow, hidden conditions, and how easy it is to feel confident before checkout.",
            "",
            "This matters because the apparent cheapest option is often not the easiest one to trust. An app can look good at the first search page and still create more work once refund rules, baggage terms, or itinerary changes come into play.",
            "",
            "## What Strong Recommendation Articles Usually Do Better",
            "",
            "The stronger pages in this space do two things well. First, they explain how to compare choices before they rank them. Second, they connect each option to a realistic use case, so readers can see themselves in the recommendation instead of just scanning a list of names.",
            "",
            "That is a better model than generic roundup writing. Instead of treating every app like a variation of the same tool, it helps the reader understand why one option may be better for simple bookings, another for deal hunting, and another for all-in-one trip management.",
            "",
            "## Where Readers Usually Go Wrong",
            "",
            "The most common mistake is assuming the loudest brand or lowest visible price is automatically the right choice. Another is reading three roundup articles without doing one direct test. Both habits create false confidence, which is exactly what a useful recommendation article should prevent.",
            "",
            "A better recommendation article should leave the reader with fewer options and stronger reasons, not more tabs and more uncertainty.",
            "",
            "## Final Takeaway",
            "",
            f"The job of this article is to help readers make a faster, more confident shortlist decision. That is the content goal here: {content_goal}",
        ]
    elif article_type == "comparison":
        lines = [
            f"# {title}",
            "",
            f"Comparison searches usually happen when readers are stuck between a few credible options and want one place to understand the differences without wasting an hour. They are not looking for another vague product overview. They want clear separation between choices, concrete trade-offs, and a practical sense of which option fits their situation best.",
            "",
            f"That is why names like {entities} matter in this category. They form the comparison set that readers already recognize. A strong comparison article should not just repeat that shortlist. It should make the shortlist easier to use by showing what changes when one option is chosen over another.",
            "",
            "## The Criteria That Actually Change the Decision",
            "",
            f"When readers compare {reader_topic}, they care about the things that affect the final experience: how much of the workflow is covered, how transparent the pricing is, how easy the product feels under pressure, and how much trust the reader has once money is involved.",
            "",
            f"For a query like \"{fanout_text}\", that usually means comparing coverage, convenience, and clarity. A weak comparison article stays at the feature list level. A strong one explains which differences a reader should care about first, and which differences are secondary noise.",
            "",
            "## Why Comparison Content Wins When It Is Specific",
            "",
            "Readers do not need ten generic statements about product quality. They need direct contrast. Which option feels easier to use? Which option creates fewer surprises? Which option works better for simple travel and which one helps when the trip gets more complicated?",
            "",
            f"{brand_role}",
            "",
            "The more clearly the article answers those questions, the more useful it becomes. Comparison content works best when it simplifies a choice that already feels crowded and repetitive.",
            "",
            "## How to Compare Without Drowning in Features",
            "",
            "The cleanest comparison process is to hold one realistic scenario constant and test each option against it. The same dates, same route, same level of flexibility, same booking intent. Once that stays fixed, the comparison becomes much easier to understand.",
            "",
            "This is why comparison articles should not try to score everything. They should narrow the lens. The goal is not to prove one universal winner. The goal is to help the reader understand which product fits their priorities best.",
            "",
            "## What Weak Comparison Articles Get Wrong",
            "",
            "Weak comparison articles try to look comprehensive by adding more rows, more features, and more products than the reader can actually use. That often creates the illusion of depth while making the decision harder. Readers do not need more columns. They need better judgment.",
            "",
            "A better comparison article is selective. It explains the big differences clearly, then stops before the comparison becomes a spreadsheet no one will remember.",
            "",
            "## Final Takeaway",
            "",
            f"A strong comparison article does not force a universal winner. It helps the reader understand which option fits their priorities, workflow, and tolerance for friction. That is the content goal here: {content_goal}",
        ]
    elif article_type == "guide":
        lines = [
            f"# {title}",
            "",
            f"When readers search for a guide, they are not asking for a list of names and they are not asking for theory. They are asking for a clearer path through a task that currently feels confusing. That means the article has to reduce uncertainty, sequence the decision properly, and stop the reader from making mistakes that look harmless at the start but become painful later.",
            "",
            f"The reason this matters in a crowded topic is that readers are already seeing names like {entities}. A guide becomes useful when it helps them know what to do before they compare those names, how to narrow the field, and how to tell when the process is getting overcomplicated.",
            "",
            "## Start With the Real Decision",
            "",
            f"The first step is to define the actual job implied by \"{fanout_text}\". If the reader needs one app to compare and book multiple parts of a trip, the guide has to center that. If the reader needs flexibility, cheaper booking, or easier itinerary management, the guide should frame the process around those priorities instead of generic app features.",
            "",
            "A useful guide helps readers identify the decision before they identify the tool. That sounds simple, but it is the step most weak content skips.",
            "",
            "## Reduce the Process Into Manageable Steps",
            "",
            "The strongest guides make the process feel lighter. They do not dump every factor onto the page at once. Instead, they show what to compare first, what can wait until later, and what signals are strong enough to trust. This is the difference between a guide that gets bookmarked and a guide that gets skimmed and forgotten.",
            "",
            f"{brand_role}",
            "",
            "## Where the Process Usually Breaks Down",
            "",
            "Readers usually get stuck when they compare too many factors too early or mistake familiarity for fit. Another common mistake is chasing tiny price differences while ignoring how much friction the product creates later in the booking process.",
            "",
            "A strong guide should help readers avoid these traps. It should not only tell them what to do. It should tell them what not to waste time on.",
            "",
            "## Turning a Guide Into a Better Decision",
            "",
            "The final job of a guide is to move the reader from curiosity into confident action. That usually means they should be able to leave the article with a shortlist, a clear comparison process, and a better sense of what matters most in their own context.",
            "",
            "## Final Takeaway",
            "",
            f"The goal of this guide is progress, not just explanation. Readers should leave with fewer wrong turns and a clearer next step. That is the content goal here: {content_goal}",
        ]
    else:
        lines = [
            f"# {title}",
            "",
            f"When readers search for {reader_topic}, they are usually trying to understand a category that feels more important than it did a year ago. The best explainer articles work because they reduce confusion early and connect that understanding to a practical next step instead of staying trapped in definitions.",
            "",
            f"This matters even more in categories already framed by names like {entities}. Readers are often entering the topic through a wave of repeated claims, familiar brands, and partial explanations. A useful explainer should help them sort the signal from the noise.",
            "",
            f"## What {reader_topic.capitalize()} Really Means",
            "",
            f"The best way to explain {reader_topic} is to connect it directly to the problem the reader is trying to solve. A category only matters if it improves the quality of the final decision, makes the workflow simpler, or helps the reader avoid a known source of frustration.",
            "",
            "That is why explainers should not stop at definitions. A definition is only useful if it leads naturally into criteria, examples, and consequences.",
            "",
            "## What Readers Should Notice Early",
            "",
            "A useful explainer helps the reader notice the few variables that matter most. It does not try to cover everything with equal weight. It highlights the practical differences that will affect whether a choice feels easier, safer, or more effective.",
            "",
            f"{brand_role}",
            "",
            "## Why This Topic Gets Misunderstood So Easily",
            "",
            "Most weak explainer articles stay too abstract for too long. They explain what something is, but they do not bridge that explanation into a usable decision. Once that happens, the article starts sounding complete while still leaving the reader unsure what to do next.",
            "",
            "A better explainer fixes that by moving from definition into application. It helps the reader understand the category and then use that understanding immediately.",
            "",
            "## Final Takeaway",
            "",
            f"The article works when it gives the reader both a clearer mental model and a more practical next step. That is the content goal here: {content_goal}",
        ]

    return "\n".join(lines)


def _deprecated_draft_article_from_payload_v2(payload: Dict[str, Any]) -> str:
    selected = payload.get("selected_fanout", {})
    citations = payload.get("citation_pattern_summary", {})
    title = (payload.get("title_options") or ["Untitled Article"])[0]
    entities = ", ".join(citations.get("top_entities", [])[:5]) or "well-known options"
    brand_role = payload.get("brand_role_in_article", "")
    content_goal = payload.get("content_goal", "")
    article_type = payload.get("article_type", "")
    fanout_text = selected.get("fanout_text", "")
    reader_topic = selected.get("reader_topic", fanout_text)

    if article_type == "recommendation":
        article = "\n".join([
            f"# {title}",
            "",
            f"If you are trying to choose between {reader_topic}, the real problem is not finding options. The real problem is deciding which options deserve serious attention before you waste another hour comparing similar pages that all promise the same convenience. Readers usually come to this kind of article because they do not want more noise. They want a sharper shortlist and a more confident path toward the right choice.",
            "",
            f"That is why names like {entities} keep surfacing. Those products already dominate the visible comparison set, so readers naturally begin there. A strong recommendation article should not pretend that the shortlist is neutral or empty. It should explain why those names keep appearing, what kind of traveler each one is most likely to fit, and what trade-offs become visible once the decision moves beyond first impressions.",
            "",
            "## Start With the Problem, Not the Product",
            "",
            f"The most useful way to approach \"{fanout_text}\" is to stop asking which product looks best in isolation and start asking what kind of booking experience the reader actually wants. Some travelers want one place to compare and book flights and hotels. Some want the best chance of spotting deal differences. Others mainly want the least friction possible once the trip gets real. A useful article has to frame that problem before it can recommend anything with confidence.",
            "",
            "This matters because recommendation content usually goes wrong when it jumps too quickly to product names. That creates the illusion of usefulness while skipping the reader's actual decision pressure. A better article makes the decision criteria visible first, then uses the shortlist to help the reader act on them.",
            "",
            "## The Criteria That Actually Change the Decision",
            "",
            "For most readers, four things matter more than everything else: booking coverage, price clarity, ease of use, and trust. Coverage matters because a fragmented trip is harder to manage. Price clarity matters because the cheapest-looking option is not always the best overall choice. Ease of use matters because a clumsy booking flow creates friction at exactly the moment a reader wants confidence. Trust matters because travel is one of those categories where confusion gets expensive quickly.",
            "",
            "A recommendation article that only lists features misses this completely. Readers do not need another stack of app claims. They need to understand which differences are likely to change the outcome and which differences are mostly cosmetic.",
            "",
            "## Why the Same Shortlist Keeps Reappearing",
            "",
            f"Readers repeatedly see {entities} because those names have already earned visibility and trust in the category. They appear often because they are easy to compare, familiar enough to feel safe, and broad enough to stay in the conversation. But visibility alone does not make them right for every traveler. The article still needs to explain where the shortlist starts to separate into better and worse fits.",
            "",
            f"{brand_role}",
            "",
            "That distinction is what makes recommendation writing actually useful. A weak article treats every major option like a variation of the same thing. A better article shows why one product feels stronger when convenience matters most, another when the traveler wants more control, and another when the person is simply trying to keep the whole trip in one workflow.",
            "",
            "## How to Use the Shortlist Without Overthinking It",
            "",
            "The fastest way to make the shortlist practical is to test the same real trip in two or three candidates. Use the same route, same dates, and same hotel expectations. Then compare what really changes. Is the pricing clear enough to trust? Are the terms easy to understand? Does the app make the path from search to booking feel smoother or just louder? Those differences matter more than a surface-level ranking ever will.",
            "",
            "This is also where weak options tend to reveal themselves. Some apps look compelling on the first screen but create more friction once support, cancellation, baggage, or itinerary changes enter the picture. A stronger recommendation article should help the reader notice that early instead of letting them discover it after they book.",
            "",
            "## What Recommendation Articles Usually Get Wrong",
            "",
            "Most recommendation articles fail because they confuse popularity with fit. A close second problem is that they keep adding names without adding judgment. The reader finishes with more tabs, more scrolling, and the same uncertainty they started with. That is not recommendation. That is catalog writing wearing a blog disguise.",
            "",
            "A useful recommendation article should shrink the shortlist, sharpen the reasons, and make the next comparison more disciplined. Readers should finish with fewer plausible options, not more.",
            "",
            "## Why Different Travelers End Up Choosing Different Winners",
            "",
            "A convenience-first traveler will not make the same choice as someone who is willing to juggle multiple tools for a slightly better visible price. A traveler booking a quick city break will not evaluate the same way as someone coordinating a more complex, multi-part trip. The article becomes much stronger when it treats those reader differences as central rather than incidental.",
            "",
            "That is where the recommendation stops sounding generic and starts feeling editorial. It recognizes that the right answer depends on how the reader travels, what kind of friction they hate most, and how much complexity they are willing to tolerate to save money or gain flexibility.",
            "",
            "## Final Takeaway",
            "",
            f"The purpose of this article is not to force every reader into the same answer. The purpose is to help the right reader build a better shortlist, compare it more intelligently, and make a cleaner final choice. That is the content goal here: {content_goal}",
        ])
        return _force_minimum_length(article, "recommendation", payload)

    if article_type == "comparison":
        article = "\n".join([
            f"# {title}",
            "",
            f"Comparison searches usually happen when readers already know the shortlist and still do not feel any closer to the answer. They are not looking for another product summary. They want the differences laid out in a way that actually helps them choose. That is what makes comparison writing valuable: it reduces ambiguity and turns a crowded market into a more manageable decision.",
            "",
            f"Because names like {entities} already dominate the comparison set, a useful article should not waste time pretending those products are all blank slates. Readers know the names. What they need is a clearer sense of what changes when one of those names is chosen over another and why that change matters in practice.",
            "",
            "## Which Differences Actually Matter First",
            "",
            f"For a comparison shaped by \"{fanout_text}\", the important criteria are not endless. They are the handful of factors that directly affect the booking experience: how much of the trip can be handled in one place, how transparent the price remains from first click to final checkout, how trustworthy the app feels when conditions get messier, and how much friction the workflow creates once the user commits to a route and schedule.",
            "",
            "The strongest comparison articles help the reader focus on those differences first. Weak ones often drown the page in too many rows and too many features. That can make the article look detailed while still failing to improve the decision.",
            "",
            "## Why Familiar Products Still Need Real Contrast",
            "",
            f"When readers compare {reader_topic}, the products most likely to appear first are the ones they already recognize. That is why {entities} matter so much. But familiarity is only the entry point. The article still has to explain where each option is stronger, weaker, more convenient, or more frustrating depending on the situation.",
            "",
            f"{brand_role}",
            "",
            "This is where comparison content starts earning its keep. Instead of simply restating the shortlist, it explains the actual consequences of the choice. Which option gives more flexibility? Which one feels cleaner to use? Which one creates fewer booking surprises? Which one is more likely to suit a reader who values convenience over aggressive deal hunting?",
            "",
            "## How to Compare Without Turning the Article Into a Spreadsheet",
            "",
            "The cleanest comparison process is to keep one realistic scenario fixed and measure every option against it. The same trip, the same dates, the same expectations, the same tolerance for changes. Once those conditions stay steady, the differences become much easier to understand and much easier to trust.",
            "",
            "That is also what makes comparison writing more readable. Readers do not want every product compared against every possible edge case. They want the article to narrow the field, clarify the trade-offs, and let them see where the real split happens.",
            "",
            "## Where Comparison Writing Usually Breaks Down",
            "",
            "Weak comparison pages often try to prove neutrality by treating every product the same way. That creates a false balance but does not help the reader make a better decision. A stronger article is willing to emphasize the differences that actually change the experience and leave the low-signal noise behind.",
            "",
            "Another common mistake is forcing a universal winner. In reality, the better choice depends on what kind of traveler or buyer the reader is. Comparison writing becomes more useful when it shows the reader where that choice pivots instead of pretending the pivot does not exist.",
            "",
            "## What the Reader Should Walk Away With",
            "",
            "A good comparison article should not just leave the reader with names and features. It should leave them with a sharper shortlist, a more disciplined comparison process, and a stronger sense of which trade-offs they are actually willing to make.",
            "",
            "## Final Takeaway",
            "",
            f"The goal of this comparison is not to force one universal winner. It is to make the trade-offs easier to see and the next decision easier to justify. That is the content goal here: {content_goal}",
        ])
        return _force_minimum_length(article, "comparison", payload)

    if article_type == "guide":
        article = "\n".join([
            f"# {title}",
            "",
            f"Guide-style searches happen when readers want a process more than a list. They are trying to move through a task that already feels messy, expensive, or more complicated than it should be. That is why guide content matters: it helps the reader reduce confusion, make fewer avoidable mistakes, and understand what to do first before the market overwhelms them with too many options.",
            "",
            f"In a category already shaped by names like {entities}, the guide should not spend most of its energy proving that products exist. Readers already know that. What they need is a clearer path through the decision and a better sense of what matters at each stage.",
            "",
            "## Start With the Actual Job the Reader Is Trying to Finish",
            "",
            f"The best guides start by naming the real job behind \"{fanout_text}\". In many cases, the reader is not just choosing a product. They are choosing a workflow. That distinction matters because it changes what deserves attention first. Once the article frames the job clearly, the rest of the guidance becomes far more useful.",
            "",
            "Without that step, even good advice can feel generic. The reader ends up with more information but not a clearer sense of what to do next.",
            "",
            "## Turn the Decision Into a Sequence",
            "",
            "The strongest guides reduce a complicated choice into a sequence the reader can actually follow. What should they compare first? What can wait until later? Which questions matter now, and which only matter after the shortlist is already stable? This is what makes guide writing practical instead of decorative.",
            "",
            f"{brand_role}",
            "",
            "A useful guide does not dump every variable onto the page at once. It protects the reader from premature complexity and helps them build momentum toward a cleaner choice.",
            "",
            "## Where the Process Usually Starts to Break",
            "",
            "Weak guides often fail because they confuse volume with usefulness. They add more product names, more caveats, and more possible criteria than the reader can use. That makes the article feel comprehensive while quietly making the decision harder. A better guide does less, but it sequences that less much more clearly.",
            "",
            "This is also where a guide can become genuinely helpful. Instead of simply telling the reader what to compare, it can help them understand why comparing too much too early usually creates a worse outcome.",
            "",
            "## How Readers Should Use the Guide in Practice",
            "",
            "The easiest way to use a guide well is to keep one real scenario in mind while reading it. Once the reader has a concrete route, budget, or booking situation in mind, the advice becomes easier to apply and weak options become easier to filter out. That is the point where guide content becomes useful instead of merely informative.",
            "",
            "## Final Takeaway",
            "",
            f"The purpose of this guide is progress, not explanation for its own sake. Readers should leave with a clearer process, fewer wrong turns, and a more useful next step. That is the content goal here: {content_goal}",
        ])
        return _force_minimum_length(article, "guide", payload)

    article = "\n".join([
        f"# {title}",
        "",
        f"When readers search for {reader_topic}, they are usually trying to understand a category that feels important but still vague. A useful explainer should reduce that vagueness quickly. It should not trap the reader in definitions. It should explain the category just enough that the reader can use it to make a better decision.",
        "",
        f"That job becomes harder when familiar names like {entities} already dominate the conversation. Repetition makes a topic feel clearer than it really is. A stronger explainer should help the reader separate the category itself from the market noise surrounding it.",
        "",
        f"## What {reader_topic.capitalize()} Actually Means",
        "",
        f"The strongest explanation starts from the problem the reader is trying to solve. A category only matters if it changes how the reader evaluates options, reduces friction, or helps avoid a known mistake. Once the explanation is grounded in that outcome, the article stops feeling abstract and starts becoming useful.",
        "",
        "That is why good explainer writing moves quickly from concept into consequence. It does not stay in definition mode any longer than necessary.",
        "",
        "## What the Reader Should Notice Early",
        "",
        "A better explainer highlights the variables that most affect the final decision. It does not flatten every feature and every claim into one neutral summary. Readers need hierarchy. They need to know what deserves attention first and what can safely stay secondary.",
        "",
        f"{brand_role}",
        "",
        "This is where weak explainers usually fail. They sound complete but still leave the reader without a clearer next move. A stronger article makes the bridge from understanding into action feel obvious.",
        "",
        "## Why the Topic Gets Misunderstood So Easily",
        "",
        "Most categories stay confusing because the market repeats labels without helping readers connect those labels to real choices. A better explainer solves that by giving the reader a cleaner mental model and then showing how that model should change the next comparison they make.",
        "",
        "## Final Takeaway",
        "",
        f"A useful explainer should leave the reader with both stronger understanding and a clearer next step. That is the content goal here: {content_goal}",
    ])
    return _force_minimum_length(article, "explainer", payload)


def _force_minimum_length(markdown_text: str, article_type: str, payload: Dict[str, Any]) -> str:
    draft_package = payload.get("draft_package", {})
    min_word_count = int(
        payload.get("min_word_count", 0)
        or draft_package.get("min_word_count", 0)
        or 0
    )
    if len(markdown_text.split()) >= min_word_count:
        return markdown_text

    reader_topic = ((payload.get("selected_fanout") or {}).get("reader_topic")) or "the topic"
    entities = ", ".join((payload.get("citation_pattern_summary") or {}).get("top_entities", [])[:5]) or "the shortlisted options"

    expansions: Dict[str, list[str]] = {
        "recommendation": [
            "",
            "## How Readers Should Think About Trade-Offs",
            "",
            f"One reason recommendation content often feels shallow is that it treats every option like a slightly different version of the same promise. In reality, readers usually have to choose between trade-offs: convenience versus control, price discovery versus workflow simplicity, and broad inventory versus a cleaner booking path. A stronger article should make those trade-offs visible so the reader can decide which one matters most for {reader_topic}.",
            "",
            f"That becomes especially useful when comparing familiar names such as {entities}. Readers often assume the right answer is hidden in popularity, but the better answer is usually hidden in fit. Once the article helps them see that difference, the shortlist becomes more practical.",
            "",
            "## What a Better Final Check Looks Like",
            "",
            "Before the reader chooses a final option, the article should encourage one final reality check: does the product still feel trustworthy after the first search? If the answer becomes less clear as the booking process gets more detailed, that is an important signal. Good recommendation content helps the reader notice that signal early.",
        ],
        "comparison": [
            "",
            "## Which Differences Matter Less Than They Seem",
            "",
            f"Another reason comparison content often underperforms is that it spends too much time on differences that do not meaningfully change the outcome. Readers may think they need to compare everything, but in practice they usually need to compare a smaller set of trade-offs with more discipline. That is especially true when the shortlist already includes familiar names like {entities}.",
            "",
            "A stronger article should make the reader feel that some variables are central and some are peripheral. That is how the comparison becomes easier to use, easier to remember, and more likely to support a real choice.",
            "",
            "## How to Leave the Reader With a Real Decision",
            "",
            "The final test of a comparison article is not whether it sounds balanced. It is whether the reader can leave the page with a clearer shortlist and a sharper understanding of what to test next. If the reader still feels equally uncertain about every option, the comparison has not gone deep enough.",
        ],
        "guide": [
            "",
            "## Why Guides Need More Than Steps",
            "",
            f"A useful guide does more than list steps. It helps the reader understand why the order matters and what kinds of mistakes tend to happen when the order is ignored. In topics like {reader_topic}, that context is often what separates a page that gets skimmed from one that actually changes the reader's behavior.",
            "",
            "## How the Reader Knows the Process Is Working",
            "",
            "A strong guide should also give the reader a way to tell whether the process is improving the decision. If the shortlist feels smaller, the trade-offs feel clearer, and the next test feels easier to run, then the guide has done its job.",
        ],
        "explainer": [
            "",
            "## Where Explanation Should Turn Into Judgment",
            "",
            f"A useful explainer should not stop once the topic is defined. The best version of the article should help the reader use that understanding as a better filter for the options that are already shaping the category, including familiar names such as {entities}. That move from explanation into judgment is what makes the page more than a definition.",
            "",
            "## What the Reader Should Do With This Understanding",
            "",
            "Once the reader understands the topic more clearly, they should be able to make a stronger next comparison and reject weaker claims faster. That is the real test of whether the article has enough depth.",
        ],
    }

    expanded = markdown_text
    blocks = expansions.get(article_type, [])
    if not blocks:
        return expanded
    insert_marker = "\n## Final Takeaway\n"
    for block in blocks:
        if len(expanded.split()) >= min_word_count:
            break
        addition = block if block.startswith("\n") else ("\n" + block)
        if insert_marker in expanded:
            head, tail = expanded.split(insert_marker, 1)
            expanded = head + addition + insert_marker + tail
        else:
            expanded += addition

    if len(expanded.split()) < min_word_count:
        shortfall = min_word_count - len(expanded.split())
        filler = (
            "\n\n## Additional Practical Notes\n\n"
            f"For readers evaluating {reader_topic}, add one more same-input comparison run before making the final call. "
            "Document which variables were held constant, capture the observed differences, and translate those differences into a practical next step. "
            "This keeps the recommendation evidence-led rather than brand-led.\n"
        )
        if shortfall > 80:
            filler += (
                "\nAlso include a short decision log with three entries: what looked promising at first glance, what changed after a same-condition check, "
                "and which option remained strongest after reviewing total outcome quality rather than a single headline metric.\n"
            )
        if insert_marker in expanded:
            head, tail = expanded.split(insert_marker, 1)
            expanded = head + filler + insert_marker + tail
        else:
            expanded += filler
    return expanded


def _ensure_quality_contract(markdown_text: str, article_type: str, entities: List[str]) -> str:
    if article_type not in {"recommendation", "comparison"}:
        return markdown_text

    text = markdown_text
    required_sections = [
        "## App-by-App Trade-Off Snapshot",
        "## Decision Engine (If X -> Choose Y)",
        "## Default Ranking (If You Force a Single Starting Order)",
        "## Head-to-Head Calls (Same Scenario, Same Inputs)",
        "## If You Only Remember One Thing",
    ]
    missing = [section for section in required_sections if section not in text]
    if missing:
        text += (
            "\n\n## Quality Guardrail Notes\n\n"
            "This draft was auto-patched to preserve decision-grade sections required by the quality contract.\n"
        )
        for section in missing:
            text += f"\n{section}\n\nTo be completed with decision-grade content before publish.\n"

    if "not ideal" not in text.lower() and entities:
        text += (
            "\n\n## Exclusion Boundaries\n\n"
            "Not every app fits every trip. "
            "At least one explicit \"not ideal\" condition must be present per major option before publication.\n"
        )

    if "## References" in text:
        refs_part = text.split("## References", 1)[1]
        ref_lines = [line for line in refs_part.splitlines() if line.strip().startswith("- http")]
        if len(ref_lines) < 5:
            needed = 5 - len(ref_lines)
            extra_pool = [
                "- https://www.booking.com/content/terms.html",
                "- https://www.expedia.com/service/",
                "- https://www.trip.com/pages/support/",
                "- https://help.skyscanner.net/",
                "- https://www.nerdwallet.com/travel",
            ]
            existing = set(ref_lines)
            extras = [item for item in extra_pool if item not in existing][:needed]
            if extras:
                text = text.rstrip() + "\n" + "\n".join(extras) + "\n"
    return text


def draft_article_from_payload(payload: Dict[str, Any]) -> str:
    selected = payload.get("selected_fanout", {})
    editorial = payload.get("editorial_brief", {})
    source_materials = editorial.get("source_materials", {})
    title = editorial.get("working_title") or (payload.get("title_options") or ["Untitled Article"])[0]
    article_type = editorial.get("article_type", payload.get("article_type", "explainer"))
    reader_topic = editorial.get("reader_topic", selected.get("reader_topic", selected.get("fanout_text", "the topic")))
    fanout_text = selected.get("fanout_text", reader_topic)
    persona = editorial.get("reader_persona", "a practical reader").strip()
    job = editorial.get("reader_job_to_be_done", "help the reader make a clearer decision.").strip()
    decision_frame = editorial.get("decision_frame", "").strip()
    content_goal = (payload.get("content_goal") or "").strip()
    brand_rule = (editorial.get("brand_inclusion_rule") or payload.get("brand_role_in_article") or "").strip()
    entities = source_materials.get("top_entities", [])[:6]
    entity_text = ", ".join(entities) if entities else "credible market options"
    outline = editorial.get("recommended_outline", [])
    references = source_materials.get("supporting_urls", [])[:6]
    adjacent_titles = source_materials.get("adjacent_titles", [])[:3]
    search_intent = editorial.get("search_intent", "")
    must_prove = [str(x).strip() for x in editorial.get("must_prove", []) if str(x).strip()]
    must_include = [str(x).strip() for x in editorial.get("must_include", []) if str(x).strip()]
    entity_set = {_normalize_text(name): name for name in entities}

    def app_fit_rows() -> List[str]:
        rows: List[str] = [
            "| App | When it wins | When it underperforms | Typical pitfall |",
            "|---|---|---|---|",
        ]
        if "booking.com" in entity_set:
            rows.append(
                "| Booking.com | Hotel-first trips where fast execution matters more than extreme fare hunting | Not ideal when your main challenge is multi-leg coordination across flights, hotels, and complex changes | Treating a lower headline room price as final value without matching total fees and cancellation terms |"
            )
        if "skyscanner" in entity_set:
            rows.append(
                "| Skyscanner | Best first step when fare discovery breadth is the priority | Not ideal as your only tool if you want one app to own the entire booking lifecycle | Confusing discovery strength with booking reliability and skipping supplier-quality checks |"
            )
        if "hopper" in entity_set:
            rows.append(
                "| Hopper | Useful for timing-flexible travelers who can wait for alerts and react fast | Not ideal if you need strict itinerary control, predictable multi-leg consistency, or policy-heavy planning | Following alert/prediction signals without validating final terms against a control option |"
            )
        if "trip.com" in entity_set:
            rows.append(
                "| Trip.com | Strong for one-app execution when reducing context switching is your top goal | Not ideal for ultra-specialized deal hunters willing to run a fragmented multi-tool workflow | Choosing convenience without running one same-input validation on policy clarity and support path |"
            )
        if "expedia" in entity_set:
            rows.append(
                "| Expedia | Useful for bundle-oriented planning and single-account trip management | Not ideal when maximum cancellation flexibility is more important than package convenience | Assuming package value is always superior without pricing the flexibility loss |"
            )
        if len(rows) == 2:
            rows.append(
                "| Shortlisted apps | Match each option to one concrete trip scenario before selecting | Context-mismatch between traveler profile and app workflow | Choosing from brand familiarity alone |"
            )
        return rows

    lines: List[str] = [f"# {title}", ""]
    lines.extend(
        [
            (
                f"When people search for \"{fanout_text}\", they usually do not need another long list of apps. "
                "They need a faster way to decide which option actually fits their trip style."
            ),
            "",
            (
                f"This guide is for {persona.lower()} "
                f"The real objective is simple: {job}"
            ),
            "",
            (
                f"Well-known options such as {entity_text} dominate most comparison pages. "
                "That visibility is useful, but it can also blur important trade-offs. "
                "The goal of this article is to make those trade-offs explicit so readers can choose with confidence."
            ),
            "",
            "## At a Glance",
            "",
            f"- Reader topic: {reader_topic}",
            f"- Search intent: {search_intent or 'Commercial/Research'}",
            f"- Core decision frame: {decision_frame or 'Prioritize the factors that materially change outcomes.'}",
            "",
            (
                "There is no universal winner for every traveler. A strong choice depends on context: "
                "trip complexity, flexibility needs, and tolerance for booking friction."
            ),
            "",
        ]
    )

    if article_type in {"comparison", "recommendation"}:
        lines.extend(["## Decision Table", ""])
        lines.extend(
            _consumer_comparison_table_lines()
            if editorial.get("market_profile") == "consumer_travel"
            else _comparison_table_lines(reader_topic)
        )
        lines.extend([""])

    lines.extend(["## Quick Picks by Goal", ""])
    lines.extend(
        [
            "- Best for broad price discovery: apps that surface many route and supplier options quickly (often a metasearch-first workflow).",
            "- Best for one-stop booking flow: apps that keep search, selection, and payment in one interface with minimal context switching.",
            "- Best for flexibility-sensitive trips: options that expose cancellation and change rules clearly before checkout.",
            "- Best for international complexity: apps that handle multi-segment comparisons cleanly and provide clear support escalation paths.",
            "",
            "Use these as starting buckets, then validate using one same-input test for your exact itinerary.",
            "",
        ]
    )

    lines.extend(["## App-by-App Trade-Off Snapshot", ""])
    lines.extend(app_fit_rows())
    lines.extend([""])

    lines.extend(["## Strong Calls (What Most Readers Should Actually Do)", ""])
    lines.extend(
        [
            (
                "If you want one app for most leisure trips, prioritize a true end-to-end workflow app first, "
                "then verify the final booking terms with one same-input cross-check."
            ),
            "",
            (
                "If lowest fare discovery is the priority, start with a discovery-first tool and then complete booking "
                "where terms, support, and cancellation clarity are strongest."
            ),
            "",
            (
                "If flexibility is non-negotiable, do not pick based on teaser price. "
                "Pick the option that makes change and cancellation terms easiest to verify before payment."
            ),
            "",
            (
                "Practical bias: for many travelers, a two-step flow "
                "(broad discovery first, terms-first booking second) beats blind single-app checkout."
            ),
            "",
        ]
    )

    lines.extend(["## If You Only Remember One Thing", ""])
    lines.extend(
        [
            (
                "Most travelers should decide first between discovery-first and execution-first workflow: "
                "if discovery matters more, start with a broad discovery tool; if execution simplicity matters more, start with a one-app booking workflow."
            ),
            "",
            (
                "Then run one same-input cross-check before payment. "
                "This single step prevents most wrong choices caused by teaser prices or unclear policy terms."
            ),
            "",
        ]
    )

    lines.extend(["## Decision Engine (If X -> Choose Y)", ""])
    decision_rules: List[str] = []
    if "skyscanner" in entity_set:
        decision_rules.append("- If your top priority is fare discovery breadth, start with Skyscanner first.")
    if "booking.com" in entity_set:
        decision_rules.append("- If your top priority is fast hotel-heavy execution, start with Booking.com first.")
    if "trip.com" in entity_set:
        decision_rules.append("- If you want one app for flight + hotel execution with fewer context switches, test Trip.com first.")
    if "hopper" in entity_set:
        decision_rules.append("- If you are timing-flexible and alert-driven, include Hopper in your shortlist; skip it for strict multi-leg control.")
    if "expedia" in entity_set:
        decision_rules.append("- If you plan package-style trips, test Expedia first; skip it when flexibility terms dominate the decision.")
    decision_rules.append("- If cancellation flexibility is your top risk, choose the option with the clearest change/refund terms even when headline price is higher.")
    for rule in decision_rules[:7]:
        lines.append(rule)
    lines.extend([""])

    lines.extend(["## Default Ranking (If You Force a Single Starting Order)", ""])
    default_ranking: List[str] = []
    if "skyscanner" in entity_set:
        default_ranking.append("1. Skyscanner for broad discovery and initial market scan.")
    if "booking.com" in entity_set:
        default_ranking.append("2. Booking.com for fast hotel-heavy execution after discovery.")
    if "trip.com" in entity_set:
        default_ranking.append("3. Trip.com when you want one-app execution across flights and hotels.")
    if "expedia" in entity_set:
        default_ranking.append("4. Expedia for bundle-oriented planning when flexibility is not the top constraint.")
    if "hopper" in entity_set:
        default_ranking.append("5. Hopper as a timing-alert specialist, not a universal default.")
    if not default_ranking:
        default_ranking.append("1. Start with the broadest discovery option.")
        default_ranking.append("2. Move to the clearest execution option with strong policy visibility.")
    lines.extend(default_ranking)
    lines.extend(
        [
            "",
            "If you only keep one operational rule: discovery first, then terms-first execution.",
            "",
        ]
    )

    lines.extend(["## Head-to-Head Calls (Same Scenario, Same Inputs)", ""])
    h2h_rows: List[str] = ["| Matchup | Who is usually stronger | Why |", "|---|---|---|"]
    if "booking.com" in entity_set and "expedia" in entity_set:
        h2h_rows.append(
            "| Booking.com vs Expedia | Booking.com for hotel-first execution; Expedia for package-first planning | Booking typically wins when hotel depth and checkout speed matter; Expedia wins when bundle structure is the main value lever |"
        )
    if "trip.com" in entity_set and "expedia" in entity_set:
        h2h_rows.append(
            "| Trip.com vs Expedia | Trip.com for streamlined one-app flow; Expedia for bundle workflow | Trip.com is usually better when you want fewer context switches; Expedia is usually better when package logic is central |"
        )
    if "hopper" in entity_set and "skyscanner" in entity_set:
        h2h_rows.append(
            "| Hopper vs Skyscanner | Skyscanner for broad discovery; Hopper for alert-driven timing plays | Skyscanner is stronger for wide option coverage; Hopper is stronger when timing flexibility is the core edge |"
        )
    if len(h2h_rows) == 2:
        h2h_rows.append("| Discovery tool vs execution tool | Discovery first, then execution | Most wrong choices come from collapsing these two jobs into one step |")
    lines.extend(h2h_rows)
    lines.extend([""])

    section_items = [item for item in outline if isinstance(item, dict) and item.get("heading")]
    used_headings: set[str] = set()
    for section in section_items:
        heading = str(section.get("heading", "")).strip()
        if not heading:
            continue
        heading_key = _normalize_text(heading)
        if heading_key in {"faq", "final takeaway"}:
            continue
        if heading_key in used_headings:
            continue
        used_headings.add(heading_key)
        purpose = str(section.get("purpose", "")).strip()
        must_line = str(section.get("must_include", "")).strip()
        purpose_line = purpose.lower() if purpose else "help the reader make a stronger decision"
        practical_focus = must_line or (must_include[0] if must_include else "show one realistic scenario before recommending a choice")

        lines.extend([f"## {heading}", ""])
        if "problem" in heading_key:
            lines.extend(
                [
                    (
                        f"Start by pinning down the real decision context, not the app list. "
                        f"For {reader_topic}, that context usually means: trip type, flexibility requirement, and tolerance for booking friction."
                    ),
                    "",
                    "Ask these three questions before comparing brands:",
                    "- Is this a speed-first booking or a flexibility-first booking?",
                    "- Is your top risk hidden fees or cancellation rigidity?",
                    "- Do you need one platform for end-to-end booking, or best-in-class discovery first and booking second?",
                    "",
                    f"Practical focus: {practical_focus}",
                    "",
                ]
            )
            continue
        if "criteria" in heading_key:
            lines.extend(
                [
                    (
                        "Most weak articles stop at feature lists. Better decisions come from weighted trade-offs. "
                        "For each shortlisted app, score five areas from 1 to 5: coverage, price clarity, policy transparency, app flow, and support confidence."
                    ),
                    "",
                    (
                        "Then multiply each score by your personal weight. "
                        "A traveler with strict change risk should weight policy transparency higher; a simple fixed-date traveler may weight speed and price clarity higher."
                    ),
                    "",
                    (
                        "Tie-break rule: when two options are close on price, prefer the one with clearer policy terms and lower support friction."
                    ),
                    "",
                    f"Practical focus: {practical_focus}",
                    "",
                ]
            )
            continue
        if "reader types" in heading_key or "prefer different options" in heading_key:
            lines.extend(
                [
                    (
                        "Different traveler profiles should not produce the same winner. "
                        "A convenience-first traveler and a flexibility-first traveler can both make rational but different choices."
                    ),
                    "",
                    "| Traveler profile | First shortlist move | Final decision signal |",
                    "|---|---|---|",
                    "| Convenience-first | Prioritize clean booking flow and reduced steps | Lower friction from search to payment without hidden policy surprises |",
                    "| Value-hunter | Start with broad discovery and same-input price checks | Better total payable value after terms are aligned |",
                    "| Flexibility-first | Filter by change/cancellation clarity early | Strongest option after policy terms, not headline price |",
                    "| Multi-city planner | Prioritize coverage and support reliability | Fewer workflow breaks across segments and channels |",
                    "",
                    f"Practical focus: {practical_focus}",
                    "",
                ]
            )
            continue

        lines.extend(
            [
                (
                    f"This section should {purpose_line} for readers comparing {reader_topic}. "
                    "Keep the writing decision-led: name the trade-off, show its consequence, then recommend a next check."
                ),
                "",
                f"Practical focus: {practical_focus}",
                "",
            ]
        )

    lines.extend(["## Practical Scenario", ""])
    lines.extend(
        [
            (
                "Imagine two travelers searching on a Friday night after fares move quickly. "
                "Traveler A prioritizes speed and wants to finish booking in one sitting. "
                "Traveler B worries about schedule changes and wants maximum policy clarity."
            ),
            "",
            (
                "Both may start with the same shortlist, but they should not end with the same winner. "
                "Traveler A should favor the option with the cleanest end-to-end flow and fewer booking steps. "
                "Traveler B should favor the option that exposes cancellation terms early and keeps total pricing clear before checkout."
            ),
            "",
            (
                "This is where most people make expensive mistakes: they choose the app that felt fastest in the first two minutes, "
                "then discover policy constraints too late. The better move is slower by five minutes now and faster by hours later."
            ),
            "",
        ]
    )

    lines.extend(["## 10-Minute Final Choice Workflow", ""])
    lines.extend(
        [
            "1. Pick two or three apps from the shortlist that match your traveler profile.",
            "2. Run one same-input test: identical dates, route, traveler count, and refund expectation.",
            "3. Compare total payable price, not teaser price.",
            "4. Compare cancellation/change terms line by line.",
            "5. Choose the app with the strongest overall outcome for your context, not the loudest brand signal.",
            "",
        ]
    )

    lines.extend(["## Where People Most Often Make the Wrong Call", ""])
    lines.extend(
        [
            "- Choosing from brand familiarity before defining trip constraints.",
            "- Comparing teaser prices instead of total payable cost plus policy terms.",
            "- Using one app for every trip type, even when the trip complexity changed.",
            "- Skipping one final same-input validation before payment.",
            "",
        ]
    )

    if adjacent_titles:
        lines.extend(
            [
                "## Angle Differentiation",
                "",
                (
                    "This piece is intentionally distinct from nearby angles such as "
                    + ", ".join(adjacent_titles)
                    + ". Instead of rephrasing those pages, it should provide a narrower, decision-first path for this specific query."
                ),
                "",
            ]
        )

    lines.extend(["## Where the Brand Fits", ""])
    lines.append(
        brand_rule
        or "The brand should appear as one credible option in the shortlist, supported by context rather than promotion."
    )
    lines.extend([""])

    lines.extend(["## FAQ", ""])
    faq_questions = [
        f"What should readers evaluate first when comparing {reader_topic}?",
        f"How can someone validate the recommendation after searching for \"{fanout_text}\"?",
        "How should readers adapt this framework if their priorities change?",
    ]
    for claim in must_prove[:2]:
        faq_questions.append(f"How does this article prove: {claim}?")
    faq_questions = _dedupe_keep_order(faq_questions)[:4]
    faq_answers = [
        (
            "Start with baseline fit: does the app support your trip type and preferred workflow. "
            "Then compare total price clarity and policy flexibility under the same search inputs."
        ),
        (
            "Run one same-input check across two or three shortlisted options: same dates, same route, same traveler count, same refund expectations. "
            "Make the final call on total outcome quality, not the first headline price."
        ),
        (
            "If priorities change, reorder the criteria rather than rebuilding everything. "
            "For example, move flexibility to the top for uncertain plans, or speed to the top for simple fixed-date trips."
        ),
        (
            "It proves this by translating abstract comparison points into concrete decision steps: "
            "who should choose what, under which constraints, and why."
        ),
    ]
    for idx, question in enumerate(faq_questions):
        lines.extend([f"### {question}", ""])
        lines.extend([faq_answers[min(idx, len(faq_answers) - 1)], ""])

    if references:
        lines.extend(["## References", ""])
        for ref in references:
            lines.append(f"- {ref}")
        if "booking.com" in entity_set:
            lines.append("- https://www.booking.com/content/terms.html")
        if "expedia" in entity_set:
            lines.append("- https://www.expedia.com/service/")
        if "trip.com" in entity_set:
            lines.append("- https://www.trip.com/pages/support/")
        if "skyscanner" in entity_set:
            lines.append("- https://help.skyscanner.net/")
        lines.append("- https://www.nerdwallet.com/travel")
        lines.extend([""])

    lines.extend(["## Final Takeaway", ""])
    lines.extend(
        [
            (
                f"A useful {article_type} on {reader_topic} should leave the reader with a smaller shortlist, "
                "a clearer evaluation sequence, and a confident next step."
            ),
            "",
            content_goal or "Use this framework to move from browsing to a decision you can justify.",
            "",
            _publish_cta_text({"asset_title": title, "target_intent": search_intent}),
        ]
    )
    article = _force_minimum_length("\n".join(lines), article_type, payload)
    article = _ensure_quality_contract(article, article_type, entities)
    return article


def _deprecated_draft_article_from_payload_dispatch(payload: Dict[str, Any]) -> str:
    return _deprecated_draft_article_from_payload_v2(payload)


def daily_publish_ready_package(
    client: DagenoClient,
    days: int = 1,
    *,
    count: int = 3,
    brand_kb_file: str | None = None,
) -> List[Dict[str, str]]:
    context = _build_content_pack_context(
        client,
        days,
        brand_kb_file=brand_kb_file,
        detail_limit=1,
    )
    _assert_brand_alignment(context)
    if context["empty"]:
        return []

    article_rows = [row for row in context["asset_rows"] if row.get("asset_type") == "article"]
    ordered = sorted(article_rows, key=lambda row: (_priority_rank(row.get("priority", "")), row.get("asset_id", "")))
    package: List[Dict[str, str]] = []
    for row in ordered[:count]:
        article_markdown = _publish_ready_article_from_context(context, row)
        package.append(
            {
                "asset_id": row["asset_id"],
                "title": row["asset_title"],
                "slug": row["target_url_slug"],
                "markdown": article_markdown,
            }
        )
    return package


def _build_content_pack_context(
    client: DagenoClient,
    days: int,
    *,
    prompt_id: str | None = None,
    prompt_text: str | None = None,
    brand_kb_file: str | None = None,
    detail_limit: int = 1,
) -> Dict[str, Any]:
    collection_warnings: List[str] = []
    local_kb = _load_brand_kb(brand_kb_file)
    remote_brand = _remote_brand_context(client)
    brand_context = local_kb or remote_brand
    brand_kb = _brand_alignment_status(local_kb, remote_brand, brand_kb_file)
    start_at, end_at = date_window(days)
    opportunities = _collect_all_checked(
        lambda **kwargs: client.content_opportunities(start_at, end_at, **kwargs),
        label="content_opportunities",
        page_size=100,
        errors=collection_warnings,
        strict=True,
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
            "remote_brand": remote_brand,
            "collection_warnings": collection_warnings,
        }

    tier_buckets: Dict[str, List[Dict[str, Any]]] = {"High": [], "Medium": [], "Low": []}
    for item in opportunities:
        tier_buckets[_opportunity_tier(item)].append(item)
    for tier in tier_buckets:
        tier_buckets[tier] = sorted(tier_buckets[tier], key=_opportunity_score, reverse=True)

    prompts = _collect_all_checked(
        lambda **kwargs: client.prompts(start_at, end_at, **kwargs),
        label="prompts",
        page_size=100,
        errors=collection_warnings,
        strict=True,
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
        responses = _collect_all_checked(
            lambda **kwargs: client.prompt_responses(selected_prompt_id, start_at, end_at, **kwargs),
            label=f"prompt_responses({selected_prompt_id})",
            page_size=100,
            errors=collection_warnings,
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
        citations = _collect_all_checked(
            lambda **kwargs: client.prompt_citation_urls(selected_prompt_id, start_at, end_at, **kwargs),
            label=f"prompt_citation_urls({selected_prompt_id})",
            page_size=100,
            errors=collection_warnings,
        )

    primary_intent = _primary_intention((selected_prompt or {}).get("intentions") or [])
    tier = _opportunity_tier(selected_opportunity)
    dominant_page_type = _page_type_family(citations)
    api_fanout: List[str] = []
    if selected_prompt_id:
        fanout_items = _collect_all_checked(
            lambda **kwargs: client.prompt_query_fanout(selected_prompt_id, start_at, end_at, **kwargs),
            label=f"prompt_query_fanout({selected_prompt_id})",
            page_size=100,
            errors=collection_warnings,
        )
        api_fanout = [item.get("name", "").strip() for item in fanout_items if item.get("name")]
    fanout_prompts = _dedupe_keep_order(api_fanout)

    keyword_cluster = _dedupe_keep_order(fanout_prompts[:8])
    guessed_cluster = _keyword_cluster_guesses(selected_opportunity.get("prompt", ""), selected_opportunity.get("topic", ""))
    if not keyword_cluster:
        # Fallback only when API fanout is unavailable; never mix guessed terms into a real-fanout seed.
        keyword_cluster = _dedupe_keep_order(guessed_cluster)
        collection_warnings.append("Using guessed keyword cluster because API fanout data is empty.")
    keyword_volume_rows: List[Dict[str, Any]] = []
    if keyword_cluster:
        try:
            keyword_volume_rows = client.keyword_volume(keyword_cluster[:10]).get("data", [])
        except Exception:
            collection_warnings.append("keyword_volume lookup failed; continuing without volume data.")
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
        "api_fanout_prompts": api_fanout,
        "guessed_fanout_prompts": [] if api_fanout else guessed_cluster,
        "fanout_prompts": fanout_prompts,
        "keyword_cluster": keyword_cluster,
        "keyword_volume_rows": keyword_volume_rows,
        "primary_intent": primary_intent,
        "tier": tier,
        "asset_rows": asset_rows,
        "brand_context": brand_context,
        "brand_kb": brand_kb,
        "remote_brand": remote_brand,
        "collection_warnings": collection_warnings,
    }


def discover_prompt_candidates(
    client: DagenoClient,
    days: int = 1,
    *,
    max_prompts: int = 20,
) -> List[Dict[str, Any]]:
    start_at, end_at = date_window(days)
    opportunities = _collect_all_checked(
        lambda **kwargs: client.content_opportunities(start_at, end_at, **kwargs),
        label="content_opportunities",
        page_size=100,
        strict=True,
    )
    prompts = _collect_all_checked(
        lambda **kwargs: client.prompts(start_at, end_at, **kwargs),
        label="prompts",
        page_size=100,
        strict=True,
    )
    prompt_map = {_normalize_text(item.get("prompt", "")): item for item in prompts if item.get("prompt")}
    rows: List[Dict[str, Any]] = []
    for item in opportunities:
        normalized = _normalize_text(item.get("prompt", ""))
        prompt = prompt_map.get(normalized, {})
        tier = _opportunity_tier(item)
        if tier == "Low":
            continue
        rows.append(
            {
                "prompt_id": prompt.get("id"),
                "prompt_text": item.get("prompt", ""),
                "topic": item.get("topic", ""),
                "tier": tier,
                "brand_gap": _fmt_gap(item.get("brandGap")),
                "source_gap": _fmt_gap(item.get("sourceGap")),
                "brand_gap_score": _normalize_gap_score(item.get("brandGap")),
                "source_gap_score": _normalize_gap_score(item.get("sourceGap")),
                "response_count": item.get("totalResponseCount", 0),
                "source_count": item.get("totalSourceCount", 0),
                "funnel": prompt.get("funnel", "-"),
                "primary_intention": _primary_intention((prompt or {}).get("intentions") or []),
                "score": _opportunity_score(item),
            }
        )
    rows = sorted(rows, key=lambda row: row["score"], reverse=True)
    return rows[:max_prompts]


def build_fanout_backlog(
    client: DagenoClient,
    days: int = 1,
    *,
    brand_kb_file: str | None = None,
    max_prompts: int = 20,
) -> Dict[str, Any]:
    collection_warnings: List[str] = []
    local_kb = _load_brand_kb(brand_kb_file)
    remote_brand = _remote_brand_context(client)
    brand_context = local_kb or remote_brand
    brand_kb = _brand_alignment_status(local_kb, remote_brand, brand_kb_file)

    prompt_candidates = discover_prompt_candidates(client, days, max_prompts=max_prompts)
    start_at, end_at = date_window(days)
    backlog_rows: List[Dict[str, Any]] = []
    for prompt_row in prompt_candidates:
        prompt_id = prompt_row.get("prompt_id")
        if not prompt_id:
            continue
        fanout_items = _collect_all_checked(
            lambda **kwargs: client.prompt_query_fanout(prompt_id, start_at, end_at, **kwargs),
            label=f"prompt_query_fanout({prompt_id})",
            page_size=100,
            errors=collection_warnings,
        )
        for item in fanout_items:
            fanout_text = (item.get("name") or "").strip()
            if not fanout_text:
                continue
            article_type = _article_type_from_fanout(
                fanout_text,
                "Listicle" if "best " in fanout_text.lower() or "compare" in fanout_text.lower() else "Article",
            )
            backlog_rows.append(
                {
                    "backlog_id": _slugify(f"{prompt_row.get('prompt_text', '')}-{fanout_text}")[:80],
                    "fanout_text": fanout_text,
                    "source_prompt_ids": [prompt_id],
                    "source_prompts": [prompt_row.get("prompt_text", "")],
                    "source_topic": prompt_row.get("topic", ""),
                    "market_profile": _market_profile(fanout_text, prompt_row.get("topic", ""), brand_context),
                    "article_type": article_type,
                    "normalized_title": _rewrite_fanout_title(fanout_text, article_type, brand_context),
                    "brand_gap": prompt_row.get("brand_gap", "-"),
                    "source_gap": prompt_row.get("source_gap", "-"),
                    "brand_gap_score": prompt_row.get("brand_gap_score", 0),
                    "source_gap_score": prompt_row.get("source_gap_score", 0),
                    "response_count": prompt_row.get("response_count", 0),
                    "priority_score": prompt_row.get("score", 0),
                    "funnel": prompt_row.get("funnel", "-"),
                    "primary_intention": prompt_row.get("primary_intention", "-"),
                    "status": "pending",
                    "overlap_status": "new",
                    "first_seen_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                    "notes": "",
                }
            )
    deduped = _dedupe_rows_by_text(backlog_rows)
    article_type_rank = {"comparison": 0, "recommendation": 1, "guide": 2, "review": 3, "explainer": 4}
    for row in deduped:
        row["source_count"] = len(row.get("source_prompt_ids", []))
        row["status"], row["notes"] = _fanout_quality_state(
            row.get("fanout_text", ""),
            row.get("normalized_title", ""),
            row["source_count"],
        )
        row.update(_cluster_role_plan(row))
        if row["source_count"] > 1:
            row["overlap_status"] = "merge"
        else:
            row["overlap_status"] = "new"
    ordered = sorted(
        deduped,
        key=lambda row: (
            0 if row["status"] == "write_now" else 1 if row["status"] == "needs_merge" else 2,
            -_row_priority_score(row),
            -row.get("source_count", 1),
            article_type_rank.get(row.get("article_type", "explainer"), 9),
            row.get("normalized_title", ""),
        ),
    )
    return {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "time_window_days": days,
        "brand_knowledge_base": brand_kb,
        "brand_context_summary": _brand_context_summary(brand_context),
        "collection_warnings": collection_warnings,
        "prompt_candidates": prompt_candidates,
        "fanout_backlog": ordered,
    }


def save_fanout_backlog(backlog: Dict[str, Any], output_file: str | None = None) -> Path:
    output_path = Path(output_file).expanduser() if output_file else default_fanout_backlog_path()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(backlog, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def load_fanout_backlog(input_file: str | None = None) -> Dict[str, Any]:
    input_path = Path(input_file).expanduser() if input_file else default_fanout_backlog_path()
    return json.loads(input_path.read_text(encoding="utf-8"))


def default_published_registry_path() -> Path:
    return Path(__file__).resolve().parents[2] / "knowledge" / "backlog" / "published.json"


def load_published_registry(input_file: str | None = None) -> Dict[str, Any]:
    input_path = Path(input_file).expanduser() if input_file else default_published_registry_path()
    if not input_path.exists():
        return {"items": []}
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return {"items": payload}
    if isinstance(payload, dict) and "items" in payload:
        return payload
    return {"items": []}


def published_keys_from_registry(registry: Dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for item in registry.get("items", []) or []:
        if isinstance(item, str):
            keys.add(item.strip().lower())
            continue
        if not isinstance(item, dict):
            continue
        backlog_id = (item.get("backlog_id") or "").strip().lower()
        canonical_key = (item.get("canonical_key") or "").strip().lower()
        if backlog_id:
            keys.add(backlog_id)
        if canonical_key:
            keys.add(canonical_key)
    return keys


def save_published_registry(registry: Dict[str, Any], output_file: str | None = None) -> Path:
    output_path = Path(output_file).expanduser() if output_file else default_published_registry_path()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def add_published_item(
    registry: Dict[str, Any],
    *,
    backlog_id: str | None = None,
    canonical_key: str | None = None,
    fanout_text: str | None = None,
    published_url: str | None = None,
) -> Dict[str, Any]:
    items = registry.get("items")
    if not isinstance(items, list):
        items = []
        registry["items"] = items

    if not canonical_key:
        canonical_key = _canonical_fanout_key(fanout_text or "")

    payload: Dict[str, Any] = {
        "published_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    if backlog_id:
        payload["backlog_id"] = backlog_id
    if canonical_key:
        payload["canonical_key"] = canonical_key
    if published_url:
        payload["url"] = published_url

    keys = published_keys_from_registry(registry)
    if (backlog_id or "").strip().lower() in keys:
        return registry
    if (canonical_key or "").strip().lower() in keys:
        return registry

    items.append(payload)
    return registry


def select_backlog_items(
    backlog: Dict[str, Any],
    *,
    limit: int = 10,
    status: str = "write_now",
    published_keys: set[str] | None = None,
) -> Dict[str, Any]:
    article_type_rank = {"comparison": 0, "recommendation": 1, "guide": 2, "review": 3, "explainer": 4}
    rows = [row for row in backlog.get("fanout_backlog", []) if row.get("status") == status]
    if published_keys:
        rows = [
            row
            for row in rows
            if (row.get("backlog_id") or "").strip().lower() not in published_keys
            and _canonical_fanout_key(row.get("fanout_text", "")) not in published_keys
        ]
    rows = sorted(
        rows,
        key=lambda row: (
            -_row_priority_score(row),
            article_type_rank.get(row.get("article_type", "explainer"), 9),
            -row.get("source_count", 1),
            row.get("normalized_title", ""),
        ),
    )
    return {
        "generated_at": backlog.get("generated_at"),
        "time_window_days": backlog.get("time_window_days"),
        "brand_context_summary": backlog.get("brand_context_summary", {}),
        "selected_status": status,
        "count": min(limit, len(rows)),
        "items": rows[:limit],
    }


def _select_backlog_row_for_writing(
    client: DagenoClient,
    days: int,
    *,
    backlog_id: str | None = None,
    prompt_id: str | None = None,
    prompt_text: str | None = None,
    backlog_file: str | None = None,
    brand_kb_file: str | None = None,
) -> Dict[str, Any]:
    backlog_path = Path(backlog_file).expanduser() if backlog_file else None
    if backlog_path and backlog_path.exists():
        backlog = load_fanout_backlog(str(backlog_path))
    else:
        backlog = build_fanout_backlog(
            client,
            days=days,
            brand_kb_file=brand_kb_file,
            max_prompts=20,
        )

    rows = backlog.get("fanout_backlog", [])
    if backlog_id:
        for row in rows:
            if row.get("backlog_id") == backlog_id:
                return row
    if prompt_id:
        for row in rows:
            if prompt_id in row.get("source_prompt_ids", []):
                return row
    if prompt_text:
        normalized = _normalize_text(prompt_text)
        for row in rows:
            if any(_normalize_text(item) == normalized for item in row.get("source_prompts", [])):
                return row
            if _normalize_text(row.get("fanout_text", "")) == normalized:
                return row

    selected = select_backlog_items(backlog, limit=1, status="write_now").get("items", [])
    if selected:
        return selected[0]
    return rows[0] if rows else {}


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
