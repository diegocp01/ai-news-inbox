# Executor validation evidence — 2026-10-15

## Local acceptance tests

Command: `python3 -m unittest discover -s workflows/anf/tests -q`.
Baseline: **148 passed**. With executor/transport acceptance coverage: **180
passed**. The engine and intake output gate remain unchanged.

The added tests exercise the real executor and Git Data transport against a
synthetic service: competing writers and non-force rejection; response lost
after accepted ref update; object created without a ref; cancellation before
and after ref update; restart and cleared blob cache; missing workflow events
and closed issues; separate identical articles versus same-operation retry;
preview/review interruption; delayed eligibility and frozen retry membership;
large blobs, empty/truncated encoded bytes, incomplete trees and missing ledger;
actual HTTP error header handling; permission denials; edited/unauthorized
submitters; immutable job conflicts; strict job envelope validation; privileged
approval binding; stale operation timestamps; and replacement of stale output.

The independent-review P2 discovery-starvation finding was reproduced before
the fix: with a budget of two, a seven-issue unauthorized prefix plus one valid
job caused nine authentication calls, and discovery preceded already accepted
pending work. Five regression tests now cover bounded unauthorized floods,
durable discovery progress after restart/cache loss, accepted work before
saturated discovery, budgeting known/irrelevant/PR rows with wraparound,
cross-page progress, and accepted work before a discovery transport failure.

The existing engine tests cover sparse delivered membership, exact frozen files,
uncertain native delivery reconciliation, receipt binding, publication collision,
correction rules, full state validation, and output-gate failures. The executor
adds tests that reject all issue-supplied delivery/acknowledgment operations and
preserve an existing uncertain attempt after restart. These are synthetic
receipt tests, **not** a real attachment delivery demonstration.

## Real connector invocation

The existing GitHub connector authenticated as `diegocp01`, numeric user ID
`154387858`; repository permission check returned `admin`. It created
[issue #2](https://github.com/diegocp01/ai-news-inbox/issues/2) at
`2026-10-15T03:14:52Z` with the exact read-only status envelope in EXECUTOR.md.
Independent issue readback reported that user as author and
`performed_via_github_app.slug: chatgpt-codex-connector`. This proves the real
connector can submit durable structured jobs under the allowlisted identity.
It does not prove a deployed executor consumed that job.

## Real file over 1 MiB

Pinned source commit: `bffe4d0d54a1eb427d225082667f9bfb6cc0d6b8`.
Ledger blob: `ab6e7e548a0daf1de16f7973788bd4f5a9a741c9`.

- Connector `fetch_file` for that exact ledger/ref returned `content: ""`.
- Connector GET of `/git/blobs/ab6e7e548a0daf1de16f7973788bd4f5a9a741c9`
  returned the full decoded content.
- The new Python `GitHub.blob()` method called the real public Git blobs endpoint,
  verified base64, byte count and Git blob SHA, and matched the cloned file exactly:
  **1,053,961 bytes**, SHA-256
  `3fbbbc38aec75fc76ae43cfbc9d6b516c2f2fe40b94906ad9b260ce62f2cf2d9`.

The local Python installation initially lacked its CA chain. Repeating with the
existing macOS trusted bundle (`SSL_CERT_FILE=/etc/ssl/cert.pem`) succeeded with
TLS verification enabled. No certificate check was bypassed or credential added.

## Real isolated Git write/competition proof

Target: [anf-executor-sandbox-proof-20261015](https://github.com/diegocp01/ai-news-inbox/tree/anf-executor-sandbox-proof-20261015),
created from the pinned source commit above. Only synthetic `.anf-executor-proof/`
files were candidates. No ledger, batch, policy, config, publication, production
ref, workflow, or schedule was changed by these calls.

The connector successfully accepted the actual `create_tree` arguments
`repository_full_name`, `base_tree_sha`, `tree_elements`.

| Object | SHA | Outcome |
| --- | --- | --- |
| Candidate A tree | `6a0c9c04b08a26b49ef5fd01cfff600e2789c8c2` | Created |
| Candidate A commit | `fd55c5c62113d184dac335e2a05d7223c105ed67` | Non-force ref update accepted |
| Competing B tree | `02b945474c9e576d6b10ef003f2c2e9cf4cb3f0f` | Created |
| Competing B commit | `300d5f59d6425296c86536029e48c279059e6018` | Object exists; never reached branch |

Both candidates have the same original sole parent. Updating B with the old
expected head returned GraphQL `UNKNOWN` at `2026-10-15T03:24:23Z`. Fresh branch
readback proved HEAD remained A. Attempting B with expected head A and
`force: false` returned `UNPROCESSABLE: rejecting non-fast forward update`
(also wrapped as connector `UNKNOWN`). A's file was fetched and matched its
exact submitted bytes. This demonstrates why an error string or an existing
commit object cannot replace branch reconciliation.

The tests inject actual lost responses/cancellation. The live proof does not
claim to have forced a real network response loss; it demonstrated ambiguous
connector errors and safe observation of the resulting branch state.

## Explicit remaining proof/deployment blockers

- There was no `.github/workflows` directory on the inspected default-branch
  commit. GitHub issue workflows run only when present on the default branch.
  End-to-end **issue → Actions → executor** has not run. The PR stays undeployed;
  merge/activation/permission changes require separate approval.
- Local `gh auth status` reported the existing token invalid. Connector access
  worked, but the Python process cannot inherit it. Live writes above used the
  authorized connector; the Python HTTP transport's write path has synthetic
  coverage, not a live Actions-token demonstration. No new credential was made.
- No Actions-native ChatGPT attachment/receipt adapter is available. No real
  deliveries were attempted. Full production writer cutover must wait for that
  integration and its approval/proof.
- The connector rejected the Actions workflow-list URL as unsupported, so no
  claims are made about repository-level Actions settings or policies.

These are precise proof limits, not failures of the pure engine. See
[the deployment/cutover plan](EXECUTOR.md#deployment-requirements-and-safe-cutover).
