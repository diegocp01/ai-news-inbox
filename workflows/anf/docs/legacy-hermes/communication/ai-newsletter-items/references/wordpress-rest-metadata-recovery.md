# WordPress REST Metadata Recovery

Use this when a WordPress article renders slowly, browser metadata inspection times out, or the exact canonical slug and lead image are uncertain.

## Procedure

1. Query the site search endpoint:
   `https://<host>/wp-json/wp/v2/search?search=<encoded-query>&per_page=5`
2. Match the result by title/date and record its `id` and canonical `url`.
3. Fetch the post object:
   `https://<host>/wp-json/wp/v2/posts/<id>`
4. Confirm `link`, `title.rendered`, `excerpt.rendered`, publication date, and `featured_media`.
5. Read and verify the article body from `content.rendered`, not only the excerpt. When the browser snapshot collapses the JSON into one huge truncated line, parse the live page body in `browser_console` and convert the HTML to text in the DOM:
   ```js
   (() => {
     const raw = document.body.innerText;
     const data = JSON.parse(raw.slice(raw.indexOf('{'), raw.lastIndexOf('}') + 1));
     const node = document.createElement('div');
     node.innerHTML = data.content.rendered;
     return {
       link: data.link,
       title: data.title.rendered,
       excerpt: data.excerpt.rendered,
       content: node.innerText,
       featured_media: data.featured_media
     };
   })()
   ```
   This avoids copying or locally reparsing a truncated accessibility snapshot.
6. If `featured_media` is nonzero, fetch:
   `https://<host>/wp-json/wp/v2/media/<featured_media-id>`
7. Use `source_url` as the direct image URL; verify `mime_type`, width, and height from `media_details`.
8. Open the direct image URL once to ensure it resolves as an image, and visually check that it is story-specific and contains no misleading overlaid text, before publishing.

## Notes

- Prefer the REST-returned canonical `link` over a guessed headline slug; publishers may shorten slugs after publication.
- The media object is often more reliable than page OpenGraph inspection and exposes the original full-resolution asset.
- Treat `caption.rendered` and publisher-specific caption fields as image labels, not authoritative article facts. Cross-check names, charges, dates, and sentence lengths against `content.rendered`; captions can contain stale copy or simple errors (for example, “months” where the body says “years”). Keep the image if it is otherwise suitable, but do not repeat the erroneous caption.
- Do not assume every WordPress site exposes public REST endpoints. If unavailable, continue with page metadata, sitemap, RSS, or publisher-specific APIs.
- The REST API is source metadata, not independent verification of claims in the article.