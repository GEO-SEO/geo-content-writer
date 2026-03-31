# Dageno Content Factory Pipeline Spec

This reference captures the latest workflow logic for the skill.

The key shift is:

- not one prompt to one article
- but one high-opportunity prompt to one reusable content pack

## Core Principles

### 1. High-value opportunities do not always have high prompt volume

Do not rank opportunity quality by prompt volume alone.

A strong opportunity can exist when:

- brand gap is high
- source gap is high
- responses are numerous
- business intent is strong
- prompt volume is still low or zero

This is one of Dageno's strongest product-value narratives.

### 2. Heavy analysis should produce multiple downstream assets

One full pass of:

- prompt evidence
- response evidence
- citation evidence
- fanout
- SEO enrichment

should lead to a content pack, not just one article.

### 3. Prompt fanout is a first-class workflow step

The connector is now part of the workflow and should remain in the architecture.

Do not do fanout of fanout.

## Main Workflow

### Step 1: collect opportunities

Source:

- `get_content_opportunities`

### Step 2: classify into tiers

Classify all prompts into:

- High Opportunity
- Medium Opportunity
- Low Opportunity

Default to High first.

### Step 3: select the working prompt

Capture:

- prompt id
- prompt text
- topic
- funnel
- intentions
- observed prompt volume

### Step 4: inspect response evidence

Use:

- response list
- response detail

Questions:

- how many responses exist
- how many mention the brand
- what framing dominates
- what entities appear instead

### Step 5: inspect citation evidence

Use:

- prompt-level citation URLs

Questions:

- what source types dominate
- what domains dominate
- what content formats are most cited

### Step 6: run prompt fanout

Goal:

- expand the selected prompt into adjacent prompt opportunities

This is required to turn one prompt into a content pack.

### Step 7: run SEO translation

Use:

- primary keyword extraction
- keyword expansion
- search volume
- future KD
- intention mapping

### Step 8: build the unified decision object

Combine:

- opportunity tier
- prompt profile
- response-gap summary
- citation summary
- fanout outputs
- keyword cluster
- SEO metrics
- intentions

### Step 9: output the content pack

The pack should include:

- selected prompt
- key evidence
- fanout prompt set
- keyword cluster
- recommended asset list
- creation order

#### Recommended asset list schema

Use a fixed table-like structure with these fields:

| Field | Meaning |
|---|---|
| `asset_id` | unique row id |
| `source_prompt` | source seed prompt |
| `opportunity_tier` | High / Medium / Low |
| `asset_title` | recommended title |
| `asset_type` | article / landing_page / docs / comparison / community |
| `recommended_publish_surface` | where to publish |
| `target_intent` | Transactional / Commercial / Informational / Navigational |
| `primary_angle` | main angle |
| `why_exists` | reason this asset should exist |
| `derived_from` | normalized source signals |
| `writing_inputs` | required data inputs for writing |
| `priority` | high / medium / low |
| `status` | planned / queued / writing / published |
| `notes` | optional notes |

#### Publish surface logic

Infer publishing surface from citation patterns:

- dominant `Article` -> `website_blog`
- dominant `Listicle` -> `website_blog` or `third_party_article`
- dominant `Homepage / Product Page / Category Page` -> `landing_page` or `comparison_page`
- dominant `Discussion` -> `community_post`

#### Derived-from examples

Use normalized tags such as:

- `high_brand_gap`
- `high_source_gap`
- `repeated_response_framing`
- `dominant_article_citations`
- `dominant_listicle_citations`
- `fanout_prompt_cluster`
- `high_transactional_intent`
- `keyword_search_demand`

#### Writing-input examples

Use explicit data dependencies such as:

- `top_response_details`
- `top_citation_urls`
- `top_entities_in_mentions`
- `fanout_prompt_set`
- `keyword_cluster`
- `search_volume_and_kd`
- `dageno_product_positioning`

### Step 10: choose the next generated asset

Possible downstream outputs:

- article
- future landing page
- future supporting asset

## Opportunity Tiers

### High Opportunity

Usually:

- high brand gap
- high source gap
- enough response count
- high commercial or product relevance

### Medium Opportunity

Usually:

- partial gap
- weaker stability or weaker business fit

### Low Opportunity

Usually:

- weak gap
- small sample size
- weak business fit

## Demand Layers

Keep these separate:

- `observed_prompt_volume`
- `estimated_prompt_volume`
- `search_volume`
- `keyword_difficulty`

## Intention Normalization

The workflow should normalize both:

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

and:

```json
[
  {
    "i": "Transactional",
    "s": 88
  }
]
```

## Future Branches

Keep visible in project architecture:

- landing page generation
- existing-content refresh
- post-publish monitoring loop

## GEO Writing Standard

When a row from the recommended asset list is turned into content, use this writing standard:

1. Start with a direct definition or answer.
2. Make each H2 independently understandable.
3. Put the answer before the explanation.
4. Keep one core idea per paragraph.
5. Prefer lists, tables, steps, and comparisons where helpful.
6. Make entities and capabilities explicit.
7. Use FAQ as an extraction layer.
8. Write in a way that supports standalone answer extraction.

Suggested output shape:

- definition-first intro
- context-independent H2 sections
- short answer-led paragraphs
- structured list or table blocks
- FAQ block
- evidence-backed claims
- chunk-friendly sections

## Suggested Unified Object

```json
{
  "opportunity_tier": "High",
  "selected_prompt": {
    "id": "673c9c68-b400-4cab-ae78-66925f06eab3",
    "prompt": "Enterprise AEO solutions for brand authority",
    "topic": "Answer Engine Optimization",
    "funnel": "BOFU",
    "observed_prompt_volume": 0,
    "intentions": [
      {
        "i": "Transactional",
        "s": 88
      }
    ]
  },
  "evidence": {
    "response_count": 94,
    "mentioned_true": 0,
    "mentioned_false": 94,
    "top_page_types": [
      ["Article", 393],
      ["Listicle", 106]
    ]
  },
  "fanout": {
    "prompts": []
  },
  "seo": {
    "primary_keyword": null,
    "keyword_cluster": []
  },
  "content_pack": {
    "recommended_assets": []
  }
}
```
