# ANF cloud ledger runtime protocol

## Deployment state

This is a forward-only ANF workflow. The user's latest instruction excludes all old queue/history/news migration. The initial ledger contains only the two explicitly supplied pending ANFs as IDs 1 and 2, with checkpoint 0, no prior records, no checkpoint history, no imported exports, and no prepared batch. Existing repository `items/` files remain untouched.

The authorized GitHub integration has successfully created and read back a proof file. Atomic multi-file CAS commit behavior still must be honored and verified when deploying this package and at every later operation. No worker in this package writes GitHub or accesses the old machine.

Compilation was initially paused. The current `runtime_config.json` now contains `compilation_enabled: true` and the SHA-256 digest of the user's cutover confirmation. The cutover gate remains enforced by the engine; scheduler state must be checked separately. Never visit or modify the old computer to infer or reconfirm that confirmation.

The intended schedule is Monday–Friday at 08:00 America/New_York, including DST. A paused schedule has no actual next run. The engine itself contains no scheduler, GitHub client, sender, machine access, or credentials.

The two initial records preserve exact user-supplied finalized blocks and source labels. They are explicitly marked as finalized seeds, with evidence hashes and no assertion of a fresh image check. Future researched intake uses all normal validation requirements.

## Files and ownership

Repository: `diegocp01/ai-news-inbox`, branch `main`.

- `workflows/anf/ledger_engine.py`: pure Python 3 standard-library state/commit-plan engine
- `workflows/anf/intake_output_gate.py`: read-only deterministic final-intake-output verifier; no network, writes, or credentials
- `workflows/anf/policy.json`: authoritative machine-readable final URL, image-host, and 60-word limits
- `workflows/anf/runtime_config.json`: explicitly approved trusted-route hashes; empty/disabled by default
- `workflows/anf/ledger.json`: authoritative durable queue, ingress ledger, revisions, pending batches, delivery attempts, operations, and checkpoints for this new forward-only queue
- `workflows/anf/batches/<batch_id>.txt` and `.json`: immutable frozen batch bytes
- `items/YYYY-MM-DD.json`, then `-2`, `-3`, ...: consumer-facing publication arrays only
- `workflows/anf/tests/`: isolated synthetic tests
- `workflows/anf/docs/`: sanitized full editorial intake instructions and references, with provenance

Use the current GitHub branch contents as the source of truth. Local files are expendable caches. Do not restore stale local state over GitHub or consult a disconnected machine as an alternate state source.

## Non-negotiable outer transaction contract

The planner does not perform a commit. A successful Python exit, an output file, or `publication_planned` is not a successful save/publication/delivery. The connector/orchestrator must implement all of the following:

1. Read `main` HEAD and its complete tree. Fetch every blob under `workflows/anf/` and every existing `items/*.json` path/content needed for collision detection and publication verification, all at that same immutable commit SHA. Detect truncated listings and paginate or fetch full subtrees. A branch's current directory listing mixed with older blobs is not a coherent snapshot.
2. Supply `{ "head": "<commit-sha>", "complete": true, "files": { "repo/path": "exact UTF-8 content" } }`. The `complete` flag is an assertion by the bridge, not something the planner can independently prove.
3. Generate a plan for one operation. The operation has a stable opaque `operation_id` and an explicit UTC `at` timestamp. Reuse the exact same operation body/ID when checking an ambiguous save. Never regenerate its timestamp under the same ID.
4. Create every changed blob and one tree containing **all** `changes`. Use the observed tree as the base so unrelated repository files are preserved. Create one commit whose sole parent is exactly `base_sha`. Update `refs/heads/main` using a real expected-head comparison, or a non-force Git ref update that rejects a candidate whose parent is stale. Do not perform separate Contents API writes for individual changed files, force a ref, merge a stale planned ledger, or use a connector that cannot guarantee atomic multi-file publication.
5. If another writer advances HEAD, discard the old plan, fetch a new complete snapshot, and re-plan the same operation. Operation deduplication prevents double application if the original operation already committed. For a truly rejected old operation whose timestamp now predates a newer committed operation, create a new retry operation ID/timestamp only after verifying the old ID is absent; preserve the same request/attempt identity. A `403` is a permission blocker, not a CAS conflict, and is not permission to try another identity or route.
6. Read back the committed ledger and every changed artifact at the confirmed new commit, then confirm that commit is still on `main` (or an ancestor of its current HEAD). Verify exact bytes/digests and the operation entry. A lost response requires this reconciliation before any retry. Do not infer success from a generated commit object that never reached the branch.
7. Report any failed durable save to the user. Keep the intake unresolved and do not emit a polished final ANF or a success claim when its final block is not durably verified.

The planner's `send_authorized` is always false. Sending is exclusively an outer-bridge decision after the transaction/readback procedure below. A replay response has `status: operation_replayed`, `original_result`, and current state. It must never trigger a send by replaying an old delivery intent.

## CLI

```sh
python3 workflows/anf/ledger_engine.py --input request.json --output commit-plan.json
python3 -m unittest discover -s workflows/anf/tests -v
```

Input file:

```json
{
  "snapshot": { "head": "0000000000000000000000000000000000000000", "complete": true, "files": {} },
  "operation": { "kind": "status" }
}
```

The illustrative empty `files` map is intentionally not executable: it must include the actual policy/configuration and live ledger/artifacts. Do not use the zero SHA against production. `status` and `preview` are read-only and do not prepare or deliver. Preview reports only durable state, not evidence that the entire external inbox was ingested.

Mutations also require `operation_id` and `at`, for example `2026-10-01T12:00:00+00:00`. Persisted operation chronology cannot go backward. All operation IDs/request IDs/attempt IDs should be opaque hashes of private transport identity, never a raw chat/channel/user identifier.

## Ingress and finalization

1. At the actual accepted intake boundary, commit `receive` with `request_id`, `expected_items`, and optional `mode` (`standard` by default). Every accepted request must be durably received before acknowledging acceptance, beginning research, or scheduling processing. A crash before this save cannot be detected by the engine; the ingress bridge must treat it as failed acceptance and visibly recover/retry.
2. One received sequence is assigned by the atomic commit order. Research may run in parallel, but `finalize`, `correct`, and `reconcile_intake` are blocked while an earlier received intake remains unresolved. This keeps new record IDs in durable ingress order without losing late results. Duplicate requests use the same request ID and do not create another ingress.
3. Research and editorial verification are performed outside the engine. Apply the complete intake skill and relevant references: neutral title/tone, claim/source alignment, a real verified image, and no adjacent unrequested stories. The engine checks four physical lines, the word count, HTTP(S) URL syntax, forbidden domains/subdomains/suffixes, and an explicit image-verification assertion. It cannot verify article truth, image bytes, neutrality, or authenticity itself.
4. Commit `finalize` with `request_id` and exactly `expected_items` entries in `items`: each has `block`, optional public publisher `source`, and `image_verified: true` for standard intake. This is atomic across all items. A malformed second item leaves the entire intake received/unresolved.
5. Read back each exact block, revision, and SHA-256, then run the required executable intake-output gate below before returning it to the user. An exact duplicate anywhere in full revision/history resolves to that existing record without incrementing IDs or requeuing delivered/superseded content. If the matched content is superseded, do not present it as a newly queued current correction.
6. Error-only processing results remain unresolved. Do not silently discard them or move a baseline past them. `reconcile_intake` requires one `record_ids` entry per expected item plus `evidence_sha256`, which must attest to an externally checked per-item mapping. Repeated IDs are permitted only when separately supplied items are genuine duplicates; do not repeat one arbitrary ID to cover missing research. The engine records current revision/hash references for each mapping.

For a correction, `receive` must include `corrects_record_id` before processing. This ensures a correction to a frozen batch blocks that batch until resolved. Commit `correct` with matching `request_id`, `record_id`, `block`, optional source, and image verification. Only unpublished records above the checkpoint may change. Each revision preserves previous content, source, digest, request provenance, and timestamp. Source-only changes also produce revisions. Published or delivered content is never rewritten.

If a correction touches a prepared unpublished batch, retain its old artifacts as `superseded`; the replacement freezes the same membership and intake cutoff with the corrected revisions. New arrivals remain for the following batch.

### Required executable intake-output gate

The only approved source of a final intake response is the exact `items[].block`
released by `intake_output_gate.py` with exit code 0, `status: intake_output_verified`,
and `ready_to_send: true` for the same request/operation. A planner's `finalized`
result, its candidate ledger, `committed` flag, or an existing output file is never
enough. All planner outputs explicitly set `ready_to_send: false`.

After the atomic GitHub commit and exact changed-file readback:

1. Fetch `main` HEAD and the coherent complete snapshot at that SHA through the
   authorized GitHub plugin. Re-read `main` after the blobs are fetched. If HEAD
   changed, refetch at the new HEAD rather than combine snapshots. This also
   recovers an ambiguous commit response: look for the exact original operation,
   without writing another record or inventing a replacement timestamp.
2. Supply the original `finalize` or `correct` operation unchanged, the fresh
   `snapshot`, and an `observation` object with `repository: diegocp01/ai-news-inbox`,
   `branch: main`, `head` equal to the final observed HEAD, `observed_at` equal to
   that UTC read time, and `snapshot_sha256` equal to
   `ledger_engine.digest(ledger_engine.canonical(snapshot))`. Build this from
   actual connector results; never apply a plan locally and label it a readback.
3. Run `python3 workflows/anf/intake_output_gate.py --input readback.json --output intake-output.json`.
   Input keys are `snapshot`, `operation`, and `observation`. No credentials or
   private transport identifiers belong in these files or in the repository.
4. The verifier requires an observation no more than 300 seconds old according to
   its real UTC clock, complete valid ledger state, exact original operation hash,
   a finalized request, identical persisted result/request references, and exact
   block/revision/SHA-256 agreement. An uncommitted operation, stale or mismatched
   readback, edited block, or superseded revision fails closed with exit code 1,
   `ready_to_send: false`, and no released blocks. A normal validation failure
   replaces an existing output artifact with the blocked result. Always check this
   invocation's exit code; never reuse an old success after any execution/I/O error.
5. Only return the released bytes. Respect each item's `queue_status`: an existing
   `published` or `delivered` duplicate was verified, not newly queued. For a
   superseded duplicate, report that fact without presenting an obsolete block as
   a current ANF. Do not repeat an already answered intake merely because a replay
   passes the gate. This verifier grants no compilation attachment-delivery or
   resend permission and does not advance any checkpoint.

The boundary is explicit: Python deterministically validates the supplied state
and observation bindings; the GitHub plugin/assistant must actually perform the
commit and authentic fresh reads. The digest binds inputs but is not a GitHub
signature. This no-network package cannot independently prove snapshot origin or
freshness, run connector calls itself, or force the chat platform to route all
free-form replies through Python. Within this workflow, skipping the gate is an
error, not a supported shortcut. New sessions must fetch this protocol and code
from GitHub rather than rely on conversational memory.

### Trusted preprocessed route

The old skill's complete `anf_v1` exception is represented but **disabled by default**. Enabling a specific route requires explicit user authorization, independent transport authentication, and adding its stable hash to `runtime_config.json`. A receiving operation must supply that approved `trusted_route_sha256`. Do not accept a payload's self-declared mode as authentication.

An approved trusted route mechanically preserves all supplied four-line field bytes, including blanks, instead of researching or rewriting. New summaries still have a hard 60-word maximum under the current user instruction. Overlong payloads fail closed and require an authorized correction. Historical imports are preserved exactly and are not retroactively edited for a newer policy. The route is not activated by this package.

## Compilation, publication, delivery, acknowledgment

1. Scheduled `prepare` must include `eligibility_at`: the scheduled weekday's 08:00 America/New_York converted to UTC with DST. Use the scheduled boundary even when the run or retry starts late; do not substitute the retry time. The user has authorized compilation to proceed without waiting for unfinished bot intake. Freeze the contiguous queued-ID prefix after the checkpoint whose current revisions were finalized by that boundary. A revision completed after the boundary and every following ID remain queued for the next batch, so acknowledgment cannot skip an earlier record. Unfinished intake requests outside this selection are explicitly listed in frozen `deferred_request_ids`; they remain unresolved and unchanged, with their expected item counts preserved. They are not failures, finalized records, or delivered items. They can finalize later and receive future record IDs normally. A pending correction targeting a selected record still blocks. An unconfirmed compiler cutover still blocks. Without `eligibility_at`, the original strict all-intakes gate remains in force. Return `empty` if no records are eligible; never advance the checkpoint for an empty result. Save immutable TXT and JSON plus batch metadata in the same atomic Git commit. No checkpoint moves.
2. Freeze `intake_cutoff`, `eligibility_at` and `deferred_request_ids` as well as record membership. A retry uses the same pending batch even if a newer eligibility boundary is supplied. Later unrelated intakes and the explicitly deferred intakes do not block retry/publication/delivery of this batch. Their subsequent finalization never adds records to the frozen batch or its acknowledgment. An unresolved correction explicitly targeting a member does block it. A replacement after an authorized correction preserves the old membership/cutoffs/deferrals while using the corrected revisions; its eligibility boundary describes original membership selection, not the later correction time. No intake is silently resolved, discarded or acknowledged by deferral.
3. TXT bytes are exactly four-line blocks separated by `\n\n`, followed by `\n\n\n\n\n\n.`. The final dot is the last byte, without a trailing newline. This is five empty lines before the dot.
4. JSON is a raw array with the original keys and ordering: `title`, `description`, `image_url`, `learn_more_url`, `date`, `source`. `date` is the frozen UTC preparation date. Explicit source is preserved; otherwise the original source-inference function applies. Newlines/UTF-8 formatting are deterministic.
5. `publish` with `batch_id`: choose the first unused `items/YYYY-MM-DD.json`, then `-2`, `-3`, etc. Both the new items file and pending publication metadata are returned in **one atomic plan**. Existing items files are never edited or deleted. On CAS collision, choose again from the new complete tree. Read back this commit before attempting chat delivery.
6. `begin_delivery` with `batch_id`, a new opaque `attempt_id`, and `target_sha256` (hash of the verified intended conversation). It requires an already committed publication and exact bytes. Commit the in-flight intent atomically, then read it back.
7. Only the worker that just successfully committed this fresh intent may attempt **one** send. If that commit response is ambiguous, the process restarts, the intent is replayed, or ownership of the send is uncertain, reconcile first. An in-flight marker is never itself permission to send. Never retry based solely on elapsed time.
8. Materialize the exact frozen TXT bytes and verify `txt_sha256`. Upload through the supported native Library/attachment route to the user's account, then send one native attachment to the verified conversation. Confirm that the accepted native attachment ID/version refers to these exact bytes. Upload success alone, a displayed link, a message containing a filename, a text response, an empty tool response, or a local file path is not an attachment-delivery receipt.
9. On a definite rejection with evidence that the service did not accept the attachment, commit `delivery_failed` with `definitely_not_accepted: true` and `evidence_sha256`. The checkpoint/batch/publication remain unchanged, and a new attempt may retry the same file. On timeout/lost response/uncertain outcome, commit `delivery_uncertain`. If even that save fails, the existing in-flight marker remains safely blocking.
10. For in-flight/uncertain recovery, inspect the actual native send result and verified conversation history, attachment identity/version, and byte-hash linkage. If accepted, use the actual recovered receipt to acknowledge. If definitive evidence establishes it was not sent, commit `reconcile_not_sent` with an evidence digest, then create a new attempt. If evidence is unavailable or conflicting, keep the batch pending and ask for help; do not guess or blindly resend.
11. `acknowledge` requires matching `batch_id`, latest `attempt_id`, and a real verified receipt containing:
    - `channel: "chatgpt"`, `accepted: true`
    - `accepted_at` in UTC, between delivery intent and acknowledgment timestamps
    - `attachment_sha256` equal to the frozen TXT hash
    - `target_sha256` equal to the intended target hash
    - `message_receipt_sha256`: digest of the exact native accepted-message receipt
    - `native_attachment_receipt_sha256`: digest of the exact native attachment receipt/identity-version mapping
12. The bridge must derive receipt values from actual accepted tool outputs, not an LLM's assertion. Digests in a public ledger preserve privacy and audit linkage but are not independent proof of service authenticity. Keep access to the original private receipt through the native service/history; never publish private message IDs, recipient IDs, chat text, account tokens, credentials, or signed URLs in this public repository.
13. Acknowledge atomically appends receipt/checkpoint history, advances only through this batch's last ID, marks it delivered, and clears pending. It never includes later arrivals. If the ack save fails after a successful send, report that precise partial outcome and retry/reconcile **acknowledgment only**, not publication or sending. Report completion only after ack readback.

## Forward-only starting boundary

Do not import any old queue, archive, prior news, checkpoints, or export files. The only initial content is the two exact finalized ANFs supplied for this new workflow. Their IDs are 1 and 2 and neither is marked delivered. No historical data is copied merely to deduplicate future intake.

`initialize` can seed explicitly selected finalized blocks using `initial_items`, a `boundary_evidence_sha256`, and `seed_evidence_sha256`. It applies the structural, URL-domain, and 60-word checks without pretending to repeat the prior image verification. The checked-in initial ledger is already initialized; do not run initialize again or overwrite it with a fresh local copy after the branch has advanced.

Future exact duplicates are rejected against the full history of this new ledger, including superseded/delivered revisions. Existing `items/` filenames must still be fetched for collision detection and left immutable. If the user separately asks to check whether a future story appeared in older published JSON, read those existing files without importing them into the ledger or silently changing this starting boundary.

The engine retains generic import operations for test coverage/backward compatibility, but they are out of scope and must not be used for this deployment. Nothing under `imports/` is included in the deployment.

## Recovery and limits

- Lost local state: fetch the coherent current GitHub snapshot, verify the ledger/artifact digests, and continue the state machine
- Uncertain Git write: search/read the stable operation ID in the current ledger before retrying
- Missing/altered immutable TXT, JSON, imported export, or published items file: fail closed; restore exact verified historical bytes through an authorized atomic repair, never synthesize an acknowledgment
- Existing frozen batch plus new arrivals: preserve batch bytes and cutoff; handle later items next
- A user asks for a read-only hypothetical compilation: `preview` only
- A user asks for an old already delivered file: recovery-send the existing immutable attachment only under that explicit request; do not re-publish or move the checkpoint
- GitHub integration denied, missing atomic CAS support, native delivery unavailable, or unconfirmed compiler cutover: surface the exact blocker and keep production schedule paused

The included tests prove deterministic local state behavior with a simulated atomic CAS repository. They do not prove GitHub write access, connector-level CAS semantics, a real production send, external source/image verification, or a completed cutover. The live ledger includes subsequent intake, and current configuration records the confirmed compiler cutover. Scheduler state and real delivery still require independent checks.
