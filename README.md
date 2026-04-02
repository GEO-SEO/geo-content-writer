[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Skill](https://img.shields.io/badge/skill-Content%20Writer-blue)](skills/content-writer.md)
[![Workflow](https://img.shields.io/badge/workflow-Prompt%20%E2%86%92%20Fanout%20Backlog%20%E2%86%92%20Citation%20Analysis-blue)](references/pipeline-spec.md)

# GEO Content Writer

> Turn Dageno prompt opportunities into a fanout backlog, then turn selected fanout items into publishable GEO articles.

## What Works Today

- discover high-value prompts from Dageno
- extract real fanout into a reusable backlog
- mark backlog rows as `write_now` or `needs_cleanup`
- generate publish-ready article drafts from selected backlog items
- publish drafts to WordPress and WordPress.com

## Current Limitation

The project does **not** yet perform full citation-page body crawling inside the main runtime.

Current behavior:

- it uses Dageno citation URLs and citation metadata
- it does **not** yet fetch and analyze the full HTML/body text of the top citation pages in the main workflow

So the project has already shifted to a fanout-backlog-first architecture, but the citation crawl step is still a missing implementation in the writing layer.

## What This Project Is

This is no longer a prompt-to-article shortcut.

It is a GEO writing system with one core idea:

- Dageno finds high-value prompts
- real fanout becomes the content backlog
- citation analysis teaches the writing structure
- one selected fanout becomes one article

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
9. choose article type
10. rewrite into a reader-facing title
11. generate one publish-ready article

### D. Distribution Layer

12. publish to WordPress draft or publish status

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

### 3. Generate one publish-ready article

```bash
PYTHONPATH=src python -m geo_content_writer.cli publish-ready-article --output-file examples/publish-ready-article.md
```

### 4. Publish to WordPress

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
PYTHONPATH=src python -m geo_content_writer.cli publish-ready-article
PYTHONPATH=src python -m geo_content_writer.cli publish-wordpress examples/publish-ready-article.md --status draft
```

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
- citation crawl is planned in the workflow design but not yet fully wired into runtime article generation
- WordPress publishing is a lightweight distribution example, not the center of the system

## License

MIT
