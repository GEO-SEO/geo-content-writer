---
name: content-writer
description: >
  Use when the user wants to turn Dageno content opportunities into a structured SEO + GEO content
  pack. This skill starts by classifying prompts into High, Medium, and Low opportunity tiers,
  defaults to High first, then analyzes prompt profile, responses, response detail, citation URLs,
  prompt fanout, keyword expansion, SEO metrics, and intentions before outputting a reusable content
  pack. It is designed for ongoing opportunity-driven content generation, not just one-off article writing.
metadata:
  author: GEO-SEO
  version: "0.4.0"
  homepage: https://github.com/GEO-SEO/geo-content-writer
  primaryEnv: DAGENO_API_KEY
  tags:
    - dageno
    - seo
    - geo
    - content-factory
    - opportunity-tiering
    - prompt-fanout
    - citation-intelligence
    - content-pack
  triggers:
    - "Dageno content opportunities"
    - "high medium low opportunity"
    - "prompt fanout"
    - "response detail"
    - "citation URLs"
    - "content pack"
    - "SEO GEO content blueprint"
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

# GEO Content Writer

Use this skill to turn one Dageno high-opportunity prompt into a reusable content pack.

## What This Skill Is For

This skill is for teams that want to use Dageno as the starting point for SEO + GEO content production.

It should not behave like:

- a plain keyword generator
- a one-prompt one-article writer
- a simple reporting dashboard

It should behave like:

- an opportunity classifier
- an evidence analyzer
- a fanout engine
- a content-pack generator

## Core Insight

Keep this principle central:

**High-value content opportunities do not always have high prompt volume.**

That means:

- do not rank opportunities by volume alone
- prioritize real brand gaps and source gaps
- use response count and commercial closeness as stronger evidence

## Opportunity Tiers

The skill should always group prompts into:

- `High Opportunity`
- `Medium Opportunity`
- `Low Opportunity`

### High Opportunity

Usually means:

- high brand gap
- high source gap
- enough response count to show the issue is stable
- strong business relevance

Default to this tier first.

### Medium Opportunity

Use as the second queue.

### Low Opportunity

Keep visible, but do not prioritize by default.

## Operating Principle

One expensive analysis pass should not produce only one article.

It should produce:

- one evidence layer
- one fanout layer
- one SEO/GEO merge
- one reusable content pack

Then the user can choose:

- which article to write first
- whether to generate a future landing page

## Main Workflow

### 1. Classify opportunities

Start by listing prompts under:

- High Opportunity
- Medium Opportunity
- Low Opportunity

Default to High first, but allow user choice.

### 2. Select the working prompt

Once selected, capture:

- prompt text
- prompt id
- topic
- funnel
- intentions
- observed prompt volume

### 3. Build the evidence layer

Inspect:

- response list
- response detail
- citation URLs

Use this to answer:

- is the gap real
- is the gap stable
- what entities or sources are filling the gap
- what source types dominate the answer space

### 4. Run prompt fanout

Keep prompt fanout in the core workflow.

Important:

- the connector may be provided later
- do not remove this step from the architecture
- do not do fanout of fanout

The purpose is:

- expand one prompt into adjacent prompt opportunities
- prepare the content pack

### 5. Run SEO translation

After fanout, translate the seed prompt into SEO language:

- extract a primary keyword
- expand a keyword cluster
- enrich with `search_volume` and `keyword_difficulty`
- map intentions

### 6. Merge GEO and SEO

The unified decision object should include:

- opportunity tier
- prompt profile
- response-gap summary
- citation summary
- fanout prompts
- keyword cluster
- SEO metrics
- intentions

### 7. Output a content pack

This is the primary output.

Do not collapse too early into a single article.

The pack should contain:

- one selected prompt
- evidence summary
- fanout prompt set
- keyword cluster
- recommended asset list
- recommended creation order

### Recommended Asset List

The recommended asset list should be emitted as a structured table, not just prose.

Suggested fields:

- `asset_id`
- `source_prompt`
- `opportunity_tier`
- `asset_title`
- `asset_type`
- `recommended_publish_surface`
- `target_intent`
- `primary_angle`
- `why_exists`
- `derived_from`
- `writing_inputs`
- `priority`
- `status`
- `notes`

#### Publish surface guidance

Infer `recommended_publish_surface` from citation patterns and asset role.

Examples:

- `website_blog`
- `landing_page`
- `docs_page`
- `comparison_page`
- `community_post`
- `third_party_article`

#### Derived-from guidance

Normalize the reasons into reusable tags such as:

- `high_brand_gap`
- `high_source_gap`
- `repeated_response_framing`
- `dominant_article_citations`
- `dominant_listicle_citations`
- `fanout_prompt_cluster`
- `high_transactional_intent`
- `keyword_search_demand`

#### Writing-input guidance

Each asset row should specify what the writing step should consume.

Examples:

- `top_response_details`
- `top_citation_urls`
- `top_entities_in_mentions`
- `fanout_prompt_set`
- `keyword_cluster`
- `search_volume_and_kd`
- `dageno_product_positioning`

### 8. Choose the generation target

Only after the content pack is ready should the user pick:

- article
- future landing page
- future supporting asset

## Demand Model

Keep these layers separate:

- `observed_prompt_volume`
- `estimated_prompt_volume`
- `search_volume`
- `keyword_difficulty`

Never treat estimated fanout demand as observed prompt volume.

## Intention Model

Use Dageno-aligned intention categories:

- `Transactional`
- `Commercial`
- `Navigational`
- `Informational`

Preferred structure:

```json
{
  "intentions": [
    {
      "score": 86,
      "intention": "Commercial"
    }
  ]
}
```

Real data may also appear as:

```json
{
  "i": "Transactional",
  "s": 88
}
```

The skill should normalize both forms.

## Future Branches

Keep these branches visible in the architecture:

- landing page generation
- existing-content refresh
- post-publish monitoring loop

## GEO Writing Guidance

When the workflow moves from content-pack row to actual written output, use the following writing rules:

1. Start with a direct definition or answer.
2. Make every H2 understandable without the full page context.
3. Put the conclusion before the supporting explanation.
4. Keep paragraphs focused on one main idea.
5. Use lists, tables, comparisons, or steps where they clarify the answer.
6. Name entities, products, and capabilities explicitly.
7. Treat FAQ as an extraction layer.
8. Prefer writing that can be quoted as a standalone answer.

Preferred GEO structure:

- definition-first intro
- context-independent H2 blocks
- short answer-led paragraphs
- at least one structured list or table
- FAQ block
- evidence-backed claims
- chunk-friendly sections

They are not the current core, but they should not be forgotten.

## Output Format

When the skill answers, prefer this structure:

1. `Opportunity Tiers`
2. `Selected Prompt`
3. `Evidence Layer`
4. `Fanout Layer`
5. `SEO Layer`
6. `Content Pack`
7. `Chosen Asset`

## Connector Policy

Required:

- `DAGENO_API_KEY`

Reserved / optional:

- future KD connector
- page fetch connectors
- SERP connector

If optional connectors are missing:

- keep their place in the workflow
- continue with the rest of the analysis
- do not silently delete that branch from the architecture

## Reference

For the repo-level workflow and data model, see:

- [`references/pipeline-spec.md`](references/pipeline-spec.md)
