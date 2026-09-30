# Same-day model-name disambiguation

Use this note for terse ANF intakes that name only a model family or version, such as “Gemini 3.8.”

- Search the exact wording first. Silently expand it to a specific public SKU only when current exact-match results consistently identify one release.
- Verify release status with dated same-event coverage and, when available, an official model card or live model documentation.
- Do not trust a search snippet as evidence that an older official post was updated for the new release. Related-story modules can splice a new model heading into the snippet.
- Extract the candidate page and compare its title, body, and publication date. Reject it as the launch source when those still document an earlier model.
- If official live docs lag but a current reputable report confirms rollout, use the current report as the final URL and the official model card only as supporting evidence.
