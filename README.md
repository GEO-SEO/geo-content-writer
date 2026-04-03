[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Skill](https://img.shields.io/badge/skill-Content%20Writer-blue)](skills/content-writer.md)
[![Workflow](https://img.shields.io/badge/workflow-Backlog%20Row%20%E2%86%92%20Editorial%20Brief%20%E2%86%92%20Draft%20%2B%20Review-blue)](references/pipeline-spec.md)

# GEO Content Writer

> Turn Dageno prompt opportunities into a fanout backlog, then turn one selected backlog row into an editorial brief, draft contract, and review contract for publishable GEO articles.

## What Works Today

- discover high-value prompts from Dageno
- extract real fanout into a reusable backlog
- mark backlog rows as `write_now` or `needs_cleanup`
- generate backlog-row-first editorial payloads for selected backlog items
- generate section-by-section draft and review contracts for external agents
- publish drafts to WordPress and WordPress.com

## Current Limitation

The project does **not** yet perform full citation-page body crawling inside the main runtime.

Current behavior:

- it uses Dageno citation URLs and citation metadata
- it now performs lightweight article-first citation crawling
- it does **not** yet perform full browser-rendered or Firecrawl-based extraction

So the project has already shifted to a fanout-backlog-first architecture, but the citation crawl step is still a partial implementation in the writing layer.

## Citation Learning Policy

- prefer article-like pages first
- ignore app-store, forum, and similar non-article pages for primary structure learning
- if article-like pages are fewer than 3, switch to `article_first_fallback`
- in fallback mode, keep article pages as the primary learning source and use support pages only as secondary context

## What This Project Is

This is no longer a prompt-to-article shortcut.

It is a GEO writing system with one core idea:

- Dageno finds high-value prompts
- real fanout becomes the content backlog
- one backlog row becomes one editorial brief
- the editorial brief becomes a draft contract and review contract
- external agents can write section by section instead of improvising from one loose prompt

## Core Workflow

### A. Opportunity Layer

1. discover high-value prompts
2. extract real fanout for each prompt
3. save all fanout into one backlog

### B. Backlog Layer

4. mark overlap / merge / duplicate items
5. keep one prioritized backlog with statuses
6. choose which fanout item to write next

### C. Writing Layer

7. crawl top citation pages for the selected fanout
8. analyze citation patterns
9. build one editorial brief from one selected backlog row
10. generate section-by-section draft instructions
11. generate section-by-section review instructions
12. assemble one publish-ready article

### D. Distribution Layer

13. publish to WordPress draft or publish status

## Non-Negotiable Rules

- only use real Dageno fanout
- do not generate guessed fanout
- do not write directly from Dageno `topic` labels
- do not publish from prompt alone
- one selected fanout should map to one article
- if brand knowledge base and Dageno brand snapshot do not match, block publish-ready generation

## Why This Is Better

This design avoids three common failure modes:

- writing from internal topic labels that do not sound like human search language
- repeating near-duplicate articles because different prompts expand into similar fanout
- copying one universal article template across every industry

It also gives external agents a cleaner interface:

- a stable backlog row as the production object
- an editorial brief with audience, angle, and differentiation targets
- a section drafting contract instead of one giant article prompt
- a section review contract and assembly review prompt for quality control

## Required Knowledge Base

The project expects a local brand knowledge base at:

```text
knowledge/brand/brand-knowledge-base.json
```

If the Dageno account belongs to a different brand than the local knowledge base, publish-ready generation should stop until the knowledge base is corrected.

## Quick Start

### 1. Discover prompt candidates

```bash
PYTHONPATH=src python -m geo_content_writer.cli discover-prompts --days 1 --max-prompts 20
```

### 2. Build the real fanout backlog

```bash
PYTHONPATH=src python -m geo_content_writer.cli build-fanout-backlog --days 1 --max-prompts 20
```

Default backlog file:

```text
knowledge/backlog/fanout-backlog.json
```

Suggested backlog statuses:

- `write_now`
- `needs_merge`
- `needs_cleanup`
- `skip`

### 3. Select the next backlog items

```bash
PYTHONPATH=src python -m geo_content_writer.cli select-backlog-items --top-n 10
```

### 4. Generate one backlog-row-first article payload

```bash
PYTHONPATH=src python -m geo_content_writer.cli publish-ready-article \
  --backlog-file knowledge/backlog/fanout-backlog.json \
  --backlog-id your-backlog-row-id \
  --output-file examples/publish-ready-payload.json
```

This now outputs a structured payload with:

- `editorial_brief`
- `draft_package`
- `review_package`
- `writer_prompt`

If you do not pass `--backlog-id`, the CLI will fall back to the top `write_now` row.

### 5. Draft an article from the payload

```bash
PYTHONPATH=src python -m geo_content_writer.cli draft-article-from-payload \
  examples/publish-ready-payload.json \
  --output-file examples/publish-ready-article.md
```

### 6. Publish to WordPress

```bash
export WORDPRESS_SITE_URL="https://your-site.com"
export WORDPRESS_USERNAME="your-username"
export WORDPRESS_APP_PASSWORD="your-application-password"
PYTHONPATH=src python -m geo_content_writer.cli publish-wordpress examples/publish-ready-article.md --status draft
```

For `wordpress.com` hosted sites, also set:

```bash
export WORDPRESS_CLIENT_ID="your-client-id"
export WORDPRESS_CLIENT_SECRET="your-client-secret"
```

## Key Commands

```bash
PYTHONPATH=src python -m geo_content_writer.cli discover-prompts
PYTHONPATH=src python -m geo_content_writer.cli build-fanout-backlog
PYTHONPATH=src python -m geo_content_writer.cli select-backlog-items --top-n 10
PYTHONPATH=src python -m geo_content_writer.cli publish-ready-article --backlog-id <row-id>
PYTHONPATH=src python -m geo_content_writer.cli draft-article-from-payload examples/publish-ready-payload.json
PYTHONPATH=src python -m geo_content_writer.cli publish-wordpress examples/publish-ready-article.md --status draft
```

## Payload Shape

The primary production payload is no longer a loose writer prompt. It is a machine-readable object for external agents:

- `backlog_row`: the selected production unit
- `selected_fanout`: normalized writing seed
- `editorial_brief`: audience, article angle, differentiation targets, adjacent rows to avoid, and evidence guardrails
- `draft_package`: target word counts, `draft_sections`, and assembly notes
- `review_package`: final review prompts plus `section_review_contract`
- `writer_prompt`: a convenience prompt derived from the structured payload

See:

- `schemas/article_generation_payload_schema.json`
- `examples/publish-ready-payload-trip.json`

## Official Path

The recommended production flow is now:

1. `build-fanout-backlog`
2. `select-backlog-items`
3. `publish-ready-article --backlog-id <row-id>`
4. `draft-article-from-payload`
5. run section reviews from `review_package.section_review_contract`
6. run assembly review from `review_package.assembly_review_prompt`
7. clear the final gate in `review_package.final_gate`
8. `publish-wordpress`

Commands still present for compatibility but no longer recommended as the main entrypoint:

- `legacy-publish-ready-article`
- `content-pack`
- `first-asset-draft`

## Cluster Roles

Each backlog row now carries a `cluster_role` to make the content calendar more deliberate before writing begins. Examples:

- `category_article`
- `buyer_shortlist_article`
- `decision_stage_comparison_article`
- `workflow_guidance_article`
- `fit_assessment_article`

The goal is to stop adjacent rows from becoming near-duplicates that differ only in title wording.

## Benchmarks

A lightweight benchmark suite now lives in:

- `examples/benchmarks/README.md`
- `examples/benchmarks/benchmark_manifest.json`

It uses 4 real project examples across travel and enterprise software to evaluate:

- distinctness
- naturalness
- decision support
- brand fit
- cluster role clarity

## Repo Structure

```text
geo-content-writer/
├── README.md
├── LICENSE
├── manifest.json
├── agents/
│   └── openai.yaml
├── skills/
│   └── content-writer.md
├── knowledge/
│   ├── brand/
│   │   └── brand-knowledge-base.json
│   └── backlog/
├── schemas/
├── references/
├── examples/
└── src/
```

## Technical Notes

- the project keeps Dageno as the opportunity discovery layer
- the backlog is the core production object
- fanout is the main writing seed
- citation crawl is still lightweight and not yet a full browser-rendered implementation
- `publish-ready-article` is now a backlog-row-first payload builder for model-driven writing
- the main writing interface is designed for external agents that can draft and review section by section
- WordPress publishing is a lightweight distribution example, not the center of the system

## License

MIT
