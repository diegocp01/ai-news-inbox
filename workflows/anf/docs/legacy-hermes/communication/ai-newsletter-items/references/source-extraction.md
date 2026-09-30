# Source Extraction Patterns for ANF Items

Concise techniques learned from prior AI-newsletter-format sessions.

## Web articles

Use article metadata first:

- `og:title` for the title signal
- `og:description` for the summary signal
- `og:image` for `Image URL`
- `og:url` or canonical link for the final URL

Clean tracking parameters from the final URL when the canonical URL is available (drop `utm_*`, `mrfcid`, etc.).

When browser navigate times out or returns thin JS shells, fall back to `urllib`/`curl` with a normal browser User-Agent and parse the same meta tags from HTML. Do not treat search snippets alone as verified body copy.

### Search fallback: Google News RSS → publisher search

If the configured web-search backend is temporarily unavailable:

1. Open `https://news.google.com/rss/search?q=<narrow encoded query>&hl=en-US&gl=US&ceid=US:en` in the browser.
2. Read candidate headlines and publishers from the XML feed. Use this only for discovery—not as the final source.
3. Resolve the actual article through the publisher’s own search page or by opening the publisher result and inspecting DOM links. This avoids emitting a Google News redirect.
4. Read the article body, extract its canonical URL and `og:image`, and preserve source attribution.

This is a fallback workflow, not evidence that ordinary search is permanently unavailable.

**Browser-session pitfall:** serialize `browser_navigate` calls. They mutate one shared browser tab/session, so parallel navigations can race and leave later `browser_snapshot`, `browser_console`, or `browser_get_images` calls attached to the wrong page. Parallelize independent `web_search`/`web_extract` calls instead; navigate and inspect one browser page at a time.

### Same-day vendor voice-model launches

For a launch such as Grok Voice Think Fast where the primary announcement is on X or a policy-blocked `.ai` news page:

1. Resolve the shortened social link to recover the exact canonical slug and launch state, even though that blocked host cannot be the final `URL:`.
2. Search Google News RSS using the exact model name. Newly indexed independent coverage may appear there before ordinary search catches up.
3. Open the publisher result, then read the actual canonical location and inspect article images; never emit the Google News redirect.
4. Prefer a credible independent report. Treat same-day retailer/editorial blogs as fallback sources only; if the available alternate is too weak, leave `URL:` blank rather than implying strong independent verification.
5. Capture developer-impact details when confirmed: time to first audio, per-minute price, API/builder availability, automatic alias migration date, and the explicit version pin needed to avoid migration.
6. Attribute benchmark, transcription, conversion, and support-containment improvements to the vendor unless independently reproduced.
7. Prefer a story-specific publisher hero or product screenshot over X-hosted media, which violates image-host policy.

### Rogue-agent and safety-incident claims

Keep evidence layers separate:

- Company-confirmed breach details can be stated as disclosed by the company.
- Details from Reuters or another outlet citing unnamed sources—such as an agent leaving instructions for future runs or disabling monitors—must remain “reported” claims.
- If reporting says it is unclear whether earlier behavior involved the same agent as a later breach, preserve that uncertainty.
- Prefer neutral titles such as “Agent Reportedly Left Instructions to Bypass Controls” over anthropomorphic framing like “plotted its escape.”
- A publisher search page can recover a clean article URL when a news-feed result exposes only a redirect; Tom’s Hardware’s search DOM is one proven example.

### Cloudflare / 403 publishers (Axios and similar)

When the publisher blocks browser and direct HTTP with challenge pages:

1. **Body text:** `curl`/`jina` reader — `https://r.jina.ai/https://www.example.com/path` returns markdown of the article. Use this for summary facts, not as the final `URL:`.
2. **Metadata / OG image:** try `https://api.microlink.io/?url=<encoded-article-url>` for `title`, `description`, and `image.url` when HTML is unreachable.
3. **Stale Axios OG:** microlink sometimes returns an old stock CDN asset (e.g. 2018 `images.axios.com/...`). If the image is generic or years older than the story, swap to a verified story-specific image from related same-event coverage (e.g. Japan Times Kimi booth photo for a Kimi policy piece) while keeping the Axios learn-more URL.
4. Prefer the clean canonical Axios path without social UTMs as `URL:`.

## Policy-blocked hosts (`.ai`, OpenAI, X)

Final `URL:` must obey skill frontmatter `anf_policy`. Common rewrite targets:

| Blocked primary | Prefer instead |
| --- | --- |
| `x.ai/...` product or news | Microsoft Marketplace listing, independent press, GitHub (`github.com/xai-org/...`) |
| `platform.kimi.ai/...` docs | Independent press (Tom’s Hardware, Reuters, TechCrunch), or non-`.ai` site such as `kimi.com` if it hosts the technical blog |
| `openai.com/...` / `help.openai.com/...` | Independent press if it covers the same story; **if same-day / press has not caught up, leave `URL:` blank** rather than linking OpenAI |
| `fireworks.ai/...`, other vendor `*.ai` blogs | Official LinkedIn company cross-post with the same metrics, or independent coverage |
| `claude.ai/...` | `support.claude.com`, `claude.com`, or `anthropic.com` (non-`.ai`) |
| X/Twitter only | Company page, GitHub, help center, or leave `URL:` blank |

Images must not use `pbs.twimg.com` / twimg hosts. Pull publisher CDN, arXiv HTML figures, marketplace screenshots, or company static assets instead.

**OpenAI index posts with no compliant press alternate yet:** scrape the page for facts and `og:image` (often `images.ctfassets.net/...` — allowed). Emit blank `URL:`, story image from Contentful/CDN, and attribute findings as what OpenAI says (sandbox escapes, trajectory monitoring, pause/restore, etc.).

### Chrome Web Store as a compliant product source

For a same-day ChatGPT browser-feature announcement available only through forbidden OpenAI/X URLs:

1. Find the verified Chrome Web Store listing and read its live **Overview**; confirm it materially documents the relevant browser context, tabs, site access, permissions, or history behavior.
2. Use the clean `chromewebstore.google.com/detail/.../<extension-id>` canonical URL rather than a store search page.
3. Inspect all large carousel images from the live DOM (`document.images`, `currentSrc`, `naturalWidth`, `naturalHeight`). The listing `og:image` is often only a small extension icon.
4. Visually inspect candidate screenshots and select the one depicting the announced feature—for example, Side Chat or starting a task from a browser tab—not merely the first asset.
5. A listing that documents browser behavior does not independently verify every desktop-app detail in a social announcement. Keep those details explicitly attributed to the company, or omit them if the match is too weak.

### Apple App Store as a compliant launch source

For a same-day app or agent launch whose primary announcement is on X or a policy-blocked `.ai` page:

1. Locate the verified `apps.apple.com/.../id...` listing and treat its live description as authoritative for the shipping iPhone/iPad capabilities, developer identity, privacy disclosures, and availability—not for unsupported desktop claims.
2. Use the clean App Store product URL as `URL:` when it materially documents the launch. This is preferable to leaving the URL blank or linking a thin same-day rewrite.
3. Inspect `document.images` for `is*-ssl.mzstatic.com` carousel assets. Apple pages may omit useful `og:image` metadata or initially expose only a 200×200 placeholder.
4. Prefer a feature-specific screenshot over the app icon. An App Store thumbnail such as `.../157x340bb.webp` can usually be requested at a larger proportional size such as `.../630x1365bb.webp`; open the resulting URL and verify that it resolves directly with plausible dimensions before publishing.
5. Cross-check platform and subscription claims against independent coverage or the launch post. Do not infer Android, Windows, Linux, Mac, plan gates, or beta status solely from an iPhone listing.

## Microsoft Marketplace (Office add-ins)

For Grok Excel/Word/PowerPoint add-ins:

1. Use the Marketplace product URL as final `URL:` (compliant, stable, plan gates listed).
2. Read Overview body for capabilities and availability (e.g. SuperGrok, Heavy, Business, Enterprise; usage limits).
3. Prefer large snapshot images (`*Hero*.png`, `ExcelTwo.png`, etc. on `catalogartifact.azureedge.net`) over the 300×300 add-in icon in `og:image`.
4. `x.ai/grok/excel` and similar pages are often 403 and are policy-blocked by the `.ai` suffix anyway.

## GitHub repositories

GitHub repo pages usually expose enough metadata:

- `og:title` often includes `owner/repo` and tagline
- `og:description` often contains the repo description
- `og:image` is a GitHub OpenGraph image and is acceptable as the image URL
- README text should be skimmed for a clearer ≤60-word summary
- License line (e.g. Apache 2.0) belongs in the summary when open-sourcing is the news

## X posts and screenshots

When an X post ID is known and official API auth is unavailable, the public oEmbed endpoint can extract the visible post text and author without credentials:

```text
https://publish.twitter.com/oembed?url=https%3A%2F%2Ftwitter.com%2FUSER%2Fstatus%2FPOST_ID
```

The response includes `author_name`, `author_url`, and HTML with the post text. This is useful for grounding a screenshot-derived ANF item. Do not use `x.com` as final URL if an official/company/project page exists.

## Self-reported research/product claims

For items based on a tweet thread or screenshot, keep the summary careful:

- Use “says,” “claims,” or “reportedly” unless independently verified.
- Summarize the AI relevance, not every technical claim.
- Prefer a company/project page as final URL; otherwise leave `URL:` empty if only X is available.

### AI-generated programming versus advertising

Do not infer that a service's commercials are AI-generated merely because its programming is AI-generated or because it is described as ad-supported. Verify the ad breaks separately through the service description, direct observation, or credible reporting. If coverage observes conventional ads promoting traditionally produced titles, correct the viral shorthand explicitly and neutrally rather than repeating “AI-generated commercials.”

### Desktop imports and cross-agent synchronization

For announcements about importing projects, chats, skills, plugins, or other agent state:

- Distinguish a one-time import from optional automatic updates or bidirectional synchronization; do not call the feature “sync” unless the source documents continuing updates.
- Report where the control lives, which desktop app surfaces receive the imported work, and whether availability is desktop-only.
- If the exact announcement exists only on a forbidden OpenAI/X URL and compliant coverage has not caught up, leave `URL:` blank. A related desktop-app article can provide policy-compliant imagery, but must not be stretched into source evidence for the import feature.

## Math / science “AI solved X” headlines

- Prefer major science press (New Scientist, Nature news) over social reposts; X announcement alone is not a final URL.
- Neutralize “proven false / solved” in the title when community verification is still in flight — e.g. “Uses Claude Fable 5 on Jacobian Conjecture” not “Jacobian Conjecture Proven False By AI.”
- In the summary: name the human researcher, the model as helper, what was posted (e.g. hand-checkable counterexample), and that scrutiny/confirmation is ongoing when that is still true.
- Do not over-claim sole AI authorship if the post credits a human collaborator plus the model.

## Live leaderboards (Arena, etc.)

1. Open the live leaderboard category (e.g. WebDev / Frontend Code), not only secondary blog posts.
2. Capture rank, score, comparator model/score, and any “preliminary” wording.
3. Secondary articles (OfficeChai, etc.) are fine for narrative + images if the leaderboard itself is awkward to screenshot; still ground numbers on the live board when possible.
4. Crowdsourced ranks can change—say so briefly when scores are preliminary.

## Regulatory / policy items

- Prefer state wire or major national press (Xinhua English, ABC, WSJ) over thin aggregators.
- Distinguish: total ban vs minors-only ban vs “must not encourage emotional reliance” vs crisis-intervention duties.
- Effective date and who must comply (platforms/companion bots) belong in the summary when known.

## Research papers (arXiv)

- Use `arxiv.org/abs/...` as URL (compliant).
- Prefer `arxiv.org/html/...` figures (e.g. method diagrams) over generic site chrome.
- Phrase results as author-reported findings.

## Hardware / vehicles marketed with AI

- Check whether “parks itself / runs errands” is teleoperation (remote human) vs autonomy.
- Capture speed class (e.g. 25 mph LSV), range, price, and road restrictions when they define the product.
- Company FAQ often contradicts press shorthand—read both.

## Weak or generic Open Graph images

Replace when `og:image` is:

- A default publisher logo (Yahoo Finance default mark)
- A tiny app icon when a full product screenshot exists
- Unrelated stock art when a paper figure or launch hero is available elsewhere on the same story

Keep the best compliant article URL; swap only the image.

## Example: garage biotech / PAC-832

A screenshot showed Tanishq Mathew Abraham quoting Douglas Yao’s PAC-832 thread. Useful extraction path:

1. Use vision/OCR to capture visible entities: Douglas Yao, PAC-832, Alzheimer’s, GalR1 antagonist, Opentrons OT-2, Claude Code, ChatGPT Pro.
2. Use X Search to identify the original thread and corroborate details.
3. Use `publish.twitter.com/oembed` for the original post text when a post ID is available.
4. Use `https://pacepharmaceuticals.com/` as the final URL instead of X because it is the project/company page.
5. Use cautious wording because the drug-development claims are self-reported and preclinical.

## Example: Kimi K3 docs URL

User supplied `platform.kimi.ai/docs/...` (blocked `.ai`). Path:

1. Extract specs from the docs page or browser text dump (2.8T params, 1M context, KDA, weights-by date).
2. Final URL → independent coverage (e.g. Tom’s Hardware) or non-`.ai` official blog if available.
3. Image → press hero or model card art, not a thin docs `og.png` if a better story image exists.

## Example: Grok for Excel paste

User pasted “Grok for Excel is live” + `x.ai/grok/excel`:

1. Do not emit `x.ai` as `URL:`.
2. Resolve Microsoft Marketplace product page; confirm sidebar agent, financial models, plan gates.
3. Image → Marketplace Excel hero screenshot on `catalogartifact.azureedge.net`.

## Example: Axios China open-source / Kimi policy piece

User supplied a heavily tracked Axios URL (`utm_*`, `mrfcid`):

1. Canonicalize to `https://www.axios.com/2026/07/20/ai-us-china-open-source-kimi`.
2. If Axios CF-blocks fetch, pull body via jina reader; OG via microlink.
3. Discard stale generic OG if present; use same-story Kimi press photo when better.
4. Summary frame: reported consideration / momentum toward restrictions — not an enacted ban — and note competing open-competition critiques when central to the piece.

## Example: OpenAI long-horizon safety post

User URL `openai.com/index/safety-alignment-long-horizon-models/`:

1. Forbidden final URL → blank `URL:` if no independent write-up yet.
2. Image → OpenAI `ctfassets` SEO/hero asset from the page.
3. Summary: internal long-running model failures (sandbox escape, trajectory workarounds), pause, new monitoring, limited restore — attributed to OpenAI.

## Example: same-day ChatGPT Voice on desktop paste

User paste: Voice in desktop app; control computer; direct Work/Codex agents; GPT-Live; macOS/Windows; named paid plans.

1. Confirm via X Search / help echoes; do not invent unstated free-tier access.
2. `openai.com` / `help.openai.com` cannot be `URL:` → blank until independent coverage exists.
3. Image → GPT-Live Contentful hero (`images.ctfassets.net/...`) from the related GPT-Live post.
4. Summary attributes company rollout; full-duplex speak/listen; agent/computer-control claims as stated.

## Example: Claude voice model + connectors update

User paste: voice uses Opus/Sonnet; mid-conversation email/calendar tools.

1. Prefer live help doc `support.claude.com/en/articles/...-use-voice-mode` when it documents model picker + connected tools (Gmail, Calendar, etc.).
2. Note plan limits on connectors if the doc states them; only mention Fable-unavailable-in-voice if central and confirmed.
3. `claude.ai` is blocked by `.ai`; help/product on `support.claude.com` or `claude.com` is fine.
4. Intercom help OG images are often generic logos—acceptable last resort; prefer story UI art when available.

## Example: Fireworks Kimi K3 vs Fable routing study

User paste mirrors a `fireworks.ai/blog/...` post (blocked `.ai`).

1. Find Fireworks AI official LinkedIn post with the same ~1,000-task / 93% routing claims.
2. `URL:` → LinkedIn activity URL; image → LinkedIn feed asset if it resolves.
3. Attribute metrics to Fireworks; treat as vendor benchmark, not neutral SOTA proof.

## Example: White House distillation accusation (Kratsios / Moonshot)

1. Do not use the X post as `URL:`.
2. Use secondary coverage that quotes the statement.
3. Title/summary: “accuses” / “says the U.S. has information…” — not “stole” as settled fact.
4. Include GB300/Thailand chip claims only as part of the official statement when reported.
5. Story image: Moonshot/Kimi event photo from press when wire OG is weak.
