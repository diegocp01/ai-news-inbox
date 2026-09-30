# Research-paper and AI-content provenance verification

Use this reference for ANFs about newly posted papers, simulated-user systems, text watermarks, or provenance metadata.

## Fast arXiv discovery and verification

1. When a pasted paper name is misspelled or stylized ambiguously, query the arXiv Atom API using exact title fragments and adjacent concepts. Inspect the returned `id`, `title`, `published`, `updated`, abstract, comments/project URL, and author list.
2. Open the canonical arXiv abstract page to verify submission/version dates. Do not call a revised paper “new” solely because current coverage is new.
3. Open experimental HTML when available. Extract figure URLs and captions from the rendered DOM; choose the figure whose caption best represents the reported result or framework, then verify the direct image URL’s content type and dimensions.
4. Read limitations/responsible-use sections, not only the abstract. For synthetic-persona work, distinguish persona-record count, released coreset, instantiated trials, validation sample, and real-human evidence.
5. Attribute paper results to the authors and avoid upgrading preprints into settled findings.

Useful arXiv API form:

```text
https://export.arxiv.org/api/query?search_query=ti:%22<encoded-title-fragment>%22&start=0&max_results=10
```

## Text watermarks versus file provenance

Treat these as separate mechanisms:

- **Text watermark:** an imperceptible statistical or machine-readable signal embedded in generated wording. It may travel with copied text and survive some editing, but short passages or substantial edits can make detection unreliable.
- **File provenance:** signed metadata such as C2PA attached to images or other files. It can indicate processing history but may disappear through screenshots, conversions, or re-saving.

Verification checklist:

1. Confirm whether the policy applies to newly launched models, existing models, or both.
2. Record the effective date, geographic scope, supported products/API/cloud surfaces, and whether rollout is complete or transitional.
3. Do not say “all Claude text” or equivalent unless the source covers every model and output surface. Prefer “text from supported/new models.”
4. State that a detected mark is not definitive proof that AI authored the underlying ideas: a model may translate, summarize, or edit human-written text.
5. State that an absent mark does not prove human authorship; old models, short text, heavy editing, or unsupported surfaces may produce no detectable signal.
6. Distinguish legal obligation from voluntary code implementation. Verify the operative law/article and the company’s signed commitment separately.

## Same-day publisher recovery

Google News RSS can expose a just-published article before normal search indexing. Navigate the RSS article URL and then inspect `location.href`, canonical metadata, OpenGraph title/image, and article body in the live DOM. The browser snapshot may still display a Google News URL even after the publisher content has loaded; trust the verified publisher canonical URL, not a guessed slug.

For sparse official product launches, inspect the live rendered DOM, hidden tab panels, image alt text, and model-selector screenshots. Attribute internal adoption counts and “battle-tested” language to the vendor unless independently corroborated.
