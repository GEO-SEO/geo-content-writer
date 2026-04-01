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

Use this skill to turn one Dageno GEO opportunity into a usable content plan.

## Best Use Case

Use this skill when a team wants to answer:

- what should be written next
- why that topic matters
- which angle should come first

This skill is not for generic article generation from scratch.
It is for opportunity-driven writing based on Dageno evidence.

## Core Principle

Keep this principle central:

**High-value GEO opportunities do not always have high prompt volume.**

So the workflow should prioritize:

- brand gap
- source gap
- response count
- business relevance

not just volume.

## Workflow

### 1. Classify opportunities

Group prompts into:

- `High`
- `Medium`
- `Low`

Default to `High` first, unless the user picks a different prompt.

### 2. Build the evidence layer

For the selected prompt, collect:

- prompt profile
- response list
- response detail
- citation URLs

Summarize:

- how AI is framing the topic
- whether the brand is missing
- which entities appear instead
- which source types dominate

### 3. Expand the topic

Use:

- prompt fanout
- keyword extraction
- keyword expansion
- search volume
- intention mapping

The goal is to turn one opportunity into multiple nearby writing directions.

### 4. Output a content plan

The content plan should include:

- selected prompt
- evidence summary
- fanout ideas
- search-side context
- recommended asset list
- creation order

### 5. Generate the next asset

Only after the content plan is ready should the workflow choose:

- the first article
- a future landing page
- or another supporting asset

## Output Format

Prefer this order:

1. `Opportunity Tiers`
2. `Selected Prompt`
3. `Evidence Summary`
4. `Fanout Summary`
5. `SEO Summary`
6. `Content Plan`
7. `Next Asset`

## GEO Writing Rules

When the content plan turns into a written asset:

1. Start with a direct answer or definition.
2. Make each H2 understandable on its own.
3. Put the answer before the explanation.
4. Keep one main idea per paragraph.
5. Use lists, tables, steps, and comparisons when helpful.
6. Name entities and capabilities explicitly.
7. Use FAQ as an extraction layer.
8. Write so sections can stand alone as AI-friendly chunks.

## Reference

For detailed schema, data structures, and asset rules, see:

- [`references/pipeline-spec.md`](references/pipeline-spec.md)
