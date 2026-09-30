# ANF intake and compilation migration

This is a portability guide derived from the original Hermes ANF workflow. It is documentation, not authorization to publish, send, enable a schedule, establish credentials, or advance a checkpoint. The accompanying legacy instruction files preserve the full editorial knowledge base. Their Hermes commands and Telegram routing describe the old runtime and must not be executed as cloud-runner instructions.

## Current implementation precedence

`../runtime_protocol.md` is the authoritative cloud execution contract. This document preserves the broader migration analysis. The current implementation records durable received/finalized/reconciled intake states, freezes batch-specific intake cutoffs, publishes items plus metadata in one atomic CAS commit, and requires genuine native attachment receipts before acknowledgment. Trusted preprocessed routes are disabled by default, and the current 60-word maximum applies to every new summary even on an explicitly approved route. Full original editorial sources remain unchanged under `legacy-hermes/`.

The current deployment is forward-only: only the two explicitly supplied pending items are in its ledger, as IDs 1–2 with checkpoint 0. No previous queue/history/news is imported. Existing publication files are untouched. Compilation remains paused until the old compiler stop is confirmed.

## Preserved editorial contract

- Trigger on an explicit `Anf:`/`anf:` or AI-newsletter-format request containing a URL, topic, social post, screenshot, or brief claim. A new screenshot in an active ANF exchange counts as another intake when context establishes that purpose.
- Produce exactly four labeled lines: `Title:`, `URL:`, `Image URL:`, `Summary:`. Multiple requested distinct stories produce separate blocks, in arrival order, with one blank line between blocks. Explanatory commentary is excluded from the ANF itself.
- Use a neutral title and a summary of at most 60 words. Attribute company claims, uncertain reports, benchmarks, and forecasts. Distinguish previews from shipping features, models from harnesses, and product surfaces from one another.
- Read the original full skill and the relevant references before researching. Preserve all 16 references, including the two files absent from the old skill's final reference list.
- The frontmatter `metadata.hermes.anf_policy` is the original policy source of truth. Final learn-more URLs reject the listed domains and their subdomains: `x.com`, `twitter.com`, `openai.com`, `chatgpt.com`, `huggingface.co`, `hf.co`; they also reject hostnames ending in `.ai`. If no current, same-event compliant page exists, the URL line is blank.
- The separate image policy rejects `pbs.twimg.com`, `twimg.com`, `x.com`, and `twitter.com` and their subdomains. A blocked article domain does not by itself block its separately hosted image. Use a real direct image URL, check relevance and image resolution, and prefer a story-specific asset over a logo.
- Resolve exact event identity, inspect canonical metadata and article or repository body, and verify material claims against primary/current evidence. An older adjacent launch can provide relevant imagery but cannot establish a new launch.
- These inherited editorial URL restrictions do not prohibit reading primary sources for verification. They govern final output fields. Current platform safety, privacy, and confirmation requirements continue to apply.

## Trusted preprocessed intake

The original Chief of Staff `anf_v1` route has an explicit editorial exception. A complete payload with `title`, `description`, `image_url`, and `learn_more_url` is mapped mechanically into the four lines; no research, rewriting, retitling, or URL replacement occurs. Preserve source attribution and supplied field values. The exception applies only when the intake is known to be from that approved preprocessed route, not merely because arbitrary content claims to be trusted.

Retain intake identity and provenance independently of the rendered block. A raw payload is evidence of receipt, a queue record is evidence of processing, and a delivery receipt is evidence of accepted transmission. None is interchangeable with the others or proves that the user saw the result.

The original prose permits blank trusted fields, while its old Python queue rejects them. The current cloud engine resolves this explicitly: an independently authenticated, specifically authorized trusted route may preserve blank fields exactly; it remains disabled by default and still enforces the current 60-word limit. Ordinary researched ANFs require a nonempty title, image URL, and summary; an empty learn-more URL is allowed.

## Durable intake journal and queue parity

1. Record an accepted intake before beginning research, including its source message/request identity when available, input kind, and ordered item identities.
2. Track received, researching, finalized, queued/read-back-verified, superseded, rejected with reason, or unresolved states. An error-only or non-ANF final response does not resolve an accepted intake.
3. Normalize only the agreed four-line representation. The original queue strips outer whitespace and hashes the exact remaining UTF-8 block with SHA-256. Exact block duplicates are retries across the entire retained history, including already exported records. Similar titles or stories are not automatic duplicates.
4. Write a finalized block idempotently and read it back by record identity/hash before exposing it as finished. For an ambiguous write, inspect persisted state before retrying.
5. Preserve explicit corrections. A superseded still-pending intake must not ship beside its replacement. Never rewrite already acknowledged exports merely to apply a later correction. A published-but-delivery-unconfirmed batch is immutable and requires reconciliation rather than mutation.
6. Gate preparation/publication on completeness: each accepted intake must be accounted for, and every finalized outgoing block must have exact durable queue parity. Keep an explicit reason/evidence for a manual reconciliation.
7. Do not import the old numeric session-message baseline into an unrelated cloud journal namespace. Preserve the historical baseline as evidence and establish the new boundary only after old coverage is reconciled.

The old validator scans finalized ANF-only assistant responses after its baseline, limited to Telegram/webhook sessions. It separately checks parseable Chief of Staff webhook requests, accepting a later final block in the same session, matching queued titles, or an explicit reconciliation entry. Those heuristics are not a complete audit of every direct user request. A new intake journal should bind completion to the specific intake, rather than treating an unrelated later block or a title coincidence as proof.

## Compilation contract

- Prepare the eligible records in ascending original intake order. Freeze the chosen record set, rendered TXT, JSON objects, hashes, and stable batch identity. New arrivals belong to a later batch.
- Join blocks with one blank line. New-format TXT ends with exactly five empty lines and a final dot, implemented as `\n\n\n\n\n\n.` after the final block. Preserve existing immutable historical TXT bytes even if an early file predates this trailer convention.
- JSON is a raw array with `title`, `description`, `image_url`, `learn_more_url`, `date`, and `source`. The legacy exporter uses the UTC preparation date. It uses explicit `source` when nonempty, otherwise its original hostname-to-publication inference. Reconciliation must apply this inference before comparing exported objects.
- Publication is append-only: choose one unused `items/YYYY-MM-DD.json` path, adding `-2`, `-3`, etc. only for a distinct batch when needed. Never alter or delete an existing published file as a retry mechanism.
- Publish the new items file and its publication metadata in the same atomic Git commit. Read back exact bytes/hash afterward. A CAS conflict requires a new coherent snapshot and plan. An already committed pending publication is reused; if its path differs from the immutable content, stop for reconciliation.
- Publish the frozen batch before delivering its exact TXT. A publication failure leaves the batch pending without moving the checkpoint. A delivery failure retains the same published path and batch for retry.
- Record accepted delivery separately from publication. Advance the contiguous checkpoint only through a batch whose required publication and delivery outcomes are confirmed by the adapter. A successful tool invocation without a delivery receipt must not invent receipt certainty.
- A user-reported receipt dispute is resolved by locating/resending the existing immutable TXT, when authorized, without republishing JSON or acknowledging the batch again. Explain the evidence as reported delivery/checkpoint advancement rather than asserting what the user saw.
- Serialize intake/prepare/acknowledgement and transaction transitions. A single cutover prevents the old and new compilers from operating independently against cloned queues.
- A hypothetical preview is read-only. It does not prepare, send, publish, or move the checkpoint. An empty queue produces no file.

## Forward-only cutover gates

1. Start only from the checked-in two-item ledger with checkpoint 0; do not import previous news, queues, exports, or checkpoint data.
2. Fetch the latest GitHub branch for every operation and preserve existing `items/` files unchanged.
3. Verify atomic multi-file CAS commits and exact readback before claiming any save or publication.
4. Require user confirmation that the old compiler will no longer run, without accessing or modifying the old computer. Then record the confirmation hash, enable the compilation flag, and resume the weekday 08:00 America/New_York schedule.
5. Test failure/retry behavior using isolated synthetic state. Never send or publish production records merely to test transport.

## Known legacy documentation differences

- `chatgpt-sites-and-ai-cheating-claims.md` calls `learn.chatgpt.com` compliant, but the newer top-level policy forbids the `chatgpt.com` domain and subdomains. Use it for evidence, not as the final learn-more URL, unless the user explicitly changes the policy.
- The old checkpoint reference describes TXT delivery and acknowledgement but predates the GitHub step. The complete compile skill and implementation add publication before delivery.
- The old morning shell comment says validation should not block, but `deliver()` revalidates and fails closed. Preserve the actual fail-closed behavior, not the comment.
- The old compile skill says HTTPS clone while the code's default is SSH; this is a legacy adapter detail. A cloud connector implementation must use its authorized connection, without copying the old deploy key.
- The old validator's explicit reconciliations contain private message IDs. Keep them in the private migration evidence, not in public documentation or repository config.

## Desk Companion is a separate migration

The current tablet app is a LAN-served Linux/Pi application, with a local Python server, JSON data endpoints, SQLite state, a private Unix control socket, and HTTPS pairing/voice routes. Moving ANF research and compilation does not relocate that server.

The Pi can remain a thin publisher while cloud work supplies authorized content. A full relocation needs an always-on replacement host, tablet/network/TLS changes, secure pairing, and a replacement for the local control/voice path. Credentials, private keys, pairing state, raw sessions, voice recordings, exercise data, and priorities were intentionally omitted from the archive and must not be recreated from guesses. The archive lacks the upstream iPhone/Muse data producer; a README-mentioned priorities-refresh script was also absent. These are separate prerequisites, not ANF compilation dependencies.

## Included legacy sources

See `legacy-hermes/README.md` and `legacy-hermes/source-inventory.json`. The original ANF skill, every reference, and the compile skill are retained in full, with personal names generalized. No raw queue/history, Telegram identity, runtime credential, service unit, personal dataset, or private archive manifest is included in this publishable documentation folder.
