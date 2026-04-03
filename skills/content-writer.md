---
name: content-writer
description: >
  Use when the user wants to turn Dageno GEO opportunities into a real-fanout backlog and then
  write one publish-ready article from one selected fanout item.
metadata:
  author: GEO-SEO
  version: "0.6.0"
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

Use this skill to turn Dageno prompt opportunities into a real-fanout backlog and then produce one backlog-row-first editorial package for one selected fanout item.

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

## Non-Negotiable Rules

- only use real Dageno fanout
- do not generate guessed fanout
- do not write directly from Dageno `topic`
- one selected fanout should map to one article
- one backlog row should map to one editorial brief
- use the section drafting and review contracts when integrating with external agents
- if local brand knowledge base and Dageno brand snapshot do not match, block publish-ready output

## Required Local Files

- `knowledge/brand/brand-knowledge-base.json`
- `knowledge/backlog/fanout-backlog.json`

## Reference

See [`references/pipeline-spec.md`](references/pipeline-spec.md).
