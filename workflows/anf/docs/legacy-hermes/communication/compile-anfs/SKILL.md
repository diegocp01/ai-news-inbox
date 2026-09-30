---
name: compile-anfs
description: "Use when compiling queued ANFs to text and GitHub JSON."
version: 1.3.0
author: Hermes Agent
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [anf, newsletter, export, text-file, github, json, checkpoint]
    requires_tools: [terminal]
    requires_commands: [git, hermes]
---

# Compile ANFs

Use when the user says **“compile ANFs,” “export ANFs,” “make my ANF text file,”** or invokes `/compile-anfs`.

Each compile run publishes the same queued batch in two formats:

- the existing `.txt` attachment delivered through Telegram;
- one new raw JSON array committed to `items/` on `diegocp01/ai-news-inbox`, branch `main`.

Every `.txt` export must end with exactly five empty lines followed by a dot as the final character (equivalent to appending `\n\n\n\n\n\n.` after the last ANF block).

## Workflow

1. Run the transactional delivery command:

```bash
python3 ~/.hermes/skills/communication/compile-anfs/scripts/anf_queue.py deliver --target telegram
```

The command first performs a fail-closed intake validation against Hermes session history. Every finalized ANF-only assistant response after the reconciled baseline must have an exact durable queue record. If any are missing, compilation stops before preparation, GitHub publication, Telegram delivery, or checkpoint advancement.

The validation also audits Chief of Staff webhook ANF requests themselves. If an isolated processor fails before producing a four-line block, compilation stops unless the source title has since been queued or the intake is explicitly recorded in `intake_validation.json` under `reconciled_intakes` with its message ID, matching queue record IDs, and a reason (for example, an equivalent corrected story already queued under a different title).

2. Parse the returned JSON.
3. When `status` is `delivered`, briefly confirm how many ANFs Telegram received and report the returned `github_filename`. Do **not** attach the file again with `MEDIA:` because the script already delivered it.
4. When `status` is `github_publish_failed`, explain that GitHub publication failed and the same batch remains pending; Telegram is not sent and the checkpoint is not advanced.
5. When `status` is `delivery_failed`, explain that Telegram delivery failed, report the already-created `github_filename`, and state that the same batch remains pending. The next trigger reuses that GitHub file and retries Telegram without creating a duplicate JSON file.
6. When `status` is `empty`, say there are no new ANFs since the previous successfully delivered compilation.
7. When `status` is `intake_validation_failed`, report the missing titles/message IDs and queue or reconcile them before retrying. Never bypass the check or move the baseline past an unexplained result.

## Transaction and Checkpoint Behavior

The workflow is deliberately transactional:

1. **Prepare:** Create one immutable `.txt` export and save `pending.json`. The checkpoint does not move.
2. **Publish GitHub:** Clone `https://github.com/diegocp01/ai-news-inbox.git` at `main`, create exactly one unused `items/YYYY-MM-DD.json` path (or `-2`, `-3`, etc.), commit, and push. Existing files are never edited or deleted.
3. **Deliver Telegram:** Send the exact pending `.txt` through `hermes send --to telegram`.
4. **Acknowledge:** Only after both GitHub publication and Telegram delivery succeed, atomically advance `last_exported_id` and clear `pending.json`.

The GitHub file is raw JSON containing one object per queued ANF, with keys `title`, `description`, `image_url`, `learn_more_url`, `date`, and `source`. `date` is the UTC preparation date. The filename is persisted in the pending transaction, so a Telegram retry reuses the same GitHub file instead of creating another.

Additional guarantees:

- Re-running after a failed delivery returns and retries the same batch ID, record range, and file.
- ANFs queued while a batch awaits delivery remain for the following batch.
- A pending export is deterministically recreated before every retry, including the required five-empty-lines-and-dot trailer.
- Queue records receive monotonically increasing integer IDs.
- Existing delivered exports remain on disk.
- A filesystem lock prevents simultaneous queue writes, preparations, and acknowledgements from corrupting state.

## Storage

Runtime data is kept outside the Git-managed skill directory:

```text
~/.hermes/data/anf-queue/
├── records.jsonl
├── state.json
├── pending.json
├── queue.lock
└── exports/
```

## Diagnostic Commands

Prepare without sending or advancing the checkpoint:

```bash
python3 ~/.hermes/skills/communication/compile-anfs/scripts/anf_queue.py prepare
```

Manually acknowledge only when Telegram delivery has independently been confirmed:

```bash
python3 ~/.hermes/skills/communication/compile-anfs/scripts/anf_queue.py ack --batch-id <batch-id>
```

Inspect current state or recover the pending/latest path:

```bash
python3 ~/.hermes/skills/communication/compile-anfs/scripts/anf_queue.py status
python3 ~/.hermes/skills/communication/compile-anfs/scripts/anf_queue.py latest
python3 ~/.hermes/skills/communication/compile-anfs/scripts/anf_queue.py validate-intake
```
