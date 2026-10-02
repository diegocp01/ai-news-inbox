#!/usr/bin/env python3
"""Release ANF intake text only from a fresh, verified GitHub readback snapshot.

No network or writes. The authorized GitHub connector must supply authentic
snapshot/observation data; this verifier cannot authenticate a caller's claims.
A plan, commit object, or successful planner exit is never readback evidence.
"""
from __future__ import annotations
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
import ledger_engine as e

REPOSITORY = "diegocp01/ai-news-inbox"
BRANCH = "main"
MAX_OBSERVATION_AGE_SECONDS = 300


def verify_intake_output(snapshot, operation, observation, *, now=None):
    """Read-only, fail-closed gate. `now` is an in-process test seam, not CLI input."""
    e.require(isinstance(observation, dict), "Fresh GitHub readback observation is required")
    e.require(observation.get("repository") == REPOSITORY and observation.get("branch") == BRANCH,
              "Readback must come from the authorized repository and main branch")
    e.require(isinstance(snapshot, dict), "Readback snapshot is required")
    e.require(observation.get("head") == snapshot.get("head"), "Observed main HEAD differs from snapshot")
    e.require(observation.get("snapshot_sha256") == e.digest(e.canonical(snapshot)),
              "Readback snapshot does not match its observation digest")
    observed_at = datetime.fromisoformat(e.timestamp(observation.get("observed_at")))
    now = now or datetime.now(timezone.utc)
    e.require(now.tzinfo is not None, "Gate clock must be timezone-aware")
    age = (now - observed_at).total_seconds()
    e.require(0 <= age <= MAX_OBSERVATION_AGE_SECONDS, "Readback is stale or future-dated; fetch main again")
    e.require(isinstance(operation, dict) and operation.get("kind") in {"finalize", "correct"},
              "Gate requires the exact finalize or correct operation")
    e.require(datetime.fromisoformat(e.timestamp(operation.get("at"))) <= observed_at,
              "Operation is newer than the readback observation")

    # Validate the full durable state and policy through the existing engine.
    e.plan(snapshot, {"kind": "status"})
    files = snapshot["files"]
    e.require(e.LEDGER in files, "Durable ledger is missing")
    state = json.loads(files[e.LEDGER])
    op_id = e.opaque(operation.get("operation_id"), "operation ID")
    e.require(op_id in state["operations"], "Operation is not in the committed readback ledger")
    persisted = state["operations"][op_id]
    e.require(persisted["sha256"] == e.digest(e.canonical(operation)),
              "Committed operation differs from the submitted operation")
    request_id = e.opaque(operation.get("request_id"), "request ID")
    request = state["requests"].get(request_id)
    e.require(isinstance(request, dict) and request.get("status") == "finalized",
              "Intake is not durably finalized")
    result = persisted["result"]
    if operation["kind"] == "finalize":
        e.require(result.get("status") == "finalized" and result.get("request_id") == request_id,
                  "Persisted finalization result does not match request")
        refs = result.get("records")
        items = operation.get("items")
    else:
        e.require(result.get("status") == "corrected"
                  and request.get("corrects_record_id") == operation.get("record_id"),
                  "Persisted correction result does not match request")
        e.require(isinstance(result.get("record"), dict)
                  and result["record"].get("id") == operation.get("record_id"),
                  "Committed correction reference differs from target record")
        refs = [result["record"]]
        items = [operation]
    e.require(refs == request.get("records"), "Persisted result differs from resolved intake records")
    e.require(isinstance(items, list) and isinstance(refs, list)
              and len(items) == len(refs) == request["expected_items"], "Intake item count mismatch")
    released = []
    for item, ref in zip(items, refs):
        e.require(isinstance(item, dict) and isinstance(ref, dict), "Invalid intake item or reference")
        record = e.lookup(state, ref["id"])
        e.require(ref["revision"] == len(record["revisions"]),
                  "Intake refers to superseded content; do not present it as a current ANF")
        rev = record["revisions"][ref["revision"] - 1]
        submitted_block = e.block_fields(item.get("block"), preserve=request["mode"] == "trusted_preprocessed")[0]
        e.require(submitted_block == rev["block"] and e.digest(submitted_block) == ref["sha256"] == rev["sha256"],
                  "Final block differs from the exact committed revision")
        duplicate = operation["kind"] == "finalize" and any(
            entry.get("id") == ref["id"] and entry.get("revision") == ref["revision"]
            for entry in result.get("duplicates", []))
        if (operation["kind"] == "correct" and "source" in item) or (operation["kind"] == "finalize" and not duplicate):
            e.require(isinstance(item.get("source", ""), str) and item.get("source", "").strip() == rev["source"],
                      "Source differs from the committed operation")
        published = any(batch["status"] in {"published", "delivered"} and any(
            member["id"] == record["id"] for member in batch["records"]) for batch in state["batches"].values())
        queue_status = "delivered" if record["id"] in e.delivered_ids(state) else ("published" if published else "queued")
        released.append({**ref, "block": rev["block"], "source": rev["source"], "queue_status": queue_status})
    return {"status": "intake_output_verified", "ready_to_send": True, "purpose": "intake_response",
            "operation_id": op_id, "request_id": request_id, "verified_head": snapshot["head"],
            "observed_at": observation["observed_at"], "snapshot_sha256": observation["snapshot_sha256"],
            "ledger_sha256": e.digest(files[e.LEDGER]), "items": released,
            "attachment_delivery_authorized": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="Read JSON input; defaults to stdin")
    parser.add_argument("--output", type=Path, help="Write gate result; defaults to stdout")
    args = parser.parse_args()
    code = 0
    try:
        value = json.loads(args.input.read_text(encoding="utf-8") if args.input else sys.stdin.read())
        result = verify_intake_output(value["snapshot"], value["operation"], value.get("observation"))
    except (e.LedgerError, KeyError, TypeError, ValueError, AttributeError, IndexError, RecursionError, OverflowError, OSError) as exc:
        result = {"status": "intake_output_blocked", "ready_to_send": False, "items": [], "error": str(exc)}
        code = 1
    output = e.encoded(result)
    # Replace a prior success artifact even on validation failure; never leave it
    # looking current. A filesystem failure also exits nonzero and reports no text.
    try:
        if args.output:
            args.output.write_text(output, encoding="utf-8")
        else:
            sys.stdout.write(output)
    except OSError as exc:
        sys.stdout.write(e.encoded({"status": "intake_output_blocked", "ready_to_send": False,
                                   "items": [], "error": str(exc)}))
        return 1
    return code


if __name__ == "__main__":
    raise SystemExit(main())
