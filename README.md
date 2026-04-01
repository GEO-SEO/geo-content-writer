[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Skill](https://img.shields.io/badge/skill-GEO%20Content%20Writer-blue)](skills/content-writer.md)
[![Workflow](https://img.shields.io/badge/workflow-Inputs%20%E2%86%92%20Evidence%20%E2%86%92%20Fanout%20%E2%86%92%20Content%20Pack-orange)](references/pipeline-spec.md)
[![Docs](https://img.shields.io/badge/docs-Dageno%20Open%20API-informational)](https://open-api-docs.dageno.ai/2055134m0)
[![Examples](https://img.shields.io/badge/examples-Live%20Outputs-lightgrey)](examples/live-30-day-example.md)

# GEO Content Writer

![GEO Content Writer Cover](assets/cover-v3.png)

> A GEO-first content writer that turns Dageno opportunity data into structured content packs for ongoing article generation, future landing pages, and agent-driven execution.
>
> It is designed for teams that want to turn GEO opportunities into a repeatable publishing system, not just generate one-off articles.
>
> In practice, this is a **Content Writer Skill backed by a CLI runtime**: the skill defines the workflow, and the CLI executes real Dageno/Open API steps.

## Quick Links

- [Open API Docs](https://open-api-docs.dageno.ai/2055134m0)
- [Skill Instructions](skills/content-writer.md)
- [Workflow Reference](references/pipeline-spec.md)
- [Live Example Output](examples/live-30-day-example.md)
- [Cursor MCP Example](examples/cursor-mcp.json)
- [Book a Demo](https://dageno.ai)

## What This Project Does

This project helps a team answer one simple question:

> "If AI tools are already talking about our category, what should we publish next so our brand gets included?"

Instead of starting from a plain keyword list, this writer starts from **GEO evidence**:

- which prompts AI is already answering
- where the brand is missing
- which third-party pages AI is citing
- which adjacent prompt ideas exist around the same topic
- which SEO terms map to that opportunity

The result is not just one article title.

The result is a **content pack**: a small, prioritized set of writing opportunities that a team or agent can execute.

## Why This Matters

Most content tools tell teams what people search.

This project tells teams something more useful for GEO:

- where AI is already shaping the market narrative
- where competitors or third-party sources are winning that narrative
- where the brand is absent from high-value AI answers

One of the most important insights here is:

**a high-value GEO opportunity does not always have high prompt volume**

That is exactly why Dageno data is useful.

## About Dageno

[Dageno](https://dageno.ai) is a GEO and AI visibility platform for brands that want to understand how AI systems such as ChatGPT, Gemini, Perplexity, Copilot, and Google AI products talk about their business.

It helps teams monitor:

- prompt-level brand visibility
- prompt-level brand gaps and source gaps
- response detail
- citation patterns
- content opportunities

Open API docs:

- [Dageno Open API](https://open-api-docs.dageno.ai/2055134m0)

This project uses Dageno as the data foundation for automated content writing decisions.

## Contact

For teams evaluating Dageno or this workflow, the public contact paths currently shown on the Dageno website footer are:

- [Schedule a demo](https://dageno.ai)
- [Slack Community](https://join.slack.com)
- [About Dageno](https://dageno.ai)

The footer also states that support is available across:

- Email
- Chat
- Phone
- Slack

## Who This Is For

This project is built for:

- teams that want to automate GEO-driven article generation
- agencies that want a repeatable GEO writing workflow for clients
- marketers who need a simple answer to "what should we publish next?"
- operators who want a content pack before they start writing

## Inputs

At a simple level, the engine needs three kinds of inputs.

### 1. GEO opportunity data from Dageno

- `List content opportunities`
- `List prompts`
- `List responses by prompt`
- `Get response detail by prompt`
- `List citation URLs by prompt`
- `List query fanout by prompt`

### 2. SEO enrichment

- keyword extraction
- keyword expansion
- `Get keyword volume` from the API

In customer-facing language, this is **search volume**.

### 3. Product positioning context

The writer also needs a basic understanding of:

- what the brand does
- which category it wants to win
- which commercial angle matters most

## 10-Second View

For a non-technical customer, the workflow can be reduced to this:

| Input | Output |
|---|---|
| one high-value GEO prompt opportunity from Dageno | one ready-to-use content plan |
| AI response detail | a clear explanation of what AI is saying now |
| citation URLs | a view of which sources are shaping that answer |
| fanout queries | nearby content opportunities |
| search volume | the SEO demand around those opportunities |
| one approved topic | the first article to write |

## Outputs

The output is a **content pack**.

A content pack usually includes:

- one selected prompt opportunity
- a short explanation of why it matters
- a fanout set of nearby prompt ideas
- a search-volume view of related SEO phrases
- a recommended asset list
- a suggested writing order

From there, a team can decide whether to generate:

- a blog article
- a landing page
- a comparison page
- a docs page
- a community-style post

## A Simple Customer Flow

Imagine a customer wants GEO-based article ideas.

The workflow should feel this simple:

```mermaid
flowchart TD
    A["Dageno finds a high-value prompt opportunity"] --> B["The writer checks how AI currently answers it"]
    B --> C["The writer checks which pages AI is citing"]
    C --> D["The writer expands the prompt into nearby questions"]
    D --> E["The writer maps those questions to SEO search volume"]
    E --> F["The writer outputs a content pack"]
    F --> G["The team or agent writes the first article"]
```

## Example Input And Output

Here is a simple example of how the data moves.

### Input

A customer wants article ideas around this prompt:

- `Enterprise AEO solutions for brand authority`

Dageno shows:

- high brand gap
- high source gap
- many AI responses
- many cited third-party URLs

The writer then pulls:

- response detail
- citation URLs
- fanout queries
- related SEO phrases and search volume

### Output

The engine returns a content pack such as:

1. `What Is an Enterprise AEO Solution?`
2. `How to Evaluate Enterprise AEO Platforms`
3. `Best Enterprise AEO Solutions for Brand Authority`
4. `How to Measure Brand Authority in AI Answers`
5. `Enterprise AEO Platform for Brand Authority`

This means the customer does not need to manually decide:

- which angle to write
- which query to expand
- which article should come first

The writer turns one GEO opportunity into a usable publishing queue.

## Real Example

Here is a real-style example of how a team could use this workflow.

### Input

Selected GEO opportunity:

- `Enterprise AEO solutions for brand authority`

What Dageno shows:

- brand gap is high
- source gap is high
- AI is already answering this topic across major platforms
- third-party pages are shaping the answer space

### What The Writer Finds

After checking response detail, citation URLs, fanout, and search-side signals, the writer can summarize the situation like this:

- AI already understands the topic
- AI is willing to cite many third-party sources in this category
- the brand is still missing from that answer landscape
- the opportunity is strong enough to justify multiple content assets, not just one article

### Output

The system turns that one GEO opportunity into a content plan like this:

| Title | Type | Publish Surface | Why It Exists | Priority |
|---|---|---|---|---|
| What Is an Enterprise AEO Solution? | Article | Website blog | AI repeatedly answers this as a category-definition question | High |
| How to Evaluate Enterprise AEO Platforms | Article | Website blog | The prompt is close to solution evaluation and purchase behavior | High |
| Best Enterprise AEO Solutions for Brand Authority | Article | Website blog or third-party article | AI already cites roundup-style content in this space | High |
| How to Measure Brand Authority in AI Answers | Article | Website blog | Buyers need a measurable framework, not only a definition | Medium |
| Enterprise AEO Platform for Brand Authority | Landing page | Landing page | This can become the future conversion page | Medium |

### First Writing Task

The team or agent can then start with:

- `What Is an Enterprise AEO Solution?`

This makes the workflow easy to operationalize:

1. pick one real GEO opportunity
2. let the writer build the content plan
3. approve the top item
4. generate the first article

## End-to-End Content Logic

For customers, the whole flow can be understood in 5 steps:

1. Dageno finds a strong GEO opportunity.
2. The writer checks how AI is answering that topic now.
3. The writer checks which sources AI trusts.
4. The writer expands the topic into adjacent prompt and SEO opportunities.
5. The writer outputs a prioritized content pack.

## What The Customer Actually Gets

The most useful output is a **content plan table**.

This is the working queue that a marketing team or writing agent can use directly.

Instead of only giving a keyword or a topic, the system gives:

- what to write
- why it matters
- where it should be published
- which item should be written first

### Example Content Plan

| Title | Type | Publish Surface | Why This Matters | Priority |
|---|---|---|---|---|
| What Is an Enterprise AEO Solution? | Article | Website blog | AI keeps answering this question, but the brand is still missing | High |
| How to Evaluate Enterprise AEO Platforms | Article | Website blog | This is a strong buyer-intent angle close to solution selection | High |
| Best Enterprise AEO Solutions for Brand Authority | Article | Website blog or third-party article | AI already cites roundup-style content in this topic area | High |
| How to Measure Brand Authority in AI Answers | Article | Website blog | This helps turn abstract authority into measurable outcomes | Medium |
| Enterprise AEO Platform for Brand Authority | Landing page | Landing page | This can become the commercial conversion page later | Medium |

### Full Table Structure

If a team wants the detailed version, the content plan table can include:

| Column | Meaning |
|---|---|
| `asset_id` | internal row id |
| `source_prompt` | the GEO prompt that created this plan |
| `opportunity_tier` | High / Medium / Low |
| `asset_title` | suggested title |
| `asset_type` | article / landing page / docs / comparison / community |
| `recommended_publish_surface` | where the content should be published |
| `target_intent` | the search or buying intent behind it |
| `primary_angle` | the main angle of the piece |
| `why_exists` | the reason this item is in the plan |
| `derived_from` | the key signals that created the idea |
| `writing_inputs` | the data the writer should use |
| `priority` | what should be written first |
| `status` | planned / queued / writing / published |
| `notes` | optional notes |

## GEO Data Value, Explicitly

This project should make Dageno's GEO value obvious.

The platform is useful because it helps answer questions such as:

- which commercially important prompts exclude the brand entirely
- which answer spaces are already shaped by third-party sources
- which content formats AI systems already trust
- which adjacent prompts deserve new content
- which content assets should exist before writing begins

That is more valuable than a plain keyword list.

## GEO Writing Standard

When an asset row is turned into actual content, follow these rules:

1. Start with a direct definition or answer.
2. Make each H2 understandable without the rest of the page.
3. Put the answer before the explanation.
4. Keep one core idea per paragraph.
5. Prefer lists, tables, steps, and comparisons when useful.
6. Name entities and capabilities explicitly.
7. Use FAQ as an extraction layer.
8. Write in a way that can be quoted by AI systems as a standalone answer.

## Live Commands

### Basic opportunity view

```bash
cd geo-content-writer
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export DAGENO_API_KEY="your-token"
PYTHONPATH=src python -m geo_content_writer.cli content-opportunities --days 7
```

### Full content pack

```bash
PYTHONPATH=src python -m geo_content_writer.cli content-pack --days 7
```

### Target one prompt

```bash
PYTHONPATH=src python -m geo_content_writer.cli content-pack --days 7 --prompt-text "Enterprise AEO solutions for brand authority"
```

## Repo Structure

```text
geo-content-writer/
├── README.md
├── LICENSE
├── manifest.json
├── agents/
│   └── openai.yaml
├── skills/
│   └── content-writer.md
├── references/
│   └── pipeline-spec.md
├── assets/
├── examples/
└── src/
```

## License

MIT
