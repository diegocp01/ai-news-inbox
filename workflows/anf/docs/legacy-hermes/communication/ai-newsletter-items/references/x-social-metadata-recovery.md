# Recovering Exact X Post Metadata for ANF

Use when an ANF intake quotes an X post but X Search returns a synthesized answer, irrelevant interpretation, weak citations, or only candidate status IDs.

## Workflow

1. Search the distinctive quoted phrase and constrain the date/handle when known.
2. Treat returned status IDs as candidates only; do not publish the search model’s prose.
3. Fetch each candidate with a realistic browser user agent:
   - `https://x.com/i/status/<status_id>`
4. Parse these HTML fields:
   - `og:title` — display name and handle
   - `og:description` — exact post text
   - `og:image` — attached media or profile image
5. Match the exact wording, named people, and demonstrated feature before using the post as evidence.
6. Continue looking for a compliant official cross-post, documentation page, or independent report.
7. Enforce ANF policy: do not output X/Twitter as the final URL or `pbs.twimg.com`/`twimg.com` as the image. If no exact compliant URL exists, leave `URL:` blank. Use verified relevant imagery from a compliant article only as an image fallback—not as evidence that the article covers the same announcement.

## Important Fallbacks

- `https://cdn.syndication.twimg.com/tweet-result?id=<id>&lang=en` may return `{}` even when the public X page exposes useful OpenGraph metadata. An empty syndication response does not prove the post is unavailable; try the public status page HTML before giving up.
- Some public X status pages expose `og:title` and `og:image` but omit `og:description`, especially for posts with large attached media. In that case, query `https://api.fxtwitter.com/status/<status_id>` and inspect `tweet.text`, `tweet.created_at`, `tweet.author`, and `tweet.media`. Use this only as a mirror of the original post—not as independent reporting—and still verify linked product claims against a live official page or current coverage. Never output the mirror, X URL, or mirrored `pbs.twimg.com` media when policy forbids them.

## Framing Examples

- `/visualize`: call it a built-in Codex skill or workflow shortcut; report the exact demonstrated output, such as turning a pinned travel thread into an interactive schedule.
- Screenshot-only mini-apps: identify the exact label (for example, “App Blocks”), describe only visible interactions, say “appears to show,” and do not infer rollout details.
