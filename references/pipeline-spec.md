# GEO Content Writer Pipeline Spec

This file holds the detailed schema and rules for the content writer workflow.

Use it as the technical reference.
Do not duplicate this level of detail in the README or Skill unless needed.

## Main Flow

1. collect content opportunities
2. classify into `High / Medium / Low`
3. select one prompt
4. inspect prompt profile
5. inspect responses and response detail
6. inspect citation URLs
7. run prompt fanout
8. run SEO translation and search-volume enrichment
9. generate the content plan
10. choose the first asset to write

## Opportunity Tiers

### High

- high brand gap
- high source gap
- enough response count
- strong business relevance

### Medium

- some real gap
- weaker stability or weaker business fit

### Low

- weak gap
- small sample size
- weak business fit

## Data Layers

### GEO data

- content opportunities
- prompts
- responses
- response detail
- citation URLs
- prompt fanout

### SEO data

- primary keyword
- keyword cluster
- search volume
- future KD
- intention mapping

## Content Plan Schema

### Core output

The main output is a content plan, not only a single article.

Suggested top-level sections:

- selected prompt
- evidence summary
- fanout summary
- SEO summary
- recommended asset list
- creation order

### Recommended Asset List

Use a fixed table with these fields:

| Field | Meaning |
|---|---|
| `asset_id` | unique row id |
| `source_prompt` | source seed prompt |
| `opportunity_tier` | High / Medium / Low |
| `asset_title` | suggested title |
| `asset_type` | article / landing_page / docs / comparison / community |
| `recommended_publish_surface` | where the asset should be published |
| `target_intent` | Transactional / Commercial / Informational / Navigational |
| `primary_angle` | main angle |
| `why_exists` | why this asset exists |
| `derived_from` | normalized source signals |
| `writing_inputs` | required writing inputs |
| `priority` | high / medium / low |
| `status` | planned / queued / writing / published |
| `notes` | optional notes |

## Publish Surface Logic

Infer publish surface from citation patterns:

- dominant `Article` -> `website_blog`
- dominant `Listicle` -> `website_blog` or `third_party_article`
- dominant `Homepage / Product Page / Category Page` -> `landing_page` or `comparison_page`
- dominant `Discussion` -> `community_post`

## Derived-From Tags

Use tags such as:

- `high_brand_gap`
- `high_source_gap`
- `repeated_response_framing`
- `dominant_article_citations`
- `dominant_listicle_citations`
- `fanout_prompt_cluster`
- `high_transactional_intent`
- `keyword_search_demand`

## Writing Inputs

Each asset should specify the data inputs it depends on.

Examples:

- `top_response_details`
- `top_citation_urls`
- `top_entities_in_mentions`
- `fanout_prompt_set`
- `keyword_cluster`
- `search_volume_and_kd`
- `dageno_product_positioning`

## GEO Writing Rules

1. Start with a direct definition or answer.
2. Make each H2 independently understandable.
3. Put the answer before the explanation.
4. Keep one core idea per paragraph.
5. Prefer lists, tables, steps, and comparisons where useful.
6. Make entities and capabilities explicit.
7. Use FAQ as an extraction layer.
8. Write in a way that supports standalone answer extraction.
