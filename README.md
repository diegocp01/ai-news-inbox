# ai-news-inbox

Public drop-box for AI news found by the Hermes agent.

One JSON file per story in `items/`, named `YYYY-MM-DD-short-slug.json`:

```json
{
  "title": "Headline in plain text",
  "summary": "One or two sentences on what happened and why it matters.",
  "url": "https://original-source",
  "date": "2026-08-08",
  "source": "Publication name"
}
```

A daily job on gptaiacademy.com reads this folder and publishes new entries to
its Daily AI news page. Nothing here is added to the curated AI history
timeline automatically.
