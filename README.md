# AI News Inbox

This repository is the handoff point between the Hermes AI-news workflow and the Daily AI News page on GPT AI Academy.

## How it works

1. AI-news items are prepared through the ANF workflow.
2. When the pending items are compiled, Hermes creates one JSON batch in [`items/`](items/).
3. GPT AI Academy reads those batches and publishes the new stories on its Daily AI News page.

This is an internal content pipeline, not a public software project. There is nothing to install or configure here.

## Files

Each compile run creates one new file using the current UTC date:

```text
items/YYYY-MM-DD.json
```

If a file already exists for that date, the next batch uses `-2`, `-3`, and so on. Existing files are kept unchanged.

Each file contains a JSON array:

```json
[
  {
    "title": "Headline in plain text",
    "description": "A short explanation of what happened and why it matters.",
    "image_url": "https://example.com/story-image.jpg",
    "learn_more_url": "https://example.com/full-story",
    "date": "2026-08-08",
    "source": "Publication name"
  }
]
```

The AI history timeline is curated separately; adding an item here does not automatically add it to that timeline.
