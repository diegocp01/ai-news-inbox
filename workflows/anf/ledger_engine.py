#!/usr/bin/env python3
"""Deterministic ANF Git-tree change planner. No network, send, shell, or Pi access.

Input: {snapshot: {head, complete: true, files: {path: UTF8}}, operation: {...}}
Output: one atomic commit plan against base_sha. Merely producing it saves nothing.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = "workflows/anf/"
LEDGER = ROOT + "ledger.json"
POLICY = ROOT + "policy.json"
CONFIG = ROOT + "runtime_config.json"
TRAILER = "\n\n\n\n\n\n."
PREFIXES = ("Title:", "URL:", "Image URL:", "Summary:")
SCHEMA = 1

class LedgerError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise LedgerError(message)


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def encoded(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def integer(value, minimum=0):
    return type(value) is int and value >= minimum


def timestamp(value):
    require(isinstance(value, str), "UTC timestamp is required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LedgerError("Invalid UTC timestamp") from exc
    require(parsed.tzinfo is not None and parsed.utcoffset().total_seconds() == 0,
            "Timestamp must explicitly use UTC")
    return parsed.astimezone(timezone.utc).isoformat()


def opaque(value, label="identifier"):
    require(isinstance(value, str) and re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", value),
            f"Invalid opaque {label}; do not include raw chat identifiers")
    return value


def sha(value, label="sha256"):
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value), f"Invalid {label}")
    return value


def block_fields(content, *, preserve=False):
    require(isinstance(content, str), "Block must be text")
    block = content if preserve else content.strip()
    # A final response contains exactly four physical lines. Do not hide blank lines.
    lines = block.split("\n")
    require(len(lines) == 4 and block.splitlines() == lines and all(
        line.startswith(prefix) for line, prefix in zip(lines, PREFIXES)),
        "ANF must have exactly four lines: Title, URL, Image URL, Summary")
    return block, dict(zip(("title", "learn_more_url", "image_url", "description"),
                          (line[len(prefix):].strip() for line, prefix in zip(lines, PREFIXES))))


def host(url):
    require(isinstance(url, str) and not any(c.isspace() or ord(c) < 32 for c in url) and "\\" not in url, "URL contains whitespace")
    parsed = urlparse(url)
    require(parsed.scheme.lower() in {"http", "https"} and parsed.hostname and not parsed.username
            and not parsed.password, "URL must be an HTTP(S) URL without embedded credentials")
    try:
        require("%" not in parsed.hostname, "URL hostname must not contain percent escapes")
        hostname = parsed.hostname.encode("idna").decode("ascii").lower().rstrip(".")
        _ = parsed.port
    except (ValueError, UnicodeError) as exc:
        raise LedgerError("Invalid URL host") from exc
    return hostname


def matches_domain(hostname, domains):
    return any(hostname == domain or hostname.endswith("." + domain) for domain in domains)


def validate_block(content, policy, mode="standard", image_verified=False):
    require(mode in {"standard", "trusted_preprocessed", "user_finalized_seed"}, "Unknown intake mode")
    block, fields = block_fields(content, preserve=mode == "trusted_preprocessed")
    require(len(fields["description"].split()) <= policy["summary_max_words"], "Summary exceeds word limit")
    if mode == "trusted_preprocessed":
        # Only an authenticated, explicitly approved bridge may select this mode.
        return block
    require(fields["title"] and fields["description"] and fields["image_url"],
            "Title, image URL and summary must not be empty")
    if fields["learn_more_url"]:
        hostname = host(fields["learn_more_url"])
        require(not matches_domain(hostname, policy["forbidden_url_domains"])
                and not any(hostname.endswith(s) for s in policy["forbidden_url_suffixes"]),
                "Final learn-more URL violates domain policy")
    require(not matches_domain(host(fields["image_url"]), policy["forbidden_image_domains"]),
            "Image URL violates domain policy")
    if mode != "user_finalized_seed":
        require(image_verified is True, "Final image must be externally verified as a real image")
    return block


def infer_source(url):
    hostname = (urlparse(url).hostname or "").lower()
    if hostname.startswith("www."):
        hostname = hostname[4:]
    known = {"arxiv.org": "arXiv", "github.com": "GitHub", "reuters.com": "Reuters",
             "apnews.com": "Associated Press", "theverge.com": "The Verge",
             "techcrunch.com": "TechCrunch", "youtube.com": "YouTube", "youtu.be": "YouTube"}
    for domain, name in known.items():
        if hostname == domain or hostname.endswith("." + domain):
            return name
    if not hostname:
        return ""
    stem = hostname.split(".")[-2] if "." in hostname else hostname
    return stem.replace("-", " ").title()


def github_items(entries, export_date):
    result = []
    for entry in entries:
        _, fields = block_fields(entry["block"], preserve=True)
        result.append({"title": fields["title"], "description": fields["description"],
                       "image_url": fields["image_url"], "learn_more_url": fields["learn_more_url"],
                       "date": export_date,
                       "source": entry["source"] or infer_source(fields["learn_more_url"])})
    return result


def render_txt(entries):
    return "\n\n".join(entry["block"] for entry in entries) + TRAILER


def fresh_state():
    return {"schema": SCHEMA, "generation": 0, "updated_at": None, "next_id": 1, "records": [], "requests": {},
            "batches": {}, "pending_batch_id": None, "replacement_batch": None, "checkpoint": 0,
            "checkpoint_history": [], "operations": {}, "migration": {"status": "unconfigured"}}


def revision(record):
    return record["revisions"][-1]


def reference(record):
    return {"id": record["id"], "revision": len(record["revisions"]),
            "sha256": revision(record)["sha256"]}


def lookup(state, record_id):
    require(integer(record_id, 1), "Record ID must be a positive integer")
    for record in state["records"]:
        if record["id"] == record_id:
            return record
    raise LedgerError(f"Record {record_id} does not exist")


def find_duplicate(state, block):
    block_hash = digest(block)
    for record in state["records"]:
        for index in range(len(record["revisions"]), 0, -1):
            rev = record["revisions"][index - 1]
            if rev["sha256"] == block_hash:
                require(rev["block"] == block, "Digest collision")
                return {"id": record["id"], "revision": index, "sha256": block_hash,
                        "superseded": index != len(record["revisions"])}
    return None


def verify_state(state, files):
    require(state.get("schema") == SCHEMA, "Unsupported ledger schema")
    if state.get("updated_at") is not None:
        timestamp(state["updated_at"])
    require(integer(state.get("generation")) and integer(state.get("checkpoint")), "Invalid checkpoint")
    require(isinstance(state.get("records"), list), "Invalid records")
    ids = [r.get("id") for r in state["records"]]
    require(all(integer(i, 1) for i in ids) and ids == sorted(set(ids)), "Record IDs must be unique and ordered")
    require(integer(state.get("next_id"), 1) and state["next_id"] == (max(ids, default=0) + 1),
            "Invalid monotonic next_id")
    require(state["checkpoint"] == 0 or state["checkpoint"] in ids, "Checkpoint is outside imported records")
    require(isinstance(state.get("requests"), dict) and isinstance(state.get("batches"), dict)
            and isinstance(state.get("operations"), dict), "Invalid ledger collections")
    for record in state["records"]:
        require(isinstance(record.get("revisions"), list) and record["revisions"], "Missing record revisions")
        for rev in record["revisions"]:
            require(isinstance(rev.get("source"), str), "Invalid source")
            block_fields(rev.get("block"), preserve=True)
            require(rev.get("sha256") == digest(rev["block"]), "Record hash mismatch")
            timestamp(rev.get("created_at"))
    for request_id, request in state["requests"].items():
        opaque(request_id, "request ID")
        require(request.get("status") in {"received", "finalized", "reconciled"}, "Invalid intake status")
        require(integer(request.get("expected_items"), 1), "Invalid expected item count")
        require(integer(request.get("received_sequence"), 1), "Invalid intake ingress sequence")
        if request["status"] != "received":
            require(isinstance(request.get("records"), list) and len(request["records"]) == request["expected_items"],
                    "Resolved intake count differs from expected items")
            for ref in request["records"]:
                record = lookup(state, ref["id"])
                require(integer(ref.get("revision"), 1) and ref["revision"] <= len(record["revisions"]),
                        "Resolved intake has a missing revision")
                require(record["revisions"][ref["revision"] - 1]["sha256"] == ref["sha256"],
                        "Resolved intake has a mismatched digest")
    for batch_id, batch in state["batches"].items():
        require(batch_id == batch.get("batch_id") and batch.get("status") in {
            "prepared", "published", "delivered", "superseded"}, "Invalid batch state")
        timestamp(batch.get("prepared_at"))
        require(integer(batch.get("intake_cutoff")), "Invalid batch intake cutoff")
        entries = []
        require(isinstance(batch.get("records"), list) and batch["records"], "Batch has no records")
        batch_ids = [ref.get("id") for ref in batch["records"]]
        require(all(integer(i, 1) for i in batch_ids) and batch_ids == sorted(set(batch_ids)),
                "Batch record IDs must be unique and ordered")
        require(batch.get("first_id") == batch_ids[0] and batch.get("last_id") == batch_ids[-1]
                and batch.get("count") == len(batch_ids), "Batch boundary/count mismatch")
        require(integer(batch.get("checkpoint_before")) and batch["checkpoint_before"] < batch_ids[0],
                "Invalid batch checkpoint")
        require(batch_ids == [rid for rid in ids if batch["checkpoint_before"] < rid <= batch["last_id"]],
                "Batch skips queued records")
        require(batch_id == digest(canonical({"checkpoint": batch["checkpoint_before"],
                                             "records": batch["records"]}))[:24], "Batch identity mismatch")
        delivery = batch.get("delivery")
        require(isinstance(delivery, dict) and delivery.get("status") in {
            "not_started", "in_flight", "uncertain", "failed", "accepted"}
            and isinstance(delivery.get("attempts"), list), "Invalid delivery state")
        if delivery["attempts"]:
            require(delivery["attempts"][-1].get("status") == delivery["status"], "Delivery attempt/state mismatch")
            attempt_ids = [a.get("attempt_id") for a in delivery["attempts"]]
            require(len(set(attempt_ids)) == len(attempt_ids), "Duplicate delivery attempt identity")
            for attempt in delivery["attempts"]:
                opaque(attempt.get("attempt_id"), "attempt ID")
                timestamp(attempt.get("started_at"))
                sha(attempt.get("target_sha256"))
                require(attempt.get("status") in {"in_flight", "uncertain", "failed", "accepted"}, "Invalid attempt status")
        else:
            require(delivery["status"] == "not_started", "Delivery outcome has no attempt")
        require((batch["status"] == "delivered") == (delivery["status"] == "accepted"),
                "Delivered/accepted state mismatch")
        if batch["status"] == "delivered":
            require(state["checkpoint"] >= batch["last_id"], "Delivered batch exceeds checkpoint")
            receipt = delivery["attempts"][-1].get("receipt", {})
            require(receipt.get("accepted") is True and receipt.get("channel") == "chatgpt"
                    and receipt.get("attachment_sha256") == batch.get("txt_sha256")
                    and receipt.get("target_sha256") == delivery["attempts"][-1]["target_sha256"],
                    "Invalid persisted delivery receipt")
            accepted_at = timestamp(receipt.get("accepted_at"))
            acknowledged_at = timestamp(batch.get("acknowledged_at"))
            require(datetime.fromisoformat(delivery["attempts"][-1]["started_at"]) <= datetime.fromisoformat(accepted_at)
                    <= datetime.fromisoformat(acknowledged_at) <= datetime.fromisoformat(state["updated_at"]),
                    "Persisted receipt chronology is invalid")
            sha(receipt.get("message_receipt_sha256"))
            sha(receipt.get("native_attachment_receipt_sha256"))
            require(any(event.get("kind") == "delivery_acknowledgment" and event.get("batch_id") == batch_id
                        and event.get("checkpoint") == batch["last_id"] and event.get("receipt") == receipt
                        for event in state["checkpoint_history"]), "Delivery lacks matching checkpoint history")
        for ref in batch["records"]:
            record = lookup(state, ref["id"])
            require(integer(ref.get("revision"), 1) and ref["revision"] <= len(record["revisions"]),
                    "Batch revision is missing")
            rev = record["revisions"][ref["revision"] - 1]
            require(rev["sha256"] == ref["sha256"], "Batch revision hash mismatch")
            if batch["status"] in {"prepared", "published"}:
                require(ref == reference(record), "Pending batch references a superseded record")
            entries.append(rev)
        txt, js = render_txt(entries), encoded(github_items(entries, batch["prepared_at"][:10]))
        require(files.get(batch["txt_path"]) == txt and batch["txt_sha256"] == digest(txt),
                "Immutable TXT artifact is missing or altered")
        require(files.get(batch["json_path"]) == js and batch["json_sha256"] == digest(js),
                "Immutable JSON artifact is missing or altered")
        publication = batch.get("publication")
        if batch["status"] in {"published", "delivered"}:
            require(isinstance(publication, dict) and publication.get("sha256") == digest(js)
                    and files.get(publication.get("path")) == js, "Published item is missing or altered")
    history = state.get("checkpoint_history")
    require(isinstance(history, list), "Invalid checkpoint history")
    for event in history:
        if event.get("kind") == "legacy_checkpoint_import":
            for artifact in event.get("imported_exports", []):
                require(isinstance(artifact, dict) and isinstance(files.get(artifact.get("path")), str)
                        and digest(files[artifact["path"]]) == artifact.get("sha256"),
                        "Immutable historical export is missing or altered")
    require(state["checkpoint"] == (history[-1].get("checkpoint") if history else 0),
            "Checkpoint differs from history")
    sequences = [request["received_sequence"] for request in state["requests"].values()]
    require(len(sequences) == len(set(sequences)), "Duplicate intake ingress sequence")
    replacement = state.get("replacement_batch")
    if replacement is not None:
        require(isinstance(replacement, dict) and integer(replacement.get("intake_cutoff"))
                and isinstance(replacement.get("record_ids"), list) and replacement["record_ids"],
                "Invalid replacement batch")
        replacement_ids = replacement["record_ids"]
        require(replacement_ids == sorted(set(replacement_ids))
                and all(rid in ids and rid > state["checkpoint"] for rid in replacement_ids),
                "Invalid replacement membership")
        require(state.get("pending_batch_id") is None, "Replacement conflicts with active batch")
    active = [key for key, batch in state["batches"].items() if batch["status"] in {"prepared", "published"}]
    pending = state.get("pending_batch_id")
    require(active == ([pending] if pending else []), "Orphan or competing active batch")
    if pending is not None:
        require(pending in state["batches"], "Missing pending batch")
        batch = state["batches"][pending]
        require(batch["status"] in {"prepared", "published"} and batch["checkpoint_before"] == state["checkpoint"],
                "Pending checkpoint/state mismatch")
        require(all(ref["id"] > state["checkpoint"] for ref in batch["records"]), "Pending batch overlaps checkpoint")


def intake_gate(state, batch=None):
    require(state["migration"].get("status") == "reconciled", "Migration/intake boundary is unresolved")
    cutoff = batch["intake_cutoff"] if batch is not None else None
    selected_ids = {ref["id"] for ref in batch.get("records", [])} if batch else set()
    if batch and "record_ids" in batch:
        selected_ids = set(batch["record_ids"])
    unresolved = [key for key, value in state["requests"].items() if value["status"] == "received"
                  and (cutoff is None or value["received_sequence"] <= cutoff
                       or value.get("corrects_record_id") in selected_ids)]
    require(not unresolved, "Unresolved intakes: " + ", ".join(unresolved))


def pending_batch(state, operation):
    batch_id = operation.get("batch_id")
    require(batch_id == state["pending_batch_id"] and batch_id in state["batches"], "Wrong pending batch")
    return state["batches"][batch_id]


def active_request(state, operation):
    request_id = opaque(operation.get("request_id"), "request ID")
    require(request_id in state["requests"], "Receive intake durably before processing it")
    request = state["requests"][request_id]
    require(request["status"] == "received", "Intake is already resolved; use its existing durable result")
    earlier = [key for key, value in state["requests"].items() if value["status"] == "received"
               and value["received_sequence"] < request["received_sequence"]]
    require(not earlier, "Finalize earlier received intakes first: " + ", ".join(earlier))
    return request_id, request


def make_revision(block, source, now, request_id, mode):
    require(isinstance(source, str), "Source must be a string")
    return {"created_at": now, "block": block, "sha256": digest(block), "source": source.strip(),
            "request_id": request_id, "mode": mode}


def put_immutable(files, changes, path, content):
    require(path not in files or files[path] == content, f"Immutable path already differs: {path}")
    if path not in files:
        changes[path] = content


def result_status(state):
    return {"status": "ok", "records": len(state["records"]), "last_record_id": state["next_id"] - 1,
            "checkpoint": state["checkpoint"], "queued_count": sum(r["id"] > state["checkpoint"] for r in state["records"]),
            "pending_batch_id": state["pending_batch_id"], "migration": state["migration"]["status"],
            "unresolved_requests": [key for key, value in state["requests"].items() if value["status"] == "received"]}


def transition(state, files, op, policy, head, changes):
    kind, now = op["kind"], timestamp(op.get("at"))
    require(state.get("updated_at") is None or datetime.fromisoformat(now) >= datetime.fromisoformat(state["updated_at"]),
            "Operation timestamp predates committed ledger state")
    if kind in {"prepare", "publish", "begin_delivery"}:
        require(policy.get("compilation_enabled") is True and policy.get("cutover_confirmation_sha256"),
                "Cloud compilation is paused until the old compiler stop/cutover is confirmed")
    if kind == "initialize":
        require(state["generation"] == 0 and not state["records"], "Ledger is already initialized")
        state["migration"] = {"status": "reconciled", "at": now,
                              "evidence_sha256": sha(op.get("boundary_evidence_sha256"))}
        initial_items = op.get("initial_items", [])
        require(isinstance(initial_items, list), "Initial items must be a list")
        if initial_items:
            evidence = sha(op.get("seed_evidence_sha256"))
            for item in initial_items:
                require(isinstance(item, dict), "Initial item must be an object")
                block = validate_block(item.get("block"), policy, mode="user_finalized_seed")
                require(find_duplicate(state, block) is None, "Initial seed is an exact duplicate")
                request_id = "seed_" + digest(block)
                record = {"id": state["next_id"], "revisions": [make_revision(
                    block, item.get("source", ""), now, request_id, "user_finalized_seed")]}
                revision(record)["provenance"] = {"kind": "user_supplied_finalized_seed", "evidence_sha256": evidence,
                    "image_verification": "preserved_prior_final_output_no_fresh_check"}
                state["records"].append(record)
                state["next_id"] += 1
                state["requests"][request_id] = {"status": "finalized", "received_at": now,
                    "finalized_at": now, "received_sequence": len(state["requests"]) + 1,
                    "expected_items": 1, "mode": "user_finalized_seed", "corrects_record_id": None,
                    "trusted_route_sha256": None, "records": [reference(record)], "evidence_sha256": evidence}
        return {"status": "initialized", "initial_pending_count": len(initial_items)}
    if kind == "import_archive":
        require(state["generation"] == 0 and not state["records"], "Import requires a new ledger")
        records = op.get("records")
        require(isinstance(records, list) and records, "Archive records are required")
        provenance_by_id = op.get("record_provenance", {})
        require(isinstance(provenance_by_id, dict), "Invalid record provenance")
        require(set(provenance_by_id) <= {str(record["id"]) for record in records}, "Provenance names a missing record")
        for record in records:
            block_fields(record["block"], preserve=True)
            require(record["sha256"] == digest(record["block"]), "Imported record hash mismatch")
            provenance = provenance_by_id.get(str(record["id"]))
            if provenance is not None:
                require(isinstance(provenance, dict) and set(provenance) <= {
                    "kind", "evidence_sha256", "github_path", "github_item_index", "github_commit"},
                    "Unsafe record provenance")
                require(provenance.get("kind") in {"public_repository_reconstruction", "user_confirmed_postcompile"},
                        "Unknown supplemental record provenance")
                sha(provenance.get("evidence_sha256"))
                if "github_path" in provenance:
                    require(isinstance(provenance["github_path"], str) and re.fullmatch(
                        r"items/\d{4}-\d{2}-\d{2}(?:-(?:[2-9]|[1-9]\d+))?\.json", provenance["github_path"]),
                        "Unsafe supplemental publication path")
                if "github_item_index" in provenance:
                    require(integer(provenance["github_item_index"], 1), "GitHub item index must be one-based")
                if "github_commit" in provenance:
                    require(isinstance(provenance["github_commit"], str) and re.fullmatch(
                        r"[0-9a-f]{40,64}", provenance["github_commit"]), "Invalid supplemental commit")
            rev = {"created_at": record["created_at"], "block": record["block"], "sha256": record["sha256"],
                   "source": record.get("source", ""), "request_id": None,
                   "mode": provenance["kind"] if provenance else "legacy_import"}
            if provenance is not None:
                rev["provenance"] = copy.deepcopy(provenance)
            state["records"].append({"id": record["id"], "revisions": [rev]})
        state["next_id"] = max(r["id"] for r in records) + 1
        checkpoint = op.get("checkpoint")
        require(integer(checkpoint) and (checkpoint == 0 or checkpoint in [r["id"] for r in records]),
                "Invalid archive checkpoint")
        state["checkpoint"] = checkpoint
        # Caller provides a public-safe digest of the complete original checkpoint document.
        event = {"kind": "legacy_checkpoint_import", "checkpoint": checkpoint, "at": now,
                 "archive_sha256": sha(op.get("archive_sha256")),
                 "checkpoint_document_sha256": sha(op.get("checkpoint_document_sha256"))}
        metadata = op.get("legacy_checkpoint_metadata", {})
        require(isinstance(metadata, dict) and set(metadata) <= {
            "last_exported_at", "last_batch_id", "last_github_filename"}, "Unsafe legacy checkpoint metadata")
        if "last_exported_at" in metadata:
            timestamp(metadata["last_exported_at"])
        if "last_batch_id" in metadata:
            opaque(metadata["last_batch_id"], "legacy batch ID")
        if "last_github_filename" in metadata and metadata["last_github_filename"] is not None:
            require(isinstance(metadata["last_github_filename"], str) and re.fullmatch(
                r"items/\d{4}-\d{2}-\d{2}(?:-(?:[2-9]|[1-9]\d+))?\.json", metadata["last_github_filename"]),
                "Unsafe legacy publication filename")
        event["legacy_metadata"] = copy.deepcopy(metadata)
        imported_exports = []
        for filename, content in op.get("legacy_exports", {}).items():
            require(isinstance(filename, str) and re.fullmatch(r"ANFs_pending_\d+-\d+_[0-9a-f]+\.txt", filename)
                    and isinstance(content, str), "Unsafe legacy export filename/content")
            path = ROOT + "imports/" + event["archive_sha256"][:16] + "/exports/" + filename
            put_immutable(files, changes, path, content)
            imported_exports.append({"path": path, "sha256": digest(content)})
        event["imported_exports"] = imported_exports
        if op.get("legacy_validation_sha256") is not None:
            event["legacy_validation_sha256"] = sha(op["legacy_validation_sha256"])
        state["checkpoint_history"].append(event)
        state["migration"] = {"status": "awaiting_reconciliation", "archive_sha256": event["archive_sha256"],
                              "imported_high_water_id": state["next_id"] - 1}
        return {"status": "imported_reconciliation_required", "records": len(records), "checkpoint": checkpoint}
    if kind == "reconcile_migration":
        require(state["migration"]["status"] == "awaiting_reconciliation", "No migration to reconcile")
        checkpoint = op.get("checkpoint")
        require(integer(checkpoint) and (checkpoint == 0 or any(r["id"] == checkpoint for r in state["records"])),
                "Invalid reconciled checkpoint")
        require(checkpoint <= state["migration"]["imported_high_water_id"],
                "Migration reconciliation cannot acknowledge post-import intake")
        require(not state["pending_batch_id"], "Cannot reconcile migration during a batch")
        evidence = sha(op.get("evidence_sha256"))
        state["checkpoint_history"].append({"kind": "migration_reconciliation", "before": state["checkpoint"],
                                            "checkpoint": checkpoint, "at": now, "evidence_sha256": evidence})
        state["checkpoint"] = checkpoint
        state["migration"] = {**state["migration"], "status": "reconciled", "at": now,
                              "evidence_sha256": evidence}
        return {"status": "migration_reconciled", "checkpoint": checkpoint}
    if kind == "receive":
        request_id = opaque(op.get("request_id"), "request ID")
        count = op.get("expected_items", 1)
        mode = op.get("mode", "standard")
        require(integer(count, 1) and count <= 1000, "Invalid intake count")
        require(mode in {"standard", "trusted_preprocessed"}, "Invalid intake mode")
        trusted_route = op.get("trusted_route_sha256")
        if mode == "trusted_preprocessed":
            require(trusted_route in policy.get("trusted_preprocessed_route_sha256", []),
                    "Trusted preprocessed route is disabled or not explicitly authorized")
        if request_id in state["requests"]:
            prior = state["requests"][request_id]
            require(prior["expected_items"] == count and prior["mode"] == mode
                    and prior.get("trusted_route_sha256") == trusted_route
                    and prior.get("corrects_record_id") == op.get("corrects_record_id"), "Request identity conflict")
            return {"status": "already_received", "request_id": request_id, "intake_status": prior["status"]}
        correction_target = op.get("corrects_record_id")
        if correction_target is not None:
            lookup(state, correction_target)
            require(count == 1, "A correction intake must expect one item")
        state["requests"][request_id] = {"status": "received", "received_at": now,
                                          "received_sequence": max((r["received_sequence"] for r in state["requests"].values()), default=0) + 1,
                                          "expected_items": count, "mode": mode, "trusted_route_sha256": trusted_route,
                                          "corrects_record_id": correction_target}
        return {"status": "received", "request_id": request_id}
    if kind == "finalize":
        request_id, request = active_request(state, op)
        require(request.get("corrects_record_id") is None, "Use correct for a correction intake")
        items = op.get("items")
        require(isinstance(items, list) and len(items) == request["expected_items"], "Finalized item count differs from intake")
        refs, duplicates = [], []
        for item in items:
            require(isinstance(item, dict), "Each finalized item must be an object")
            block = validate_block(item.get("block"), policy, request["mode"], item.get("image_verified"))
            duplicate = find_duplicate(state, block)
            if duplicate:
                refs.append({key: duplicate[key] for key in ("id", "revision", "sha256")})
                duplicates.append(duplicate)
                continue
            record = {"id": state["next_id"], "revisions": [make_revision(
                block, item.get("source", ""), now, request_id, request["mode"])]}
            state["next_id"] += 1
            state["records"].append(record)
            refs.append(reference(record))
        request.update(status="finalized", finalized_at=now, records=refs)
        return {"status": "finalized", "request_id": request_id, "records": refs, "duplicates": duplicates}
    if kind == "reconcile_intake":
        request_id, request = active_request(state, op)
        record_ids = op.get("record_ids")
        require(isinstance(record_ids, list) and len(record_ids) == request["expected_items"],
                "Reconciliation needs one matching durable record for every expected item")
        request.update(status="reconciled", finalized_at=now,
                       records=[reference(lookup(state, rid)) for rid in record_ids],
                       evidence_sha256=sha(op.get("evidence_sha256")))
        return {"status": "intake_reconciled", "request_id": request_id, "records": request["records"]}
    if kind == "correct":
        request_id, request = active_request(state, op)
        require(request["expected_items"] == 1, "Correction must be a single-item intake")
        record = lookup(state, op.get("record_id"))
        require(request.get("corrects_record_id") == record["id"], "Correction target differs from intake")
        require(record["id"] > state["checkpoint"], "Cannot rewrite delivered history")
        for batch in state["batches"].values():
            require(not (batch["status"] in {"published", "delivered"} and any(
                ref["id"] == record["id"] for ref in batch["records"])), "Cannot correct a published record")
        block = validate_block(op.get("block"), policy, request["mode"], op.get("image_verified"))
        duplicate = find_duplicate(state, block)
        require(not duplicate or (duplicate["id"] == record["id"] and not duplicate["superseded"]),
                "Correction duplicates historical content; reconcile explicitly instead")
        source = op.get("source", revision(record)["source"])
        require(isinstance(source, str), "Source must be a string")
        if block != revision(record)["block"] or source.strip() != revision(record)["source"]:
            old_ref = reference(record)
            record["revisions"].append(make_revision(block, source,
                                                       now, request_id, request["mode"]))
            if state["pending_batch_id"]:
                batch = state["batches"][state["pending_batch_id"]]
                if any(ref["id"] == record["id"] for ref in batch["records"]):
                    require(batch["status"] == "prepared", "Published batch cannot be superseded")
                    batch.update(status="superseded", superseded_at=now, corrected_record=old_ref)
                    state["replacement_batch"] = {"record_ids": [ref["id"] for ref in batch["records"]],
                                                  "intake_cutoff": batch["intake_cutoff"]}
                    state["pending_batch_id"] = None
        request.update(status="finalized", finalized_at=now, records=[reference(record)])
        return {"status": "corrected", "record": reference(record)}
    if kind == "prepare":
        if state["pending_batch_id"]:
            batch = state["batches"][state["pending_batch_id"]]
            intake_gate(state, batch)
            return {"status": "prepared", "retry": True, "batch": copy.deepcopy(batch)}
        replacement = state.get("replacement_batch")
        intake_gate(state, replacement)
        selected = ([lookup(state, rid) for rid in replacement["record_ids"]] if replacement else
                    [r for r in state["records"] if r["id"] > state["checkpoint"]])
        cutoff = replacement["intake_cutoff"] if replacement else max(
            (request["received_sequence"] for request in state["requests"].values()), default=0)
        if not selected:
            return {"status": "empty", "checkpoint": state["checkpoint"]}
        refs = [reference(r) for r in selected]
        batch_id = digest(canonical({"checkpoint": state["checkpoint"], "records": refs}))[:24]
        require(batch_id not in state["batches"], "Batch identity already exists")
        entries = [revision(r) for r in selected]
        txt, js = render_txt(entries), encoded(github_items(entries, now[:10]))
        base = ROOT + "batches/" + batch_id
        batch = {"batch_id": batch_id, "status": "prepared", "checkpoint_before": state["checkpoint"],
                 "prepared_at": now, "intake_cutoff": cutoff, "records": refs, "first_id": selected[0]["id"], "last_id": selected[-1]["id"],
                 "count": len(selected), "txt_path": base + ".txt", "json_path": base + ".json",
                 "txt_sha256": digest(txt), "json_sha256": digest(js), "delivery": {"status": "not_started", "attempts": []}}
        put_immutable(files, changes, batch["txt_path"], txt)
        put_immutable(files, changes, batch["json_path"], js)
        state["batches"][batch_id] = batch
        state["pending_batch_id"] = batch_id
        state["replacement_batch"] = None
        return {"status": "prepared", "retry": False, "batch": copy.deepcopy(batch)}
    if kind == "publish":
        batch = pending_batch(state, op)
        intake_gate(state, batch)
        if batch["status"] == "published":
            return {"status": "already_published", "publication": batch["publication"]}
        require(batch["status"] == "prepared", "Batch must be prepared")
        date = batch["prepared_at"][:10]
        suffix = 1
        while True:
            path = f"items/{date}{'' if suffix == 1 else '-' + str(suffix)}.json"
            if path not in files:
                break
            suffix += 1
        content = files[batch["json_path"]]
        put_immutable(files, changes, path, content)
        # The new items file and this metadata MUST be committed in ONE Git tree.
        batch.update(status="published", publication={"path": path, "sha256": digest(content),
                                                      "published_at": now, "planned_from_head": head})
        return {"status": "publication_planned", "batch_id": batch["batch_id"], "publication": batch["publication"]}
    if kind == "begin_delivery":
        batch = pending_batch(state, op)
        intake_gate(state, batch)
        require(batch["status"] == "published", "GitHub publication must be durably visible before sending")
        delivery = batch["delivery"]
        require(delivery["status"] in {"not_started", "failed"},
                "Delivery is in flight or uncertain; reconcile it before any send/retry")
        attempt_id = opaque(op.get("attempt_id"), "attempt ID")
        require(not any(a["attempt_id"] == attempt_id for a in delivery["attempts"]), "Attempt ID already used")
        attempt = {"attempt_id": attempt_id, "started_at": now, "status": "in_flight",
                   "target_sha256": sha(op.get("target_sha256")), "publication_observed_head": head}
        delivery["attempts"].append(attempt)
        delivery["status"] = "in_flight"
        return {"status": "delivery_intent_planned", "batch_id": batch["batch_id"],
                "attempt_id": attempt_id, "txt_path": batch["txt_path"], "txt_sha256": batch["txt_sha256"]}
    if kind in {"delivery_failed", "delivery_uncertain", "reconcile_not_sent", "acknowledge"}:
        batch = pending_batch(state, op)
        require(batch["status"] == "published", "Batch is not published")
        delivery = batch["delivery"]
        require(delivery["attempts"], "No recorded delivery attempt")
        attempt = delivery["attempts"][-1]
        require(attempt["attempt_id"] == op.get("attempt_id"), "Wrong delivery attempt")
        require(delivery["status"] in {"in_flight", "uncertain"}, "No delivery awaiting outcome")
        if kind in {"delivery_failed", "delivery_uncertain", "reconcile_not_sent"}:
            evidence = sha(op.get("evidence_sha256"))
            require(kind != "delivery_failed" or op.get("definitely_not_accepted") is True,
                    "Only a confirmed rejection can permit a retry")
            require(kind != "delivery_failed" or delivery["status"] == "in_flight",
                    "Uncertain send requires explicit reconciliation")
            status = "uncertain" if kind == "delivery_uncertain" else "failed"
            attempt.update(status=status, outcome_at=now, evidence_sha256=evidence,
                           reconciled=kind == "reconcile_not_sent")
            delivery["status"] = status
            return {"status": "delivery_" + status, "checkpoint_advanced": False, "batch_id": batch["batch_id"]}
        receipt = op.get("receipt", {})
        require(receipt.get("channel") == "chatgpt" and receipt.get("accepted") is True,
                "Native chat attachment acceptance receipt required")
        require(receipt.get("attachment_sha256") == batch["txt_sha256"], "Receipt is for another attachment")
        require(receipt.get("target_sha256") == attempt["target_sha256"], "Receipt destination mismatch")
        accepted_at = timestamp(receipt.get("accepted_at"))
        require(datetime.fromisoformat(accepted_at) >= datetime.fromisoformat(attempt["started_at"]),
                "Receipt predates delivery intent")
        require(datetime.fromisoformat(accepted_at) <= datetime.fromisoformat(now),
                "Receipt acceptance is in the future relative to acknowledgment")
        safe_receipt = {"channel": "chatgpt", "accepted": True, "accepted_at": accepted_at,
                        "attachment_sha256": batch["txt_sha256"], "target_sha256": attempt["target_sha256"],
                        "message_receipt_sha256": sha(receipt.get("message_receipt_sha256")),
                        "native_attachment_receipt_sha256": sha(receipt.get("native_attachment_receipt_sha256"))}
        attempt.update(status="accepted", receipt=safe_receipt, outcome_at=now)
        delivery["status"] = "accepted"
        batch.update(status="delivered", acknowledged_at=now)
        state["checkpoint_history"].append({"kind": "delivery_acknowledgment", "before": state["checkpoint"],
                                            "checkpoint": batch["last_id"], "at": now,
                                            "batch_id": batch["batch_id"], "receipt": safe_receipt})
        state["checkpoint"] = batch["last_id"]
        state["pending_batch_id"] = None
        return {"status": "acknowledgment_planned", "checkpoint": state["checkpoint"],
                "batch_id": batch["batch_id"], "publication": batch["publication"]}
    raise LedgerError(f"Unknown operation: {kind}")


def plan(snapshot, operation):
    """Return a transaction; callers must commit all changes atomically using expected base_sha."""
    require(isinstance(snapshot, dict) and snapshot.get("complete") is True,
            "A fresh complete GitHub snapshot is required")
    head = snapshot.get("head")
    require(isinstance(head, str) and re.fullmatch(r"[0-9a-f]{40,64}", head), "Invalid expected parent SHA")
    files = snapshot.get("files")
    require(isinstance(files, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in files.items()),
            "Snapshot files must be a full UTF-8 path/content map for items and workflows/anf")
    require(POLICY in files, "Policy file is missing")
    policy = json.loads(files[POLICY])
    require(set(policy) == {"summary_max_words", "forbidden_url_domains", "forbidden_url_suffixes", "forbidden_image_domains"},
            "Invalid policy shape")
    require(integer(policy["summary_max_words"], 1) and all(isinstance(policy[key], list) and all(
        isinstance(v, str) and v for v in policy[key]) for key in policy if key != "summary_max_words"), "Invalid policy")
    config = json.loads(files.get(CONFIG, '{"trusted_preprocessed_route_sha256": [], "compilation_enabled": false, "cutover_confirmation_sha256": null}'))
    require(isinstance(config, dict) and set(config) == {
        "trusted_preprocessed_route_sha256", "compilation_enabled", "cutover_confirmation_sha256"}
        and isinstance(config["trusted_preprocessed_route_sha256"], list)
        and type(config["compilation_enabled"]) is bool, "Invalid runtime config")
    if config["compilation_enabled"]:
        sha(config["cutover_confirmation_sha256"], "cutover confirmation hash")
    else:
        require(config["cutover_confirmation_sha256"] is None or isinstance(config["cutover_confirmation_sha256"], str),
                "Invalid cutover confirmation")
    for route in config["trusted_preprocessed_route_sha256"]:
        sha(route, "approved trusted route hash")
    policy.update(config)
    state = json.loads(files[LEDGER]) if LEDGER in files else fresh_state()
    verify_state(state, files)
    require(isinstance(operation, dict), "Operation must be an object")
    kind = operation.get("kind")
    if kind in {"status", "preview"}:
        result = result_status(state)
        if kind == "preview":
            result["items"] = [{"id": r["id"], "revision": len(r["revisions"]), **revision(r)}
                               for r in state["records"] if r["id"] > state["checkpoint"]]
        return {"base_sha": head, "changes": [], "result": result, "committed": False}
    require(LEDGER in files or kind in {"initialize", "import_archive"}, "Initialize or import the ledger first")
    op_id = opaque(operation.get("operation_id"), "operation ID")
    op_hash = digest(canonical(operation))
    if op_id in state["operations"]:
        prior = state["operations"][op_id]
        require(prior["sha256"] == op_hash, "Operation ID reused for a different operation")
        return {"base_sha": head, "changes": [], "result": {"status": "operation_replayed", "original_result": prior["result"],
                      "current_state": result_status(state)}, "replayed": True,
                "committed": True, "operation_id": op_id, "send_authorized": False,
                "warning": "Prior operation found. Never resend on replay; reconcile existing delivery intent."}
    changes = {}
    result = transition(state, files, operation, policy, head, changes)
    state["generation"] += 1
    state["updated_at"] = timestamp(operation["at"])
    state["operations"][op_id] = {"sha256": op_hash, "result": copy.deepcopy(result)}
    final_files = {**files, **changes}
    verify_state(state, final_files)
    changes[LEDGER] = encoded(state)
    return {"base_sha": head, "operation_id": op_id,
            "changes": [{"path": path, "content": content} for path, content in sorted(changes.items())],
            "result": result, "committed": False,
            "send_authorized": False,
            "warning": "Plan only. Save every change in one CAS commit and read back before reporting success or sending."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="Input JSON path; defaults to stdin")
    parser.add_argument("--output", type=Path, help="Write commit plan here instead of stdout")
    args = parser.parse_args()
    try:
        value = json.loads(args.input.read_text(encoding="utf-8") if args.input else sys.stdin.read())
        output = encoded(plan(value["snapshot"], value["operation"]))
        if args.output:
            args.output.write_text(output, encoding="utf-8")
        else:
            sys.stdout.write(output)
        return 0
    except (LedgerError, KeyError, TypeError, ValueError, AttributeError, OSError) as exc:
        sys.stdout.write(encoded({"status": "error", "saved": False, "checkpoint_advanced": False,
                                 "error": str(exc)}))
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
