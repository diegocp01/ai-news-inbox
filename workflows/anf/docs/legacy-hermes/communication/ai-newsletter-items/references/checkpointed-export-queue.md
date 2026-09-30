# Checkpointed ANF Export Queue

Use this reference when ANF blocks must be collected across Telegram sessions and exported later as one text file.

## Durable model

- Treat each finalized four-line ANF block as an append-only record with a monotonically increasing ID.
- Keep runtime records outside the Git-managed skill tree, under `~/.hermes/data/anf-queue/`.
- Maintain a hidden `last_exported_id`; do not place a visible “STOP HERE” marker in newsletter content.
- Prepare records with `id > last_exported_id` in arrival order, separated by one blank line.
- Save the chosen range as one immutable pending batch with a stable batch ID and path. New records arriving afterward belong to the next batch.
- Return no file when the pending set is empty.

## Delivery-acknowledged checkpoint

Use a two-phase transaction:

1. **Prepare:** atomically create the export and `pending.json`; do not move the checkpoint.
2. **Deliver:** send that exact file through `hermes send --to telegram`.
3. **Acknowledge:** only after exit code 0 indicates Telegram accepted the attachment, atomically set `last_exported_id` to the pending batch’s last record and remove `pending.json`.

If delivery fails, preserve the checkpoint, batch ID, record range, and export path. The next trigger retries the identical file. If its file is missing, recreate it from the saved record range. Do not use a final-response `MEDIA:` attachment when the transaction needs post-delivery acknowledgement, because no acknowledgement step can run after the final response is dispatched.

## Receipt disputes and recovery resends

An API-accepted attachment is not proof that the user saw it in the intended Telegram chat. If he says the last file he received predates `last_exported_id`:

1. Inspect `state.json`, cron run output, export timestamps, and the relevant stored Telegram session. Look specifically for a manual compilation that may have advanced the checkpoint between scheduled runs.
2. Describe the system evidence as “reported delivered” or “checkpoint advanced,” not “you received it,” unless the user confirms receipt.
3. If the immutable export and matching GitHub JSON already exist, never rerun the transactional `deliver` command merely to restore visibility. That risks duplicate publication or confusing state.
4. Resend only the existing `last_export_path` into the current conversation with `MEDIA:/absolute/path/to/file.txt`; do not alter the checkpoint and do not upload to GitHub again.
5. Explicitly answer whether GitHub was changed. For a recovery-only resend, the answer must be no.
6. When a cron reports `empty` but the user expected items, reconcile intervening manual runs before concluding that no items existed.

## Historical intake boundary

A newly installed queue begins empty. Do not silently infer that historical ANFs were exported or unexported.

When the user identifies a last-unneeded ANF as the cutoff and a first-needed ANF after it:

1. Locate both exact four-line outputs in stored Hermes session history.
2. Exclude the cutoff item itself.
3. Collect every later finalized four-line assistant ANF in chronological order through the end of the relevant stored history.
4. Search all Telegram sessions stored in the active Hermes profile, including sessions generated with different model inferences; do not assume the current session is the only source.
5. Explain the boundary of access: stored Hermes sessions are searchable, but arbitrary raw Telegram messages that Hermes did not store are not.
6. Queue the collected blocks without preparing or delivering the file; verify titles/order and pending count afterward.

## Corrections and duplicates

- Hash the exact finalized block and reject exact duplicate writes caused by retries.
- Queue corrected variants only when the user intentionally wants the revised item exported; otherwise replace or supersede the still-pending record rather than shipping both versions.
- Once a record has been delivered and acknowledged, preserve history rather than rewriting a prior export.

## Isolation and verification

- Protect add/prepare/ack/status operations with the same filesystem lock.
- Test with a temporary queue root passed only to the test process. Avoid exporting a test-only queue environment variable into a persistent shell, where a later production check could accidentally inspect test data.
- Simulate both Telegram failure and success: failure keeps `last_exported_id` unchanged and `pending.json` present; success advances only through the delivered batch; records added while delivery is pending remain for the next batch.
- Verify exact duplicate rejection, stable retry batch/path, missing-file recreation, empty behavior, malformed-state safety, and `latest` recovery.
- Gate compilation on session/queue parity: after a one-time reconciled message baseline, scan finalized ANF-only assistant responses from Telegram and webhook sessions and refuse to compile if any exact block lacks a durable queue record. This is a backstop for tool omissions, not a replacement for queueing before the response.

## Current implementation

The trigger skill `compile-anfs` owns the runnable script at `communication/compile-anfs/scripts/anf_queue.py`. The ANF skill queues finalized blocks; the trigger skill prepares, delivers, and acknowledges them.