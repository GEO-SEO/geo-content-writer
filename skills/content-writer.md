---
name: content-writer
description: >
  Use when the user wants to turn Dageno GEO opportunities into a content plan or a first article.
  This skill classifies opportunities into High, Medium, and Low, analyzes response and citation
  evidence, expands the topic with fanout and SEO data, and outputs a content plan that can be
  executed by a writing agent.
metadata:
  author: GEO-SEO
  version: "0.4.0"
  homepage: https://github.com/GEO-SEO/geo-content-writer
  primaryEnv: DAGENO_API_KEY
  tags:
    - dageno
    - geo
    - seo
    - content-writer
    - content-plan
    - prompt-fanout
    - citation-intelligence
  triggers:
    - "content writer"
    - "geo content"
    - "content plan"
    - "response detail"
    - "citation URLs"
    - "prompt fanout"
  requires:
    env:
      - DAGENO_API_KEY
      - SEO_METRICS_API_URL
      - SEO_METRICS_API_KEY
      - JINA_API_KEY
      - FIRECRAWL_API_KEY
      - SERPAPI_API_KEY
    bins:
      - python3
---

# Content Writer

Use this skill to turn one Dageno GEO opportunity into a usable content plan and first draft.

Before running the main workflow, check for a brand knowledge base at:

- `knowledge/brand/brand-knowledge-base.json`

If the file is missing, warn the user that the workflow can still run, but brand positioning, proof points, and CTA language may become inconsistent across outputs.

If an external agent is calling this skill, that agent should assume this skill reads from that standard path unless the user explicitly supplies another file location.

## Workflow

### 0. Load the brand knowledge base

Read the brand knowledge base from:

- `knowledge/brand/brand-knowledge-base.json`

Use it to keep these things consistent across the content plan and future drafts:

- brand positioning
- differentiators
- proof points
- claims to avoid
- CTA direction

### 1. Build the content pack

The skill should:

- classify opportunities into `High`, `Medium`, and `Low`
- inspect response and citation evidence
- expand the topic with fanout and keyword signals
- output a lightweight content pack with a unified asset table

### 2. Generate the first asset draft

After the content pack is ready, the skill can draft the top asset.

### 3. Generate a publish-ready article

Before distribution, convert the internal draft into a publish-ready article.

That article should follow the fixed CORE-EEAT writing policy from:

- <https://github.com/aaron-he-zhu/core-eeat-content-benchmark>

At minimum, enforce:

- direct answer early
- definition first
- audience statement
- scope statement
- heading hierarchy
- TL;DR
- comparison or decision framework
- FAQ
- references
- conclusion and next step

## GEO Writing Rules

1. Start with a direct answer or definition.
2. Make each H2 understandable on its own.
3. Put the answer before the explanation.
4. Keep one main idea per paragraph.
5. Use lists, tables, steps, and comparisons when helpful.
6. Name entities and capabilities explicitly.
7. Use FAQ as an extraction layer.
8. Write so sections can stand alone as AI-friendly chunks.

## Reference

See [`references/pipeline-spec.md`](references/pipeline-spec.md).
