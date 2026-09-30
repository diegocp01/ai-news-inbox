# DeepSeek live model verification

Use for same-day DeepSeek model launches or bare model-name intakes when search and social results are sparse or contradictory.

## Authoritative checks

1. Open `https://api-docs.deepseek.com/` and inspect the live model IDs and version note in **Your First API Call**.
2. Open `https://api-docs.deepseek.com/quick_start/pricing` and verify:
   - exact model/version name;
   - thinking-mode support;
   - context length and maximum output;
   - API features;
   - cache-hit, cache-miss, and output pricing;
   - concurrency limits;
   - any announced-but-not-yet-effective peak/off-peak policy.
3. Inspect `https://api-docs.deepseek.com/sitemap.xml` for a dedicated current news page. A current model can appear in live docs before a launch article enters the sitemap.
4. Read canonical and OpenGraph metadata from the live pricing page. The standard social card is currently `https://api-docs.deepseek.com/img/deepseek-social-card.jpeg`; verify it still resolves directly and record current dimensions before using it.

## Framing rules

- Prefer the official live docs over social summaries or contradictory search results.
- If no dated announcement exists, say DeepSeek “added,” “introduced,” or “updated” the endpoint based on the live docs; avoid claiming a precise launch date unsupported by a dated source.
- Preserve exact distinctions between model alias and version, e.g. alias `deepseek-v4-flash` versus version `DeepSeek-V4-Flash-0731`.
- Do not say peak pricing is active when the docs say it “will soon” apply or that its effective date remains subject to announcement.
- The docs and CDN hosts are compliant ANF destinations unless the skill’s current machine-readable policy changes.