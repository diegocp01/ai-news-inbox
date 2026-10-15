# Deterministic ANF executor (undeployed)

`executor.py` is a networked worker around the unchanged ledger engine. Dot stays
the researcher/editor. Dot submits small JSON jobs through its existing GitHub
connector; the worker authenticates the submitter, journals the job, executes one
engine operation, commits atomically, and verifies durable evidence. It never
interprets issue prose as instructions and never invokes a shell, another agent,
an arbitrary URL, or a sender based on job content.

The new worker is **disabled**, targets `anf-executor-sandbox`, and has a separate
production cutover gate. The existing `runtime_config.json` cutover is not
permission to activate this new writer. This PR changes no production ledger,
policy, frozen artifact, publication, existing schedule, or current writer.

## Invocation and trust boundary

1. Dot calls the existing GitHub connector `create_issue` on
   `diegocp01/ai-news-inbox`, with a title beginning `[ANF job v1]` and a body
   containing only the JSON envelope below. No labels are needed. A confirmed
   issue URL means **submitted**, not received/finalized/published/delivered.
2. Once separately deployed and enabled, the Actions `issues: opened/reopened`
   event wakes the worker. An hourly reconciliation wakeup and manual dispatch
   recover lost/canceled/replaced wakeups. This is not the compilation schedule.
3. The worker fetches the issue independently. It requires an allowlisted numeric
   user ID, current repository write/maintain/admin permission, a human GitHub
   user, matching REST/GraphQL author/body/node identity, and `lastEditedAt: null`.
   Original authorship alone is insufficient because other writers can edit an
   issue. Submit a new pristine issue for corrections; reuse the same IDs/body
   when recovering a transport retry. Changing an accepted operation is forbidden.
4. The worker persists the exact normalized job, original body digest, submitter,
   issue identity and receipt time in `workflows/anf/executor-jobs/<issue>.json`.
   It then applies the operation and changes that journal row to `applied` **in
   the same commit** as the ledger/artifact changes. `received` in the executor
   journal means the job was received; engine `receive` must itself be applied
   before Dot acknowledges article intake or begins research.
5. Dot reads the small job journal and this run's Actions result artifact. For
   final intake text after an interruption, submit another issue whose operation
   is `{"kind":"job_status","issue_number":NUMBER}` and read its result artifact's
   `job_status`. Operators can also run `executor.py --status-issue NUMBER`.
   These routes fetch fresh state on the authorized runner. Only `intake_output` with the original output gate's
   `ready_to_send: true` releases exact blocks; the envelope itself never grants
   sending permission. Historical run artifacts are evidence at their recorded
   time, not fresh output authorization. Never repeat an already answered intake.

Example read-only envelope (the real proof is issue #2):

```json
{"version":1,"job_id":"executor_probe_20261015","operation":{"kind":"status"}}
```

Example normal intake shape (replace identities and timestamp with actual data):

```json
{
  "version": 1,
  "job_id": "opaque_unique_submission_job",
  "operation": {
    "kind": "receive",
    "operation_id": "opaque_unique_operation",
    "at": "2026-10-15T03:00:00+00:00",
    "request_id": "opaque_unique_submission",
    "expected_items": 1
  }
}
```

The hard limit is 24,000 UTF-8 bytes and 20 items per job. Unknown envelope or
operation fields, duplicate JSON keys, malformed/truncated JSON, and unsupported
operations fail closed. Do not truncate an existing accepted multi-item request
or split its finalization. Use small separate requests at the initial acceptance
boundary; an oversized already-accepted request needs a separately designed
authenticated immutable-payload route, not manual partial commits.

Operation schemas are the explicit `FIELDS` table in `executor.py`, followed by
the engine's semantic/ledger checks. Supported: `status`, `preview`, `receive`,
`job_status`, `finalize`, `correct`, `review_record`, `prepare`, `publish`, `reject_url`,
`resolve_url_rejection`, `cancel_intake`, and `reconcile_intake`. Mutations retain
their exact `operation_id` and UTC `at`. Prepare always requires `eligibility_at`;
Dot supplies the intended scheduled 08:00 America/New_York boundary converted to
UTC, including after delays/DST. The executor never substitutes wall-clock time.

Cancellation, intake reconciliation, nonstandard intake modes, and authenticated
source-provenance assertions additionally require the exact canonical operation
SHA-256 in trusted `executor_config.json`. An operator must independently verify
the actual permission/source evidence before an approved config change. Digests
or approval claims supplied in issue text cannot grant this authority. Default
allowances are empty. Ordinary image/source/audience judgments remain Dot's
responsibility; the worker validates their structure, not their truth.

This is a public repository: submit only public-safe finalized content and opaque
identities/evidence hashes. Never put raw chat IDs, private source messages,
recipient details, tokens, signed URLs, or native receipts in jobs or journals.

## Queue, transaction and recovery

Actions concurrency (`cancel-in-progress: false`) is only a contention reducer.
GitHub can replace pending runs, delay schedules, or lose wakeups. Every pass
pages through issues in creation order, including closed issues, and discovers
unjournaled jobs; every durable unfinished job is revisited. Closing an issue
does not silently cancel accepted intake. The immutable Git journal is the
accepted-job queue, while GitHub issues retain work not yet journaled. Deleting
an unjournaled issue can destroy that submission; do not delete job issues.

Research and approvals happen outside the commit queue. Each accepted operation
gets a short journal transaction and a short application transaction. New jobs
are processed before blocked retries; blocked retries rotate by last attempt to
avoid preventing unrelated work. There is a configured per-pass job bound.
Validation failures retain a durable blocker and retry the same operation on a
later pass. Invalid/unauthorized submissions appear in the run result without
being accepted into the journal. Permission/outage failures stop the pass, leave
existing durable rows untouched, and fail the Action visibly.

For every transaction the worker:

- Pins the branch HEAD, reads its immutable commit/tree, fetches every ANF file
  and all existing `items/*.json` blobs, checks required paths, exact byte lengths
  and Git blob hashes, then runs full engine integrity validation. It rechecks
  HEAD after assembling the snapshot. Truncated recursive trees fall back to a
  complete nonrecursive traversal; a truncated subtree stops execution.
- Uses `/git/blobs/{sha}`, including for files over 1 MiB. Empty encoded content
  for a nonempty blob is an error, never an empty ledger. The optional in-process
  blob cache is keyed by verified SHA and size; no local scratch file is state.
- Generates a complete in-process plan without sending it through model context.
  It limits changes to the ledger, new frozen batches, new publication paths,
  and its own journal; existing artifacts cannot be overwritten.
- Creates all blobs, a base-tree-preserving tree, and a commit with exactly one
  parent equal to the observed HEAD. It reads back the candidate and every change,
  checks the parent again, then updates the ref with `force: false`. A competing
  sibling cannot fast-forward over a winner. Force updates by administrators are
  outside this model; prohibit force pushes on the production state branch.
- On an unknown/lost/canceled outcome, rereads the branch and its atomic journal
  marker before retrying. An object existing without branch membership is not
  success. Fresh status locates the reachable transition commit through pinned
  path history and verifies every original changed-file SHA-256 there, then
  validates the current ledger/operation. Later legitimate ledger changes do not
  make historical readback impossible.

The REST Git tree fields are `base_tree` and `tree`. If interacting through the
ChatGPT connector wrapper for deployment/testing, its actual fields are
`repository_full_name`, `base_tree_sha`, and `tree_elements`. They are different
interfaces, not interchangeable argument names. The worker performs REST calls
directly; Dot does not copy a generated list of Git calls.

Four transaction attempts and three stable-snapshot attempts bound contention.
Read retries honor actual `Retry-After` (seconds or HTTP date) and
`X-RateLimit-Remaining`/`X-RateLimit-Reset`. Mutation failures reconcile before any
retry. Server waits over 30 seconds defer the pass rather than sleep too briefly.
403 without explicit throttle headers is a permission blocker, never a conflict.
No credential fallback, approval bypass, force push, or token creation exists.
If a server requires a wait longer than the hourly reconciliation interval,
operators must honor that deadline before a manual run; automatic wakeups may
still encounter the server's continuing throttle and fail safely. There is no
claim that GitHub outages, schedule suppression, or approval waits can be avoided.

A job whose immutable timestamp predates a competing committed operation remains
blocked. The worker does not silently rewrite its identity/time. After verifying
the old operation is absent from the latest ledger, Dot may submit a new retry
operation ID/time retaining the request/attempt identity and original eligibility
cutoff. Preserve the old job as evidence. Replays of committed operations create
no article, publication, or send; separately submitted identical stories retain
their separate IDs under the unchanged policy.

## Delivery is an explicit platform blocker

Actions receives its own short-lived repository `GITHUB_TOKEN`. It does **not**
inherit ChatGPT's connector/Library/conversation credentials. This PR has no
native attachment sender or authenticated receipt verifier. All `begin_delivery`,
`delivery_failed`, `delivery_uncertain`, `reconcile_not_sent`, and `acknowledge`
jobs are rejected. Initialization and migration/import operations are also not
exposed. A digest asserted in an issue is not a real delivery receipt.

Prepared and published batches stay distinct from delivery. Existing in-flight
or uncertain attempts remain blocking; never resend on timeout or restart. The
unchanged engine tests cover accepted-receipt reconciliation and sparse delivered
membership. A future native bridge must verify real conversation history,
attachment identity/version and exact frozen bytes, then route authenticated
receipt transitions through the same single writer. If that integration needs
new credentials or persistent access, report and obtain separate approval first.
Until that exists, full production compilation/delivery cutover is blocked.

## Deployment requirements and safe cutover

1. Review and merge the PR only when separately authorized. Issue events require
   the workflow on the default branch. Merging alone leaves execution disabled:
   both `vars.ANF_EXECUTOR_ENABLED == 'true'` and config `enabled: true` are needed.
   The proposed job requests `contents: write` and `issues: read` for its
   short-lived token. These permissions and any repository Actions policy or
   branch-rule changes need explicit deployment approval; none was applied here.
2. Create an approved sandbox branch with synthetic state, activate **sandbox
   only**, and submit pristine status/receive/finalize/review/prepare jobs through
   the connector. Prove the real issue event, authenticated reads and Git writes,
   canceled-run reconciliation, and result retrieval with Actions' own token.
   Do not use production articles or sends as proof.
3. Complete a supported native attachment/receipt bridge and its safe test target.
   Resolve existing uncertain deliveries from actual receipts. Verify both
   independent writer stop authority and the receipt bridge before cutover.
4. In an explicitly approved maintenance boundary, stop new **ANF** commit
   submissions from the old writer, drain/reconcile its outstanding operations,
   and verify the current main ledger, requests, pending batch, immutable files,
   publications, sparse delivered membership and checkpoint. Keep Dot's research
   active outside the queue. Do not change unrelated schedules/projects.
5. Record a new executor-specific cutover evidence digest in reviewed config,
   set its target to `main`, and activate exactly this writer. Preserve the full
   current state; never seed/reset from a checkout or sandbox. Keep the existing
   weekday compilation eligibility schedule, routed to small structured jobs.
6. Begin with read-only status/preview and one explicitly approved new intake.
   Verify exact final output and operation evidence before allowing normal volume.
   Observe Actions failures, oldest unresolved jobs and queued state. If rollback
   is needed, pause this writer, reconcile all uncertain writes/receipts, then
   explicitly authorize one replacement writer against current main. Never run
   both or restore an older ledger snapshot.

The included tests and [live evidence](EXECUTOR-VALIDATION.md) are not deployment
approval. No automatic switch or notification to other projects is included.

References: [GitHub issue event requirements](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#issues),
[Git blobs](https://docs.github.com/en/rest/git/blobs#get-a-blob),
[non-force ref updates](https://docs.github.com/en/rest/git/refs#update-a-reference).
