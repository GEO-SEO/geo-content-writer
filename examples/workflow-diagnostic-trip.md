# Workflow Diagnostic: Trip.com Data Flow

This file shows one real run of the workflow using the alternate [Dageno](https://dageno.ai/?utm_source=github&utm_medium=social&utm_campaign=official) API key.

Goal:

- visualize the full pipeline
- identify where the article quality breaks
- separate data mismatch problems from writing-template problems

## Step 0: [Dageno](https://dageno.ai/?utm_source=github&utm_medium=social&utm_campaign=official) Brand Snapshot

Input:

- [Dageno](https://dageno.ai/?utm_source=github&utm_medium=social&utm_campaign=official) API key: alternate key

Output:

```text
Brand: Trip
Domain: trip.com
Website: https://www.trip.com
Tagline: Your Non-stop Travel Mate
```

Interpretation:

- the data source is not [Dageno](https://dageno.ai/?utm_source=github&utm_medium=social&utm_campaign=official)
- the monitored brand is Trip.com
- this means a [Dageno](https://dageno.ai/?utm_source=github&utm_medium=social&utm_campaign=official)-only local knowledge base is a mismatch

## Step 1: Local Brand Knowledge Base

Input:

- default project KB: `knowledge/brand/brand-knowledge-base.json`

Output:

```json
{
  "brand_name": "[Dageno](https://dageno.ai/?utm_source=github&utm_medium=social&utm_campaign=official)",
  "domain": null,
  "category": "Answer Engine Optimization and GEO platform"
}
```

Interpretation:

- this knowledge base is for the GEO-SEO product
- it does not match the alternate [Dageno](https://dageno.ai/?utm_source=github&utm_medium=social&utm_campaign=official) account

## Step 2: Brand Alignment Check

Rule:

- if local brand KB and [Dageno](https://dageno.ai/?utm_source=github&utm_medium=social&utm_campaign=official) brand snapshot do not match
- block publish-ready generation

Observed output:

```text
ValueError: Brand knowledge base does not match the [Dageno](https://dageno.ai/?utm_source=github&utm_medium=social&utm_campaign=official) brand snapshot. Use a matching knowledge base before generating publish-ready output.
```

Interpretation:

- this protection is correct
- it prevents the system from mixing Trip.com data with [Dageno](https://dageno.ai/?utm_source=github&utm_medium=social&utm_campaign=official) messaging

## Step 3: Matched Brand Knowledge Base

Input:

- `examples/trip-brand-knowledge-base.json`

Output:

```json
{
  "brand_name": "Trip",
  "domain": "trip.com",
  "category": "Online travel booking platform",
  "one_liner": "Trip.com helps travelers compare and book flights, hotels, trains, and travel packages in one place."
}
```

Interpretation:

- this fixes the brand-context mismatch
- from here on, the remaining problems come from transformation rules, not brand alignment

## Step 4: Compact Content Pack Output

Input:

- [Dageno](https://dageno.ai/?utm_source=github&utm_medium=social&utm_campaign=official) account: Trip.com
- matched KB: Trip

Output:

```json
{
  "selected_prompt": "best app for travel bookings in one place",
  "opportunity_summary": {
    "selected_tier": "Medium",
    "brand_gap": "100%",
    "source_gap": "100%"
  },
  "evidence_summary": {
    "response_count": 6,
    "citation_url_count": 142,
    "dominant_page_type": "Listicle",
    "top_entities": ["Google", "Expedia", "Priceline", "Hopper"]
  },
  "seo_summary": {
    "primary_keyword_candidate": "best app for travel bookings in one place",
    "keyword_cluster_preview": [
      "best app for travel bookings in one place",
      "enterprise top rated travel apps solutions",
      "top rated travel apps platform"
    ]
  }
}
```

Interpretation:

- the raw prompt is consumer travel intent
- the dominant citation type is listicle
- the entity set is consumer-travel specific

This part is mostly reasonable until the keyword cluster gets expanded.

## Step 5: Where The Pipeline First Goes Wrong

Problematic transformation:

```python
_keyword_cluster_guesses(prompt_text, topic)
```

Observed output preview:

```text
enterprise top rated travel apps solutions
top rated travel apps platform
top rated travel apps software
top rated travel apps tools
top rated travel apps for enterprise brands
```

Why this is wrong:

- the original prompt is consumer travel intent
- the helper injects enterprise/B2B language automatically
- that changes the meaning of the topic before the article is even written

Conclusion:

- this is the first major rule error
- the system should not add enterprise-flavored variants unless the prompt itself is B2B

## Step 6: Asset Title Generation

Current rule:

- derive article titles from `topic`
- use one fixed family of titles for all article types

Observed output:

```text
What Is Top Rated Travel Apps?
How to Choose the Best Top Rated Travel Apps
Best Top Rated Travel Apps Options Right Now
```

Why this is weak:

- "Top Rated Travel Apps" is not a natural category phrase
- the system treats topic labels as publishable human titles
- it does not normalize to reader language such as:
  - Best Travel Booking Apps in One Place
  - How to Choose an All-in-One Travel Booking App

Conclusion:

- title generation is the second major rule error
- topic labels from [Dageno](https://dageno.ai/?utm_source=github&utm_medium=social&utm_campaign=official) cannot be treated as blog-ready titles

## Step 7: Publish-Ready Article Generation

Observed outline:

```text
What Is Top Rated Travel Apps?
What Top Rated Travel Apps Actually Means in Practice
How Teams Should Evaluate Top Rated Travel Apps Solutions
What a Realistic Top Rated Travel Apps Workflow Looks Like
The Mistakes That Make Top Rated Travel Apps Content Weak
```

Why this still feels unnatural:

- the article still uses software-buying language for a consumer app topic
- "workflow", "operational workflow", and "published content" are inherited from the GEO/SaaS template
- the body structure is cleaner than before, but the voice is still wrong for the topic

Conclusion:

- this is the third major rule error
- article type and market type are not being separated before writing starts

## Step 8: What The Data Gets Right

These parts of the data flow are not the root issue:

- prompt text: `best app for travel bookings in one place`
- cited entities: Google, Expedia, Priceline, Hopper
- dominant page type: `Listicle`
- citation URLs from travel comparison pages and app listings

Interpretation:

- the [Dageno](https://dageno.ai/?utm_source=github&utm_medium=social&utm_campaign=official) opportunity itself is coherent for Trip.com
- the pipeline breaks when it converts that opportunity into B2B/GEO-style content structures

## Root Cause Summary

There are 3 primary failure points:

1. `keyword_cluster` expansion injects enterprise/B2B framing even for consumer topics.
2. `topic` is treated as if it were a publishable blog title.
3. the publish-ready article template assumes one universal "software evaluation" article type.

## What Should Change Next

To fix quality at the system level, not article-by-article:

1. Split article generation by topic type before title generation.
2. Add a normalization layer that converts raw `topic` into reader-facing title language.
3. Stop injecting enterprise variants unless the prompt or brand context clearly indicates B2B intent.
4. Create separate article blueprints for:
   - consumer listicle / recommendation intent
   - commercial comparison intent
   - category definition intent
   - product / solution intent

## Final Judgment

The main issue is not that the model "cannot write."

The main issue is that the current rules hand the model the wrong abstraction:

- wrong keyword expansion
- wrong title framing
- wrong article archetype

So the article becomes unnatural before the writing step even starts.
