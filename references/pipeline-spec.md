# GEO Content Writer Pipeline Spec

This file holds the detailed schema and rules for the content writer workflow.

Use it as the technical reference.
Do not duplicate this level of detail in the README or Skill unless needed.

## Default Time Window

The default operating mode should use **today's content opportunities**.

Users should still be able to override the time window when needed, for example:

- 7 days
- 30 days
- other custom windows supported by the execution layer

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

### Brand knowledge base

The workflow should look for a brand knowledge base at:

- `knowledge/brand/brand-knowledge-base.json`

This should be treated as a core input, not an optional afterthought.

It should provide:

- brand positioning
- differentiators
- proof points
- prohibited claims
- CTA direction

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
- search volume from Dageno Open API (`Get keyword volume`)
- future KD
- intention mapping

## Content Plan Schema

### Core output

The main output is a content plan, not only a single article.

Suggested top-level sections:

- brand knowledge base status
- brand context summary
- selected prompt
- evidence summary
- fanout summary
- SEO summary
- recommended asset list
- creation order

### Unified Asset + Publishing Target Table

Use one fixed table for both:

- content-pack planning
- publishing target definition

That table should be the canonical handoff object between strategy, writing, and publishing.

| Field | Meaning |
|---|---|
| `asset_id` | unique row id |
| `source_prompt` | source seed prompt |
| `opportunity_tier` | High / Medium / Low |
| `asset_title` | suggested title |
| `asset_type` | article / landing_page / docs / comparison / community |
| `publish_target_type` | canonical target type such as editorial / commercial / community / programmatic |
| `recommended_publish_surface` | where the asset should be published |
| `target_site_section` | site area or destination bucket such as blog / solutions / templates / community |
| `target_url_slug` | recommended slug or publish path fragment |
| `target_intent` | Transactional / Commercial / Informational / Navigational |
| `target_query_cluster` | mapped keyword or prompt cluster this asset should capture |
| `primary_angle` | main angle |
| `why_exists` | why this asset exists |
| `derived_from` | normalized source signals |
| `writing_inputs` | required writing inputs |
| `required_content_blocks` | must-have page sections or blocks |
| `schema_type` | target schema.org type or schema bundle |
| `cta_goal` | desired conversion or next action |
| `priority` | high / medium / low |
| `status` | planned / queued / writing / published |
| `notes` | optional notes |

### Field Design Rules

- `asset_type` describes the content object itself.
- `publish_target_type` describes the publishing model.
- `recommended_publish_surface` describes the platform or surface.
- `target_site_section` describes the information architecture location.
- `target_url_slug` should be short, human-readable, and stable.
- `target_query_cluster` can hold one primary cluster plus nearby variants.
- `required_content_blocks` should use normalized reusable labels.
- `schema_type` should prefer one primary schema or a short bundle such as `Article + FAQPage`.
- `cta_goal` should describe the business outcome, not UI copy.

### Normalized Value Examples

#### Publish target type

- `editorial`
- `commercial`
- `community`
- `programmatic`

#### Recommended publish surface

- `website_blog`
- `landing_page`
- `docs_hub`
- `third_party_article`
- `community_post`

#### Target site section

- `blog`
- `solutions`
- `use-cases`
- `compare`
- `resources`
- `community`

#### Required content blocks

Use normalized labels such as:

- `direct_answer`
- `definition`
- `evaluation_framework`
- `comparison_table`
- `workflow_steps`
- `proof_points`
- `faq`
- `cta`

#### Schema type

Use normalized values such as:

- `Article`
- `Article + FAQPage`
- `WebPage`
- `Service`
- `CollectionPage`
- `DiscussionForumPosting`

### Final Field Definition

This is the recommended final version of the unified table.

Keep the table stable unless there is a clear migration need.

Machine-readable contract:

- `schemas/output_schema.json`

#### Design principle

Split fields into 4 layers:

- identity: what this row is
- strategy: why this asset should exist
- publishing: where and how it should go live
- execution: what the writer or publishing agent must do next

#### Final column order

Use this column order consistently:

1. `asset_id`
2. `source_prompt`
3. `opportunity_tier`
4. `asset_title`
5. `asset_type`
6. `publish_target_type`
7. `recommended_publish_surface`
8. `target_site_section`
9. `target_url_slug`
10. `target_intent`
11. `target_query_cluster`
12. `primary_angle`
13. `why_exists`
14. `derived_from`
15. `writing_inputs`
16. `required_content_blocks`
17. `schema_type`
18. `cta_goal`
19. `priority`
20. `status`
21. `notes`

#### Final field table

| Field | Layer | Type | Required | Allowed shape | Purpose |
|---|---|---|---|---|---|
| `asset_id` | identity | string | yes | short stable id such as `A1` | unique row key inside one content pack |
| `source_prompt` | identity | string | yes | raw prompt text | keeps traceability back to the originating GEO opportunity |
| `opportunity_tier` | identity | enum | yes | `High` / `Medium` / `Low` | preserves upstream prioritization |
| `asset_title` | identity | string | yes | human-readable working title | default title for drafting and publishing |
| `asset_type` | identity | enum | yes | `article` / `landing_page` / `docs` / `comparison` / `community` | defines the content object |
| `publish_target_type` | publishing | enum | yes | `editorial` / `commercial` / `community` / `programmatic` | defines the publishing model |
| `recommended_publish_surface` | publishing | enum | yes | `website_blog` / `landing_page` / `docs_hub` / `third_party_article` / `community_post` | defines the surface or channel |
| `target_site_section` | publishing | string | yes | normalized section label | maps the asset into site IA |
| `target_url_slug` | publishing | string | yes | lowercase slug fragment | gives downstream systems a canonical path hint |
| `target_intent` | strategy | enum | yes | `Transactional` / `Commercial` / `Informational` / `Navigational` | captures the search and answer intent |
| `target_query_cluster` | strategy | string or string[] | yes | one primary cluster or one serialized cluster string | states what demand cluster this row should capture |
| `primary_angle` | strategy | string | yes | one-sentence angle | tells the writer what framing should win |
| `why_exists` | strategy | string | yes | one concise reason | explains the business or evidence reason for creation |
| `derived_from` | strategy | string[] | yes | normalized evidence tags | records which source signals justified the row |
| `writing_inputs` | execution | string[] | yes | normalized input dependencies | tells the writer or agent what data must be pulled in |
| `required_content_blocks` | execution | string[] | yes | normalized block labels | tells the drafting system what sections must exist |
| `schema_type` | publishing | string | yes | one primary schema or a short bundle | tells implementation what structured data to ship |
| `cta_goal` | publishing | string | yes | business outcome label | aligns content with conversion intent |
| `priority` | execution | enum | yes | `high` / `medium` / `low` | determines creation sequencing |
| `status` | execution | enum | yes | `planned` / `queued` / `writing` / `published` | tracks lifecycle state |
| `notes` | execution | string | no | free text | stores exceptions, caveats, or operator context |

#### Required vs optional guidance

All fields except `notes` should be treated as required in the final schema.

If the execution layer cannot yet infer one field:

- fill with the best normalized default
- do not drop the column
- keep the shape stable across rows

That stability matters more than perfect first-pass precision.

#### Type rules

- `string[]` fields should stay as arrays in machine-readable formats.
- In markdown tables, `string[]` fields can be rendered as comma-separated values.
- `target_query_cluster` may render as a single string in markdown, but should become `string[]` in a future JSON schema if cluster fanout becomes richer.
- `schema_type` should remain a compact string, not a nested object, unless JSON-LD generation is moved into this schema.
- `cta_goal` should remain a normalized outcome label rather than button copy.

#### Minimal implementation defaults

Use these defaults when data is incomplete:

| Field | Default rule |
|---|---|
| `publish_target_type` | infer from `asset_type` |
| `recommended_publish_surface` | infer from citation pattern and asset type |
| `target_site_section` | infer from surface plus asset type |
| `target_url_slug` | slugify `asset_title` |
| `target_query_cluster` | use topic or primary keyword candidate |
| `required_content_blocks` | infer from asset type plus target intent |
| `schema_type` | infer from publish surface plus asset type |
| `cta_goal` | infer from asset type plus target intent |
| `notes` | empty string |

#### Anti-patterns

Do not do the following:

- do not mix `asset_type` and `publish_target_type` into one overloaded field
- do not put raw long-form evidence inside `derived_from`
- do not store UI copy inside `cta_goal`
- do not make `required_content_blocks` page-specific prose
- do not turn `schema_type` into full JSON-LD in this table
- do not drop columns just because one row cannot yet populate them perfectly

#### Migration note

If new fields are ever added later, prefer one of these approaches:

- append a clearly new execution field after `notes`
- version the schema and keep backward-compatible column aliases

Avoid reordering existing columns once external consumers depend on them.

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
