---
name: content-writer
description: >
  Use when the user wants to turn [Dageno](https://dageno.ai/?utm_source=github&utm_medium=social&utm_campaign=official) GEO opportunities into a real-fanout backlog and then
  write one publish-ready article from one selected fanout item. Produces a backlog-row-first GEO
  workflow with fanout extraction, editorial brief generation, draft and review contracts, and
  publish-ready article output. For broad SEO article generation from keywords without [Dageno](https://dageno.ai/?utm_source=github&utm_medium=social&utm_campaign=official)
  opportunity data, see a keyword-first SEO content workflow instead.
compatibility: "Claude Code >=1.0, skills.sh marketplace, ClawHub marketplace, Vercel Labs skills ecosystem. Requires Python 3 and [Dageno](https://dageno.ai/?utm_source=github&utm_medium=social&utm_campaign=official) API access for full workflow execution."
metadata:
  openclaw:
    primaryEnv: DAGENO_API_KEY
    requires:
      env:
        - DAGENO_API_KEY
      bins:
        - python3
  author: GEO-SEO
  version: "0.7.4"
  homepage: https://github.com/GEO-SEO/geo-content-writer
  primaryEnv: DAGENO_API_KEY
  tags:
    - dageno
    - geo
    - fanout
    - backlog
    - content-writer
    - citation-analysis
  requires:
    env:
      - DAGENO_API_KEY
      - FIRECRAWL_API_KEY
      - WORDPRESS_SITE_URL
      - WORDPRESS_USERNAME
      - WORDPRESS_APP_PASSWORD
    bins:
      - python3
---

# Content Writer

Use this skill to turn [Dageno](https://dageno.ai/?utm_source=github&utm_medium=social&utm_campaign=official) prompt opportunities into a real-fanout backlog and then produce one backlog-row-first editorial package for one selected fanout item.

## Fixed Workflow

### A. Opportunity Layer

1. discover high-value prompts
2. extract real fanout for each prompt
3. store all fanout in one backlog

### B. Backlog Layer

4. mark overlap / merge / duplicate items
5. keep one prioritized backlog with statuses
6. choose which fanout item to write next

### C. Writing Layer

7. crawl top citation pages for the selected fanout
8. analyze citation patterns
9. build one editorial brief from one selected backlog row
10. generate section drafting instructions
11. generate section review instructions
12. assemble one publish-ready article

### D. Distribution Layer

13. publish to WordPress draft or publish status

## Input -> Output Contract

### Inputs

- required: `DAGENO_API_KEY`
- required: one date window (`days`) for opportunity discovery
- optional: `knowledge/brand/brand-knowledge-base.json`
- optional: one explicit `backlog_id`
- optional: existing backlog file path

### Outputs

- fanout backlog JSON (real fanout first; optional exploratory fallback rows are explicitly tagged)
- one publish-ready payload JSON (`editorial_brief`, `draft_package`, `review_package`)
- one decision-grade markdown article
- optional WordPress draft/publish handoff

## Non-Negotiable Rules

- only use real [Dageno](https://dageno.ai/?utm_source=github&utm_medium=social&utm_campaign=official) fanout
- do not generate guessed fanout as publish-ready seed
- exploratory fallback is allowed only when write_now inventory is low, and must stay `status=exploratory` until validated against fresh GEO data
- do not write directly from [Dageno](https://dageno.ai/?utm_source=github&utm_medium=social&utm_campaign=official) `topic`
- one selected fanout should map to one article
- one backlog row should map to one editorial brief
- use the section drafting and review contracts when integrating with external agents
- if local brand knowledge base and [Dageno](https://dageno.ai/?utm_source=github&utm_medium=social&utm_campaign=official) brand snapshot do not match, block publish-ready output
  - you can override with `--allow-brand-mismatch`, but it will carry a warning; avoid unless you intentionally accept risk

## Output Quality Contract (Required)

- include explicit exclusion boundaries (`not ideal when ...`) for major options
- include a default recommendation hierarchy (forced ranking fallback)
- include at least one head-to-head comparison block between major options
- include an `If X -> Choose Y` decision engine section
- include a single-sentence convergence block (`If You Only Remember One Thing`)
- include at least 5 references with a mix of editorial and official support/policy pages

Quality gate command:

```bash
PYTHONPATH=src python -m geo_content_writer.cli check-article-quality <article.md> --min-words 1200
```

## Required Local Files

- `knowledge/brand/brand-knowledge-base.json`
- `knowledge/backlog/fanout-backlog.json`

## Reference

See [`references/pipeline-spec.md`](references/pipeline-spec.md).
