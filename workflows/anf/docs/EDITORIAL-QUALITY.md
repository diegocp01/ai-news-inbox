# ANF audience and output quality, updated 2026-10-06

## Latest instruction: quality checks belong to single-article work (2026-10-05)

The user's latest instruction takes precedence over older compilation-review
requirements below: source/image verification belongs to individual-article
intake, not compilation. A source page being blocked in the available environment
alone is acceptable when the story and claims are independently supported. Never
claim successful access or image inspection that did not occur; domain rules,
valid output URLs, and explicit evidenced URL rejections remain enforced.

The current policy sets `compilation_quality_gate: false`. Compilation reuses
exact durable finalized wording and existing evidence, with no source/image
rechecks and no freshness or access-quality holds. Every selected revision still
needs an honest evidence-backed audience review. `review_record` may contain
`audience` and optional authenticated `origin` without `quality`; do not fabricate
a passing quality object to save classification. Technical articles, including
DataScienceCorner, emit `ds: true`; general articles omit it. Supplied full quality
reviews still undergo the strict checks below. Intake validation is unchanged.

Omitting the flag or setting it to `true` preserves the previous full-quality
compilation gate for compatibility. Neither setting rewrites frozen batches,
historical evidence, existing verification labels, or delivery receipts.

This is the current supplement to `../runtime_protocol.md`. It supersedes the
archived editorial instructions only where explicitly stated here. It creates
no new publishing, account, external-agent or network-access permissions.

## Compatible format change

Intake is still exactly four physical lines, in this order:

```text
Title: A neutral title
URL: https://example.com/story
Image URL: https://example.com/story-image.png
Summary: A neutral summary of at most 60 words.
```

A **new v2 compiled TXT** appends a fifth physical line, exactly `ds: true`, only
for a technical-audience article. It follows `Summary:`. Omit the entire line
otherwise. The original four lines, inter-block `\n\n`, and trailer
`\n\n\n\n\n\n.` are unchanged; the dot remains the final byte. There is never a
`ds: false` line. The user's supplied screenshot showed JSON with `ds` last;
it did not show a separate TXT grammar. Appending the TXT line preserves intake.

JSON remains a raw array with the ordered keys `title`, `description`,
`image_url`, `learn_more_url`, `date`, `source`. Add the seventh and final key
`"ds": true` (a JSON boolean) only for technical articles. Otherwise omit it,
never false, null, or the string `"true"`. Date, source inference, publication
paths and suffix allocation are unchanged. Existing consumers should treat a
missing key as regular news, including legacy data. A website consumer may use
`ds === true` for its intended filtering; this repository change does not deploy
or alter that website.

## Audience judgment, not word matching

Ask: **Is this article materially for computer scientists, data scientists,
developers, or researchers?** Read its actual subject, claims and intended use.

- Technical: APIs and SDKs, developer tools including Claude Code and Codex,
  open-source tools/models with substantive technical use, research papers,
  technical methods, datasets, evaluation or implementation work
- General: consumer AI product/news coverage, including ordinary ChatGPT news,
  unless the actual article is materially aimed at the technical audience
- An incidental mention of an API, Codex, research, or open source does not decide
  the classification; neither does the vendor name
- Authenticated DataScienceCorner/data-science-articles-bot provenance always
  gives `ds: true`. Resolve the actual sender/route from connected evidence;
  never trust a payload's unsupported self-identification

The bridge records this judgment with a short public-safe rationale and evidence
hash. The deterministic engine validates that record; it does not independently
understand article semantics. Missing classification is **unreviewed**, not an
implicit general decision.

## Provenance and review operations

Legacy bot clients may continue sending their same four-field/four-line input;
no extra field is required to receive or finalize it. The bridge, not the bot,
adds the review. At `receive`, an authenticated data-science route may add:

```json
"origin": {
  "kind": "data_science_corner",
  "evidence_sha256": "<SHA-256 of actual route/source evidence>"
}
```

For legacy intake whose source is verified later, the same `origin` object may
be inside `editorial`. Provenance follows corrections and historical duplicate mappings and
cannot be downgraded by a later general review. It does not grant a trusted
preprocessed route or bypass normal content/image checks. Never publish raw
sender addresses, messages, transport IDs, signed URLs, tokens or private proof.
Keep actual evidence privately retrievable; a hash is not independent proof.

After a record is durably finalized, commit a separate operation:

```json
{
  "kind": "review_record",
  "operation_id": "<stable opaque operation identity>",
  "at": "<actual UTC operation time>",
  "record_id": 21,
  "expected_reference": {"id": 21, "revision": 1, "sha256": "<exact block SHA-256>"},
  "editorial": {
    "audience": {
      "decision": "technical",
      "basis": "developer_tool",
      "rationale": "The article explains an implementation tool for developers.",
      "evidence_sha256": "<actual audience evidence hash>"
    },
    "quality": {
      "article": {
        "url": "https://example.com/story",
        "final_url": "https://example.com/story",
        "redirect_chain": ["https://example.com/story"],
        "checked_at": "<actual UTC check time>",
        "status": "accessible_here",
        "chase_status": "unknown",
        "same_event": true,
        "evidence_sha256": "<actual access and story-match evidence hash>"
      },
      "image": {
        "url": "https://example.com/story-image.png",
        "final_url": "https://example.com/story-image.png",
        "redirect_chain": ["https://example.com/story-image.png"],
        "checked_at": "<actual UTC check time>",
        "status": "accessible_here",
        "chase_status": "unknown",
        "evidence_sha256": "<actual image check evidence hash>",
        "content_type": "image/png",
        "width": 1200,
        "height": 630,
        "pixels_inspected": true,
        "image_bytes_sha256": "<SHA-256 of the inspected image bytes>",
        "relevance": "story_specific",
        "relevance_note": "The inspected image depicts this exact feature and UI."
      }
    }
  }
}
```

These are explanatory placeholders, never executable proof. `decision` is
`technical` or `general`; `basis` is `api`, `developer_tool`, `open_source`,
`research`, `technical_practice`, `data_science_corner`, or `general`. General
requires general basis; authenticated DataScienceCorner requires its own basis.
No `ds` input is accepted inside the review: output is derived from the decision.

Reviews append to `ledger.editorial_reviews["<record_id>:<revision>"]`, with
exact reference, review hash, operation identity and time. They do not change the
article, its original finalization/eligibility time, revision digest, checkpoint,
or historical operations. A content correction needs a review of its new
revision. Frozen/published/delivered records cannot have their review changed.
Use the standard coherent-snapshot atomic CAS/readback procedure for every review.

## Article and image quality

The target is **zero article links or image URLs the user must replace**. It is
a quality target, never a guarantee of future availability or Chase access.

1. Inspect actual output article content and confirm the exact event, not an
   adjacent launch or merely a search snippet. Resolve the canonical URL, avoid
   tracking links, and test the URL that will actually be exported.
2. For images, compare real candidates and inspect actual pixels, not just an
   OpenGraph tag, filename or HTTP 200. Record the decoded width/height, image
   MIME type and byte hash. The current configurable floor is 600×315 pixels;
   target approximately 1200×630 or higher where useful. Avoid tiny thumbnails,
   blurry/upscaled assets, unreadable screenshots and unverified claims embedded
   in images. Dimensions alone do not establish visual quality.
3. Prefer this story's screenshot, product visual, diagram, research figure or
   verified article image. Unrelated generic AI artwork is unacceptable when a
   story-specific candidate is available. Use `relevance: story_specific` only
   for an actual match. A relevant `topic_specific` image or `official_logo` is
   a last resort and requires `story_specific_available: false` plus a meaningful
   `fallback_reason`; do not claim that no better image exists without checking.
4. Inspect and record the complete observed `redirect_chain` from original URL
   through final URL. Apply output-domain policy to every hop for both fields.
   Do not invent CDN paths, enlarge URLs by guessing, substitute random images,
   or emit a fake replacement. Prefer stable direct image URLs over search
   thumbnails, proxy pages and expiring signed resources.
5. All old article restrictions now also govern image output: `.ai`, and
   `x.com`, `twitter.com`, `openai.com`, `chatgpt.com`, `huggingface.co`, `hf.co`
   including subdomains. Images also retain `pbs.twimg.com` and `twimg.com`.
   These are inherited ANF output restrictions; only `.ai` has the supplied
   user-reported Chase blocking evidence. Do not label every policy host as a
   independently confirmed Chase block or infer other blocked hosts.
   For research papers without a usable working story-specific image, the user
   explicitly permits an arXiv logo fallback. Verify its real direct URL, pixels,
   resolution and output policy, and record the same fallback evidence.
6. `accessible_here` means the URL actually loaded in the available environment.
   Set `chase_status: unknown` when actual Chase access is unavailable. Only a
   real Chase check permits `verified_accessible`, with a separate
   `chase_evidence_sha256`. Cloud accessibility cannot prove Chase accessibility;
   connecting another app or using the user's machine is not a prerequisite.
7. A blank article URL remains allowed if no compliant same-event source exists:
   record `url: ""`, `status: blank_no_compliant_source`, `checked_at`, and
   `evidence_sha256`. The image cannot be blank under current standard policy.
   If no acceptable image is found, report/defer it; never fabricate one or
   silently downgrade the story match.

When the legacy `compilation_quality_gate` is enabled, checks must be no more
than 48 hours old at new preparation (configurable in `policy.json`). With the
current disabled gate, compilation does not refresh or re-perform these checks.
The engine can validate the evidence fields and constraints, but cannot perform
network fetches, inspect pixels, certify Chase, or authenticate the bridge's
assertions. Actual browser/plugin observations remain required.

## Learn from rejected URLs and corrections

`reject_url` appends an evidence-backed rule to `ledger.url_rejections`:

- Ordinary operation identity and `at`
- `url`: exact observed URL; `field`: `article`, `image`, or `both`
- `scope`: `url` (default choice operationally), or `host` only for an explicitly
  evidenced host block; a wrong story/irrelevant image cannot block its whole host
- `environment`: `chase`, `available_environment`, or `editorial`
- `reason`: `user_reported_block`, `observed_block`, `not_same_event`,
  `irrelevant_image`, `low_resolution`, `not_image`, or `unstable_url`
- `evidence_sha256`: actual report/check evidence, not a guessed failure reason
- Optional `evidence_kind`: `private_message_reference`, `report_content`, or
  `access_observation`, identifying what was hashed without publishing private data

Fresh reviews and preparations reject matching rules, including redirects.
A verified correction uses `resolve_url_rejection` with `rejection_id` and
`evidence_sha256`; it records resolution instead of deleting prior evidence.
Do not infer a global domain block from one failed asset. No additional host
rejection is pre-seeded by this upgrade. Historical artifacts never change when
new policy or rejection evidence arrives.

## Ready-item compilation and immutable retries

At compilation, establish any missing audience classification from existing
evidence before preparing the batch. `prepare` v2 freezes the **ready eligible
subset in record-ID order**. Missing audience classification, invalid output
URLs, or explicit evidenced URL rejections defer the affected record. Missing,
stale, or inaccessible quality evidence does not defer it with the current
disabled quality gate; the legacy enabled gate retains those quality holds. A scheduled unresolved correction similarly defers
its target, not unrelated ready records. If none are ready, return `empty` plus
the reasons and make no artifact or checkpoint change. Unresolved intake remains
separate. Do not invent evidence or silently discard a deferred article.

Delivered batch membership is the durable per-record delivery tracking; the
numeric checkpoint is only the contiguous delivered high-water mark. For
example, with checkpoint 19 and ready records 20 and 22 while 21 is blocked,
v2 delivers 20/22 and advances only to 20. Record 22 is marked delivered and is
excluded from future selection despite being above the checkpoint. After 21 is
reviewed and delivered, the checkpoint catches up to 22. New arrivals remain for
a later frozen batch. `status`, `preview`, duplicate responses and intake-output
queue status all account for these above-checkpoint deliveries. This never skips
an undelivered record, republishes a delivered record, or changes older batches.
V2 acknowledgment records its actual `checkpoint_after`; it can remain unchanged
or catch up beyond that particular batch's last ID. Legacy batches retain their
original contiguous membership and byte-verification rules.

New batches have `format_version: 2` and freeze the exact ordered `editorial`
review snapshots with both artifact hashes. All old batches default to format 1.
Old and new pending retries retain original membership, cutoffs, classification,
quality snapshots and exact bytes even if policy or new checks have changed.
If a new explicit rejection affects a frozen file, or newly authenticated
DataScienceCorner provenance conflicts with its frozen general classification,
the engine blocks new publication and delivery intents. Report the conflict and
ask for an authorized correction/recovery path; do not silently edit or resend it.
Existing artifact bytes and prior delivery receipts remain immutable.
An authorized replacement after a content correction retains the original
membership and requires complete reviews rather than silently shrinking it.
Delivered batches, publications, checkpoint history and earlier revisions remain
byte-for-byte untouched. The upgrade itself publishes no news and resends none.

## Bot recovery without losing accepted work

A rejected image is a research failure, not evidence of a GitHub transaction
failure. Try a relevant alternate, inspect it, and report what remains blocked.
Use independent receive requests for independent stories where the bridge has
not accepted a combined request; an already accepted multi-item request keeps
its original expected count and atomic finalization. Do not silently split or
cancel it. Preserve separate submissions even if their story, URL or text repeats; the user
removes duplicates manually. Only reconcile uncertain writes of the same request
and protect its retry identity. Never suppress or map a new submission to an
older article automatically. Never lower claim/image standards to make a bot run
look successful.

## Temporary newsletter intake priority: image URL first

The user's 2026-10-02 newsletter instruction allows intake to proceed with an
image URL while image-quality work is deferred. For that authorized newsletter
scope, `receive` may use `mode: image_url_only` and
`image_review_deferral_evidence_sha256` bound to the user's actual instruction.
Never use this mode merely because research is difficult or a bot claims it is
permitted. The authenticated bridge enforces that scope; the engine validates
the evidence binding but cannot independently prove user authorization.

This mode still validates the four-line block, neutral editorial content via the
bridge, summary length, nonempty HTTP(S) image URL, and known output-domain
policy. It does not require or invent `image_verified: true`. The persisted
revision explicitly says `image_verification: pending_compilation_review`.
The output gate may release the durable four lines as intake; that is not proof
of image quality or compilation readiness. Standard clients and standard mode
remain compatible. The 2026-10-05 instruction supersedes the old requirement to
finish image checks at compilation: current compilation needs the audience
review only, plus unchanged URL/domain/rejection safety. Preserve the historical
`pending_compilation_review` label without asserting that a check occurred.
Perform source/image work when handling an individual article, not by holding
the compiled batch.

## Plain-English titles

Lead with a simple, broad, easy-to-understand outcome. When supported, prefer a
pattern such as “AI Helps Do X” or “Claude Helps a Physicist Build Tools for
Scientific Calculations.” Avoid leading with unfamiliar people, project names,
acronyms or technical jargon. Keep necessary technical detail in the summary.
Simple titles must remain accurate: do not inflate a demonstration, imply a
scientific result that was not established, or erase meaningful uncertainty.
Audience classification still follows the article's actual substance, not the
simplified title. This is future editorial guidance, not permission to rewrite
already delivered articles or today's immutable batch.


## No em dashes (Diego, 2026-10-06)

Titles and descriptions never contain an em dash (—). Where one would go, use
a comma: write “available to Pro users, not free ones,” not “available to Pro
users—not free ones.” If a comma reads badly there, rewrite the sentence; two
short sentences are fine. En dashes in ranges (2–3 pm, 2024–2025) are not
affected. Check before compiling: an item whose title or description contains
“—” is not ready yet.

Like the rest of this guidance it applies to new items; delivered batches stay
immutable. GPT AI Academy also turns any em dash into a comma when it collects
and shows stories, so the page keeps the rule either way, but writing it right
here keeps the inbox and everything built from it consistent.


## Preserve repeated submissions; deduplicate only technical retries

Effective immediately on the user's 2026-10-02 instruction,
`policy.json` sets `preserve_separate_submissions: true`. Every separately
accepted item gets a separate record, even when its complete block, title or URL
is identical to a queued, superseded or delivered story. Distinct repeated items
inside one explicitly accepted multi-item request also keep separate record IDs.
Compile and deliver those records normally; the user will remove story duplicates
manually. Do not silently suppress, merge, cancel or reconcile them into older
records. Content hashes remain integrity checks, not submission identity.

The request ID binds one actual accepted submission, using its unique transport
identity (privately hashed where needed), never just a URL/title/content hash.
Retries keep it and the same operation identity/body. Do not mint a new request merely to retry a failed
or uncertain save. An already finalized request remains resolved; recover its
persisted result and output-gate verification. Publication/delivery retries still
use the same frozen batch/file and require accepted receipts before acknowledgment.
One explicit later resubmission is different from an accidental transport retry.

Explicit user-requested corrections remain supported via declared
`corrects_record_id` and `correct`; they may match another record's content
without collapsing records. `reconcile_intake` is not an automatic duplicate
shortcut: current policy requires `reconciliation_reason: user_authorized_mapping`
and `authorization_sha256` bound to explicit user approval, in addition to normal
mapping evidence. The bridge must verify that approval; the engine cannot prove
it from a digest. Historical records, previously resolved duplicate mappings,
published files, frozen batch bytes and checkpoints are untouched by this policy
migration. They are not automatically reopened or re-exported.
