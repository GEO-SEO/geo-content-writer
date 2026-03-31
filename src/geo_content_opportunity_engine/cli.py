from __future__ import annotations

import argparse

from .client import DagenoClient
from .workflows import (
    backlink_opportunity_brief,
    brand_snapshot,
    citation_source_brief,
    community_opportunity_brief,
    content_pack,
    content_opportunity_brief,
    new_content_brief,
    prompt_deep_dive,
    prompt_gap_report,
    topic_watchlist,
    weekly_exec_brief,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GEO Content Opportunity Engine CLI")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--api-key", default=None, help="Override DAGENO_API_KEY")
    common.add_argument("--base-url", default="https://api.dageno.ai/business/api")
    common.add_argument("--days", type=int, default=30, help="Time window for date-based workflows")
    common.add_argument("--limit", type=int, default=5, help="How many rows to show")

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("brand-snapshot", parents=[common], help="Get brand context")
    subparsers.add_parser("topic-watchlist", parents=[common], help="List top topics")
    subparsers.add_parser("prompt-gap", parents=[common], help="List high-value prompts")
    subparsers.add_parser("citation-brief", parents=[common], help="Summarize cited domains and URLs")
    subparsers.add_parser("content-opportunities", parents=[common], help="List top content opportunities")
    subparsers.add_parser("backlink-opportunities", parents=[common], help="List top backlink opportunities")
    subparsers.add_parser("community-opportunities", parents=[common], help="List top community opportunities")
    subparsers.add_parser("weekly-brief", parents=[common], help="Generate a combined executive brief")
    content_pack_parser = subparsers.add_parser(
        "content-pack",
        parents=[common],
        help="Turn one Dageno opportunity into a reusable content pack",
    )
    content_pack_parser.add_argument("--prompt-id", default=None, help="Optional prompt ID to target")
    content_pack_parser.add_argument("--prompt-text", default=None, help="Optional prompt text to target")
    new_content_parser = subparsers.add_parser(
        "new-content-brief",
        parents=[common],
        help="Turn one real content opportunity into a new-content brief",
    )
    new_content_parser.add_argument("--prompt-id", default=None, help="Optional prompt ID to target")
    new_content_parser.add_argument("--prompt-text", default=None, help="Optional prompt text to target")

    prompt_parser = subparsers.add_parser("prompt-deep-dive", parents=[common], help="Inspect one prompt in detail")
    prompt_parser.add_argument("prompt_id", help="Prompt ID from the prompts endpoint")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

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
    elif args.command == "content-pack":
        print(
            content_pack(
                client,
                days=args.days,
                limit=args.limit,
                prompt_id=args.prompt_id,
                prompt_text=args.prompt_text,
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
