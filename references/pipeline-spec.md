# GEO Content Writer Pipeline Spec

This project follows a fanout-backlog-first workflow.

## Core Principle

Do not write directly from:

- prompt labels
- topic labels
- guessed fanout

Write only from:

- one selected real fanout item

## Workflow

### A. Opportunity Layer

1. discover high-value prompts
2. extract real fanout for each prompt
3. save all fanout to one backlog

### B. Backlog Layer

4. mark overlap / merge / duplicate items
5. rank and track statuses
6. select one fanout item to write

### C. Writing Layer

7. crawl top citation pages for the selected fanout
8. analyze citation patterns
9. choose article type
10. rewrite into a reader-facing title
11. generate one publish-ready article

### D. Distribution Layer

12. publish to WordPress

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

- only use real Dageno fanout
- block publish-ready generation on brand mismatch
- treat Dageno `topic` as an internal label, not a final blog title
- use citation pattern analysis before article drafting
