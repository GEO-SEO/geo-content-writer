import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from geo_content_writer.workflows import (
    draft_article_from_payload,
    _market_profile,
    _reader_topic_phrase,
    _rewrite_fanout_title,
)


def slugify(value: str) -> str:
    out = []
    for ch in value.lower():
        if ch.isalnum():
            out.append(ch)
        else:
            out.append("-")
    slug = "".join(out).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug


def main() -> None:
    base = json.loads(Path("examples/publish-ready-payload-trip.json").read_text(encoding="utf-8"))
    seeds = [
        "best app for travel bookings in one place",
        "travel booking apps compared which one fits your trip style",
        "how to choose a travel booking app that actually saves time",
    ]

    out_dir = Path("outputs") / ("generated-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ"))
    out_dir.mkdir(parents=True, exist_ok=True)

    for i, seed in enumerate(seeds, 1):
        payload = deepcopy(base)
        topic = payload.get("backlog_row", {}).get("source_topic", "")
        brand_context = {}

        reader_topic = _reader_topic_phrase(seed, topic, brand_context)
        profile = _market_profile(seed, topic, brand_context)

        payload["selected_fanout"] = {
            "fanout_text": seed,
            "reader_topic": reader_topic,
            "market_profile": profile,
        }

        article_type = payload.get("article_type") or payload.get("backlog_row", {}).get("article_type") or "explainer"
        title = _rewrite_fanout_title(seed, article_type, brand_context)
        payload["title_options"] = [
            title,
            _rewrite_fanout_title(reader_topic, article_type, brand_context),
            reader_topic.title(),
        ]

        md = draft_article_from_payload(payload)
        out_path = out_dir / f"{i:02d}-{slugify(title)[:80]}.md"
        out_path.write_text(md, encoding="utf-8")

    print(str(out_dir))


if __name__ == "__main__":
    main()

