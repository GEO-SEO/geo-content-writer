# Benchmark Suite

This folder defines a lightweight benchmark pack for validating the official production flow from:

- backlog row
- editorial brief
- draft sections
- section review
- assembly review
- final gate

## Goal

Validate four things against real project examples:

1. articles do not collapse into near-duplicates
2. drafts sound more like edited blog posts than generic generated templates
3. cluster roles stay differentiated
4. the final payload provides enough structure for an external agent to execute the workflow

## Cases

- travel shortlist
- travel comparison
- enterprise category
- enterprise evaluation

## Suggested scoring

- `distinctness`: 1-5
- `naturalness`: 1-5
- `decision_support`: 1-5
- `brand_fit`: 1-5
- `cluster_role_clarity`: 1-5

## Recommended usage

1. produce the payload from the official command path
2. draft sections from `draft_package.draft_sections`
3. run section reviews from `review_package.section_review_contract`
4. assemble and run the final gate
5. record scores in `benchmark_manifest.json`
