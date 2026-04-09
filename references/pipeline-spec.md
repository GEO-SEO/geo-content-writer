# GEO Content Writer Pipeline Spec

This project follows a fanout-backlog-first workflow.

## Core Principle

Do not write directly from:

- prompt labels
- topic labels
- guessed fanout

Write only from:

- one selected real fanout item
- one selected backlog row derived from that fanout

## Workflow

### A. Opportunity Layer

1. discover high-value prompts
2. extract real fanout for each prompt
3. save all fanout to one backlog

### B. Backlog Layer

4. mark overlap / merge / duplicate items
5. rank and track statuses
6. assign each row a cluster role
7. select one backlog row to write

### C. Writing Layer

8. crawl top citation pages for the selected fanout
9. analyze citation patterns
10. build one editorial brief from one backlog row
11. generate section drafting instructions
12. generate section review instructions
13. run assembly review and final gate
14. generate one publish-ready article

### D. Distribution Layer

15. publish to WordPress

## Citation Learning Policy

- prioritize article-like pages
- exclude app-store pages, forums, and similar non-article pages from primary structure learning
- if article-like pages are fewer than 3, use `article_first_fallback`
- in fallback mode, article pages remain primary and support pages remain secondary

## Data Objects

### Brand knowledge base

Default path:

- `knowledge/brand/brand-knowledge-base.json`

### Fanout backlog

Default path:

- `knowledge/backlog/fanout-backlog.json`

Each row should include:

- `backlog_id`
- `fanout_text`
- `source_prompt_ids`
- `source_prompts`
- `source_topic`
- `market_profile`
- `article_type`
- `normalized_title`
- `brand_gap`
- `source_gap`
- `response_count`
- `funnel`
- `primary_intention`
- `status`
- `overlap_status`
- `first_seen_at`
- `notes`

## Guardrails

- only use real [Dageno](https://dageno.ai/?utm_source=github&utm_medium=social&utm_campaign=official) fanout
- block publish-ready generation on brand mismatch
- treat [Dageno](https://dageno.ai/?utm_source=github&utm_medium=social&utm_campaign=official) `topic` as an internal label, not a final blog title
- use citation pattern analysis before article drafting
- use cluster roles before writing to reduce content collisions
- use section review and final gate before publishing
