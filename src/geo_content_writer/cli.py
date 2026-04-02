from __future__ import annotations

import argparse
import json
from pathlib import Path

from jsonschema import ValidationError, validate

from .client import DagenoClient
from .workflows import (
    backlink_opportunity_brief,
    brand_snapshot,
    citation_source_brief,
    community_opportunity_brief,
    content_pack,
    content_opportunity_brief,
    content_pack_json,
    default_brand_kb_path,
    first_asset_draft,
    new_content_brief,
    prompt_deep_dive,
    prompt_gap_report,
    topic_watchlist,
    weekly_exec_brief,
)


def _default_output_schema_path() -> Path:
    return Path(__file__).resolve().parents[2] / "schemas" / "output_schema.json"


def _default_brand_kb_schema_path() -> Path:
    return Path(__file__).resolve().parents[2] / "schemas" / "brand_knowledge_base_schema.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GEO Content Writer CLI")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--api-key", default=None, help="Override DAGENO_API_KEY")
    common.add_argument("--base-url", default="https://api.dageno.ai/business/api")
    common.add_argument("--days", type=int, default=1, help="Time window for date-based workflows; defaults to today")
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
        "--output-file",
        default=None,
        help="Optional file path to write the content pack output",
    )
    first_asset_parser = subparsers.add_parser(
        "first-asset-draft",
        parents=[common],
        help="Generate the first writing draft from the top content-pack asset",
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
        help="Validate a brand knowledge base JSON file against its schema",
    )
    brand_kb_parser.add_argument("input_file", help="Brand knowledge base JSON file to validate")
    brand_kb_parser.add_argument(
        "--schema-file",
        default=str(_default_brand_kb_schema_path()),
        help="Optional schema file path; defaults to schemas/brand_knowledge_base_schema.json",
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

    if args.command == "validate-output":
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

    if args.command == "validate-brand-kb":
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
        if args.output_json:
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
                )
            )
    elif args.command == "first-asset-draft":
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
