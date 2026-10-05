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


def output_url_allowed(url, field, policy, rejections=()):
    hostname = host(url)
    domains = list(policy["forbidden_url_domains"])
    if field == "image":
        domains += policy["forbidden_image_domains"]
    require(not matches_domain(hostname, domains)
            and not any(hostname.endswith(s) for s in policy["forbidden_url_suffixes"]),
            "Final " + field + " URL violates domain policy")
    for rule in rejections:
        if rule.get("resolved_at") or rule["field"] not in {field, "both"}:
            continue
        rejected = url == rule["url"] if rule["scope"] == "url" else matches_domain(hostname, [host(rule["url"])])
        require(not rejected, "Final " + field + " URL matches evidenced rejection " + rule["rejection_id"])



def frozen_conflict_gate(state, batch):
    """New adverse evidence stops sending; never rewrites already frozen bytes."""
    for index, ref in enumerate(batch["records"]):
        record = lookup(state, ref["id"])
        rev = record["revisions"][ref["revision"] - 1]
        _, fields = block_fields(rev["block"], preserve=True)
        editorial = batch.get("editorial", [])
        frozen_review = editorial[index] if editorial else None
        origin = origin_request(state, record).get("origin", {})
        if origin.get("kind") == "data_science_corner":
            require(frozen_review is not None and frozen_review["audience"]["decision"] == "technical",
                    "Frozen audience conflicts with authenticated DataScienceCorner provenance; report for recovery")
        for field, key in (("article", "learn_more_url"), ("image", "image_url")):
            urls = [fields[key]] if fields[key] else []
            if frozen_review:
                urls += frozen_review.get("quality", {}).get(field, {}).get("redirect_chain", [])
            # Only new explicit adverse observations apply here. Do not retrofit
            # current policy or quality age onto frozen legacy artifacts.
            for url in urls:
                for rule in state.get("url_rejections", []):
                    if rule.get("resolved_at") or rule["field"] not in {field, "both"}:
                        continue
                    rejected = url == rule["url"] if rule["scope"] == "url" else matches_domain(host(url), [host(rule["url"])])
                    require(not rejected, "Frozen output matches an active evidenced rejection; report for recovery")


def validate_block(content, policy, mode="standard", image_verified=False):
    require(mode in {"standard", "trusted_preprocessed", "user_finalized_seed", "image_url_only"}, "Unknown intake mode")
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
    if policy.get("export_format_version", 1) >= 2:
        output_url_allowed(fields["image_url"], "image", policy)
    else:
        require(not matches_domain(host(fields["image_url"]), policy["forbidden_image_domains"]),
                "Image URL violates domain policy")
    if mode not in {"user_finalized_seed", "image_url_only"}:
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


def github_items(entries, export_date, editorial=None):
    result = []
    for index, entry in enumerate(entries):
        _, fields = block_fields(entry["block"], preserve=True)
        result.append({"title": fields["title"], "description": fields["description"],
                       "image_url": fields["image_url"], "learn_more_url": fields["learn_more_url"],
                       "date": export_date,
                       "source": entry["source"] or infer_source(fields["learn_more_url"])})
        if editorial is not None and editorial[index]["audience"]["decision"] == "technical":
            result[-1]["ds"] = True
    return result


def render_txt(entries, editorial=None):
    return "\n\n".join(entry["block"] + (
        "\nds: true" if editorial is not None and editorial[index]["audience"]["decision"] == "technical" else "")
        for index, entry in enumerate(entries)) + TRAILER



def validate_origin(origin):
    require(isinstance(origin, dict) and set(origin) == {"kind", "evidence_sha256"}
            and origin["kind"] == "data_science_corner", "Invalid authenticated source provenance")
    sha(origin["evidence_sha256"], "source provenance evidence")


def validate_editorial(editorial, rev, request, policy, rejections=(), at=None, require_quality=True):
    require(isinstance(editorial, dict) and {"audience"} <= set(editorial) <= {"audience", "quality", "origin"}, "Editorial audience review is required")
    if "origin" in editorial:
        validate_origin(editorial["origin"])
        request = {**request, "origin": editorial["origin"]}
    audience = editorial["audience"]
    require(isinstance(audience, dict) and set(audience) == {"decision", "basis", "rationale", "evidence_sha256"},
            "Invalid audience review")
    require(audience["decision"] in {"technical", "general"}, "Audience must be explicitly technical or general")
    require(audience["basis"] in {"api", "developer_tool", "open_source", "research", "technical_practice", "general", "data_science_corner"},
            "Invalid audience basis")
    require((audience["decision"] == "general") == (audience["basis"] == "general"), "Audience decision and basis disagree")
    require(isinstance(audience["rationale"], str) and 10 <= len(audience["rationale"].strip()) <= 1000,
            "Audience needs a public-safe evidence-based rationale")
    sha(audience["evidence_sha256"], "audience evidence")
    if request.get("origin", {}).get("kind") == "data_science_corner":
        require(audience["decision"] == "technical" and audience["basis"] == "data_science_corner",
                "DataScienceCorner provenance always requires ds: true")
    if audience["basis"] == "data_science_corner":
        require(request.get("origin", {}).get("kind") == "data_science_corner", "DataScienceCorner needs authenticated ingress provenance")
    # Compilation can reuse durable finalized content without new access/image
    # assertions. Domain rules and explicit adverse evidence remain mandatory.
    _, fields = block_fields(rev["block"], preserve=True)
    for field, output_key in (("article", "learn_more_url"), ("image", "image_url")):
        if fields[output_key]:
            output_url_allowed(fields[output_key], field, policy, rejections)
        else:
            require(field == "article", "Final image URL must not be empty")
    if not require_quality:
        quality = editorial.get("quality", {})
        require(isinstance(quality, dict), "Invalid existing quality evidence")
        for field in ("article", "image"):
            check = quality.get(field, {})
            require(isinstance(check, dict), "Invalid existing URL evidence")
            chain = check.get("redirect_chain", [])
            require(isinstance(chain, list), "Invalid existing redirect evidence")
            for url in chain:
                output_url_allowed(url, field, policy, rejections)
        return editorial
    quality = editorial.get("quality")
    require(isinstance(quality, dict) and set(quality) == {"article", "image"}, "Both URL and image reviews are required")
    _, fields = block_fields(rev["block"], preserve=True)
    for field, output_key in (("article", "learn_more_url"), ("image", "image_url")):
        check = quality[field]
        require(isinstance(check, dict) and check.get("url") == fields[output_key], "Quality review must bind exact output URL")
        checked_at = datetime.fromisoformat(timestamp(check.get("checked_at")))
        sha(check.get("evidence_sha256"), "quality evidence")
        if at is not None:
            age = (datetime.fromisoformat(timestamp(at)) - checked_at).total_seconds()
            require(0 <= age <= policy.get("quality_max_age_hours", 48) * 3600, "Quality review is stale or future-dated")
        if field == "article" and not check["url"]:
            require(check.get("status") == "blank_no_compliant_source", "Blank URL needs a documented no-compliant-source review")
            continue
        require(check.get("status") == "accessible_here", "Output URL must have actually loaded in the available environment")
        require(check.get("chase_status") in {"unknown", "verified_accessible"}, "Chase status must distinguish unknown from verified")
        if check["chase_status"] == "verified_accessible":
            sha(check.get("chase_evidence_sha256"), "actual Chase verification evidence")
        chain = check.get("redirect_chain")
        require(isinstance(chain, list) and chain and chain[0] == check["url"]
                and chain[-1] == check.get("final_url"), "Record every observed redirect including output and final URLs")
        for url in chain:
            output_url_allowed(url, field, policy, rejections)
        if field == "article":
            require(check.get("same_event") is True, "Article must match this exact story")
        else:
            require(isinstance(check.get("content_type"), str) and check["content_type"].startswith("image/"), "Image response must have an image MIME type")
            require(check.get("pixels_inspected") is True, "Inspect actual image pixels, not just metadata")
            require(integer(check.get("width"), policy.get("min_image_width", 600))
                    and integer(check.get("height"), policy.get("min_image_height", 315)), "Image resolution is below the quality floor")
            require(check.get("relevance") in {"story_specific", "topic_specific", "official_logo"}, "Reject unrelated or generic decorative images")
            require(isinstance(check.get("relevance_note"), str) and 10 <= len(check["relevance_note"].strip()) <= 1000,
                    "Describe the inspected pixels and their connection to the story")
            sha(check.get("image_bytes_sha256"), "inspected image bytes")
            if check["relevance"] != "story_specific":
                require(check.get("story_specific_available") is False and isinstance(check.get("fallback_reason"), str)
                        and len(check["fallback_reason"].strip()) >= 10, "Use available story-specific imagery before any fallback")
    return editorial


def origin_request(state, record):
    # Source provenance follows the story across corrections and exact duplicates.
    for request in state["requests"].values():
        if request.get("origin", {}).get("kind") == "data_science_corner" and any(
                ref["id"] == record["id"] for ref in request.get("records", [])):
            return request
    for key, reviews in state.get("editorial_reviews", {}).items():
        if key.split(":")[0] == str(record["id"]):
            for review in reviews:
                origin = review["editorial"].get("origin")
                if origin:
                    return {"origin": origin}
    return state["requests"].get(revision(record).get("request_id"), {})


def review_for(state, record):
    key = str(record["id"]) + ":" + str(len(record["revisions"]))
    reviews = state.get("editorial_reviews", {}).get(key, [])
    return copy.deepcopy(reviews[-1]["editorial"]) if reviews else None


def assert_unfrozen(state, record):
    require(record["id"] > state["checkpoint"], "Cannot review delivered history")
    require(not any(batch["status"] in {"prepared", "published", "delivered"} and any(
        ref["id"] == record["id"] for ref in batch["records"]) for batch in state["batches"].values()),
        "Cannot change editorial review for a frozen batch; retain retry bytes")


def fresh_state():
    return {"schema": SCHEMA, "generation": 0, "updated_at": None, "next_id": 1, "records": [], "requests": {},
            "batches": {}, "pending_batch_id": None, "replacement_batch": None, "checkpoint": 0,
            "checkpoint_history": [], "operations": {}, "migration": {"status": "unconfigured"}}


def revision(record):
    return record["revisions"][-1]


def reference(record):
    return {"id": record["id"], "revision": len(record["revisions"]),
            "sha256": revision(record)["sha256"]}


def delivered_ids(state):
    # The contiguous checkpoint alone is insufficient after a sparse v2 batch.
    return {r["id"] for r in state["records"] if r["id"] <= state["checkpoint"]} | {
        ref["id"] for batch in state["batches"].values() if batch["status"] == "delivered"
        for ref in batch["records"]}


def queued_records(state):
    delivered = delivered_ids(state)
    return [record for record in state["records"] if record["id"] not in delivered]


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


def validate_cancellation_operation(op):
    require(isinstance(op, dict) and set(op) == {
        "kind", "operation_id", "at", "request_id", "reason_code",
        "authorization_sha256", "expected_request_sha256"}, "Invalid cancellation operation fields")
    require(op["kind"] == "cancel_intake" and op["reason_code"] == "user_requested_cancellation",
            "Cancellation requires explicit user authorization, not an automatic failure policy")
    opaque(op["operation_id"], "operation ID")
    opaque(op["request_id"], "request ID")
    timestamp(op["at"])
    sha(op["authorization_sha256"], "cancellation authorization hash")
    require(op["authorization_sha256"] != "0" * 64, "Missing cancellation authorization evidence")
    sha(op["expected_request_sha256"], "expected request hash")


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
    for key, reviews in state.get("editorial_reviews", {}).items():
        require(isinstance(key, str) and re.fullmatch(r"[1-9][0-9]*:[1-9][0-9]*", key)
                and isinstance(reviews, list) and reviews, "Invalid editorial review history")
        rid, index = map(int, key.split(":"))
        record = lookup(state, rid)
        require(index <= len(record["revisions"]), "Editorial review revision is missing")
        for review in reviews:
            require(review["reference"] == {"id": rid, "revision": index, "sha256": record["revisions"][index-1]["sha256"]},
                    "Editorial review does not match revision")
            require(review["sha256"] == digest(canonical(review["editorial"])), "Editorial review hash mismatch")
            timestamp(review["reviewed_at"])
            require(review.get("operation_id") in state["operations"], "Editorial review lacks audited operation")
    for rule in state.get("url_rejections", []):
        host(rule["url"])
        require(rule["field"] in {"article", "image", "both"} and rule["scope"] in {"url", "host"}, "Invalid rejection rule")
        sha(rule["evidence_sha256"])
        timestamp(rule["created_at"])
    for request_id, request in state["requests"].items():
        opaque(request_id, "request ID")
        if "origin" in request:
            validate_origin(request["origin"])
        if request.get("mode") == "image_url_only":
            sha(request.get("image_review_deferral_evidence_sha256"), "image-review deferral evidence")
        require(request.get("status") in {"received", "finalized", "reconciled", "cancelled"}, "Invalid intake status")
        require(integer(request.get("expected_items"), 1), "Invalid expected item count")
        require(integer(request.get("received_sequence"), 1), "Invalid intake ingress sequence")
        if request["status"] == "cancelled":
            audit = request.get("cancellation")
            validate_cancellation_operation(audit)
            require(audit["request_id"] == request_id and not request.get("records"),
                    "Cancelled intake cannot contain finalized records")
            require(timestamp(request.get("cancelled_at")) == timestamp(audit["at"])
                    and datetime.fromisoformat(timestamp(request["received_at"]))
                    <= datetime.fromisoformat(request["cancelled_at"])
                    <= datetime.fromisoformat(timestamp(state["updated_at"])), "Invalid cancellation chronology")
            before = copy.deepcopy(request)
            before.pop("cancellation")
            before.pop("cancelled_at")
            before["status"] = "received"
            require(digest(canonical(before)) == audit["expected_request_sha256"],
                    "Cancelled intake differs from authorized target state")
            persisted = state["operations"].get(audit["operation_id"], {})
            require(persisted.get("sha256") == digest(canonical(audit))
                    and persisted.get("result") == {"status": "intake_cancelled", "request_id": request_id,
                        "expected_items": request["expected_items"], "cancelled_at": request["cancelled_at"],
                        "checkpoint_advanced": False}, "Cancellation audit operation is missing or altered")
        elif request["status"] != "received":
            require(isinstance(request.get("records"), list) and len(request["records"]) == request["expected_items"],
                    "Resolved intake count differs from expected items")
            for ref in request["records"]:
                record = lookup(state, ref["id"])
                require(integer(ref.get("revision"), 1) and ref["revision"] <= len(record["revisions"]),
                        "Resolved intake has a missing revision")
                require(record["revisions"][ref["revision"] - 1]["sha256"] == ref["sha256"],
                        "Resolved intake has a mismatched digest")
        if request["status"] != "cancelled":
            require("cancellation" not in request and "cancelled_at" not in request,
                    "Cancelled intake cannot be reopened")
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
        if batch.get("format_version", 1) == 1:
            require(batch_ids == [rid for rid in ids if batch["checkpoint_before"] < rid <= batch["last_id"]],
                    "Batch skips queued records")
        deferred = batch.get("deferred_request_ids", [])
        require(isinstance(deferred, list) and all(isinstance(key, str) for key in deferred)
                and len(deferred) == len(set(deferred)), "Invalid deferred intake list")
        for key in deferred:
            require(key in state["requests"]
                    and state["requests"][key]["received_sequence"] <= batch["intake_cutoff"]
                    and state["requests"][key].get("corrects_record_id") not in batch_ids,
                    "Invalid deferred intake or selected-record correction")
        if "eligibility_at" in batch:
            eligible_at = datetime.fromisoformat(timestamp(batch["eligibility_at"]))
            require(eligible_at <= datetime.fromisoformat(batch["prepared_at"]),
                    "Eligibility cutoff is after preparation")
            require(all(datetime.fromisoformat(lookup(state, rid)["revisions"][0]["created_at"]) <= eligible_at
                        for rid in batch_ids), "Batch contains a record created after its cutoff")
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
            if batch.get("format_version", 1) == 1:
                require(state["checkpoint"] >= batch["last_id"], "Delivered batch exceeds checkpoint")
            else:
                require(integer(batch.get("checkpoint_after")) and batch["checkpoint_before"] <= batch["checkpoint_after"] <= state["checkpoint"],
                        "Invalid sparse-batch checkpoint")
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
                        and event.get("checkpoint") == batch.get("checkpoint_after", batch["last_id"]) and event.get("receipt") == receipt
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
        version = batch.get("format_version", 1)
        require(version in {1, 2}, "Unsupported frozen export format")
        editorial = batch.get("editorial") if version == 2 else None
        if version == 2:
            require(isinstance(editorial, list) and len(editorial) == len(entries), "Missing frozen editorial reviews")
            for ref, review in zip(batch["records"], editorial):
                history = state.get("editorial_reviews", {}).get(str(ref["id"]) + ":" + str(ref["revision"]), [])
                require(any(item["editorial"] == review for item in history), "Frozen review lacks durable provenance")
        txt, js = render_txt(entries, editorial), encoded(github_items(entries, batch["prepared_at"][:10], editorial))
        require(files.get(batch["txt_path"]) == txt and batch["txt_sha256"] == digest(txt),
                "Immutable TXT artifact is missing or altered")
        require(files.get(batch["json_path"]) == js and batch["json_sha256"] == digest(js),
                "Immutable JSON artifact is missing or altered")
        publication = batch.get("publication")
        if batch["status"] in {"published", "delivered"}:
            require(isinstance(publication, dict) and publication.get("sha256") == digest(js)
                    and files.get(publication.get("path")) == js, "Published item is missing or altered")
    occupied = set()
    for batch in state["batches"].values():
        if batch["status"] in {"prepared", "published", "delivered"}:
            membership = {ref["id"] for ref in batch["records"]}
            require(not occupied.intersection(membership), "Record appears in competing or duplicate delivery batches")
            occupied.update(membership)
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
    deferred = set(batch.get("deferred_request_ids", [])) if batch else set()
    unresolved = [key for key, value in state["requests"].items() if value["status"] == "received"
                  and (value.get("corrects_record_id") in selected_ids
                       or (key not in deferred and (cutoff is None or value["received_sequence"] <= cutoff)))]
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
    # Independent requests finish independently. Only competing corrections to
    # the same record retain ingress order, preventing stale results overwrites.
    target = request.get("corrects_record_id")
    earlier = [key for key, value in state["requests"].items() if target is not None
               and value["status"] == "received"
               and value.get("corrects_record_id") == target
               and value["received_sequence"] < request["received_sequence"]]
    require(not earlier, "Finalize earlier received corrections for this record first: " + ", ".join(earlier))
    return request_id, request


def make_revision(block, source, now, request_id, mode):
    require(isinstance(source, str), "Source must be a string")
    result = {"created_at": now, "block": block, "sha256": digest(block), "source": source.strip(),
              "request_id": request_id, "mode": mode}
    if mode == "image_url_only":
        result["image_verification"] = "pending_compilation_review"
    return result


def put_immutable(files, changes, path, content):
    require(path not in files or files[path] == content, f"Immutable path already differs: {path}")
    if path not in files:
        changes[path] = content


def result_status(state):
    return {"status": "ok", "records": len(state["records"]), "last_record_id": state["next_id"] - 1,
            "checkpoint": state["checkpoint"], "queued_count": len(queued_records(state)),
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
        require(mode in {"standard", "trusted_preprocessed", "image_url_only"}, "Invalid intake mode")
        if mode == "image_url_only":
            sha(op.get("image_review_deferral_evidence_sha256"), "image-review deferral authorization evidence")
        trusted_route = op.get("trusted_route_sha256")
        if mode == "trusted_preprocessed":
            require(trusted_route in policy.get("trusted_preprocessed_route_sha256", []),
                    "Trusted preprocessed route is disabled or not explicitly authorized")
        if "origin" in op:
            validate_origin(op["origin"])
        if request_id in state["requests"]:
            prior = state["requests"][request_id]
            require(prior["expected_items"] == count and prior["mode"] == mode
                    and prior.get("trusted_route_sha256") == trusted_route
                    and prior.get("corrects_record_id") == op.get("corrects_record_id")
                    and prior.get("origin") == op.get("origin")
                    and prior.get("image_review_deferral_evidence_sha256") == op.get("image_review_deferral_evidence_sha256"), "Request identity conflict")
            return {"status": "already_received", "request_id": request_id, "intake_status": prior["status"]}
        correction_target = op.get("corrects_record_id")
        if correction_target is not None:
            lookup(state, correction_target)
            require(count == 1, "A correction intake must expect one item")
        state["requests"][request_id] = {"status": "received", "received_at": now,
                                          "received_sequence": max((r["received_sequence"] for r in state["requests"].values()), default=0) + 1,
                                          "expected_items": count, "mode": mode, "trusted_route_sha256": trusted_route,
                                          "corrects_record_id": correction_target}
        if "origin" in op:
            state["requests"][request_id]["origin"] = copy.deepcopy(op["origin"])
        if mode == "image_url_only":
            state["requests"][request_id]["image_review_deferral_evidence_sha256"] = op["image_review_deferral_evidence_sha256"]
        return {"status": "received", "request_id": request_id}
    if kind == "cancel_intake":
        validate_cancellation_operation(op)
        request_id = op["request_id"]
        require(request_id in state["requests"], "Cancellation target does not exist")
        request = state["requests"][request_id]
        require(request["status"] == "received", "Only unresolved received intake can be cancelled")
        require(not request.get("records") and not any(
            rev.get("request_id") == request_id for record in state["records"] for rev in record["revisions"]),
            "Cancellation cannot discard finalized records")
        require(digest(canonical(request)) == op["expected_request_sha256"],
                "Cancellation target changed; refetch and request new authorization")
        request.update(status="cancelled", cancelled_at=now, cancellation=copy.deepcopy(op))
        return {"status": "intake_cancelled", "request_id": request_id,
                "expected_items": request["expected_items"], "cancelled_at": now, "checkpoint_advanced": False}
    if kind == "finalize":
        request_id, request = active_request(state, op)
        require(request.get("corrects_record_id") is None, "Use correct for a correction intake")
        items = op.get("items")
        require(isinstance(items, list) and len(items) == request["expected_items"], "Finalized item count differs from intake")
        refs, duplicates = [], []
        for item in items:
            require(isinstance(item, dict), "Each finalized item must be an object")
            block = validate_block(item.get("block"), policy, request["mode"], item.get("image_verified"))
            # Separate accepted submissions are editorial content, not retries.
            # Only request/operation identity provides retry idempotence.
            duplicate = None if policy.get("preserve_separate_submissions", False) else find_duplicate(state, block)
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
        if policy.get("preserve_separate_submissions", False):
            # Mapping a new submission to another request's record suppresses
            # content. It is never an automatic duplicate-recovery shortcut.
            require(op.get("reconciliation_reason") == "user_authorized_mapping",
                    "Separate submissions cannot be automatically reconciled as duplicates")
            sha(op.get("authorization_sha256"), "explicit reconciliation authorization")
        request.update(status="reconciled", finalized_at=now,
                       records=[reference(lookup(state, rid)) for rid in record_ids],
                       evidence_sha256=sha(op.get("evidence_sha256")))
        if policy.get("preserve_separate_submissions", False):
            request["reconciliation_authorization_sha256"] = op["authorization_sha256"]
            request["reconciliation_reason"] = op["reconciliation_reason"]
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
        require(policy.get("preserve_separate_submissions", False) or not duplicate
                or (duplicate["id"] == record["id"] and not duplicate["superseded"]),
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
                    for key in ("eligibility_at", "deferred_request_ids"):
                        if key in batch:
                            state["replacement_batch"][key] = copy.deepcopy(batch[key])
                    state["pending_batch_id"] = None
        request.update(status="finalized", finalized_at=now, records=[reference(record)])
        return {"status": "corrected", "record": reference(record)}
    if kind == "review_record":
        record = lookup(state, op.get("record_id"))
        assert_unfrozen(state, record)
        require(op.get("expected_reference") == reference(record), "Review target changed; refetch revision")
        request = origin_request(state, record)
        editorial = validate_editorial(op.get("editorial"), revision(record), request, policy,
                                      state.get("url_rejections", []), now,
                                      require_quality=policy.get("compilation_quality_gate", True)
                                      or "quality" in (op.get("editorial") or {}))
        key = str(record["id"]) + ":" + str(len(record["revisions"]))
        audit = {"reference": reference(record), "editorial": copy.deepcopy(editorial),
                 "sha256": digest(canonical(editorial)), "reviewed_at": now, "operation_id": op["operation_id"]}
        state.setdefault("editorial_reviews", {}).setdefault(key, []).append(audit)
        return {"status": "editorial_reviewed", "record": reference(record), "editorial_sha256": audit["sha256"]}
    if kind == "reject_url":
        url = op.get("url")
        host(url)
        require(op.get("field") in {"article", "image", "both"} and op.get("scope") in {"url", "host"}, "Invalid rejection scope")
        require(op.get("environment") in {"chase", "available_environment", "editorial"}, "Invalid rejection environment")
        require(op.get("reason") in {"user_reported_block", "observed_block", "not_same_event", "irrelevant_image", "low_resolution", "not_image", "unstable_url"}, "Invalid rejection reason")
        require(op["scope"] != "host" or op["reason"] in {"user_reported_block", "observed_block"},
                "A bad image or wrong story cannot justify blocking a whole host")
        evidence = sha(op.get("evidence_sha256"))
        rule = {key: op[key] for key in ("url", "field", "scope", "environment", "reason")}
        rule.update(rejection_id=op["operation_id"], created_at=now, evidence_sha256=evidence)
        if "evidence_kind" in op:
            require(op["evidence_kind"] in {"private_message_reference", "report_content", "access_observation"}, "Invalid rejection evidence kind")
            rule["evidence_kind"] = op["evidence_kind"]
        state.setdefault("url_rejections", []).append(rule)
        return {"status": "url_rejection_recorded", "rejection_id": rule["rejection_id"]}
    if kind == "resolve_url_rejection":
        matches = [rule for rule in state.get("url_rejections", []) if rule["rejection_id"] == op.get("rejection_id")]
        require(len(matches) == 1 and not matches[0].get("resolved_at"), "No active matching rejection")
        matches[0].update(resolved_at=now, resolution_evidence_sha256=sha(op.get("evidence_sha256")))
        return {"status": "url_rejection_resolved", "rejection_id": op["rejection_id"]}
    if kind == "prepare":
        if state["pending_batch_id"]:
            batch = state["batches"][state["pending_batch_id"]]
            intake_gate(state, batch)
            return {"status": "prepared", "retry": True, "batch": copy.deepcopy(batch)}
        replacement = state.get("replacement_batch")
        selected = ([lookup(state, rid) for rid in replacement["record_ids"]] if replacement else
                    queued_records(state))
        cutoff = replacement["intake_cutoff"] if replacement else max(
            (request["received_sequence"] for request in state["requests"].values()), default=0)
        selection = replacement
        if replacement is None and op.get("eligibility_at") is not None:
            eligibility_at = timestamp(op["eligibility_at"])
            require(datetime.fromisoformat(eligibility_at) <= datetime.fromisoformat(now),
                    "Eligibility cutoff cannot be in the future")
            # Legacy batches retain their prefix rule. V2 can freeze a ready
            # subset because acknowledgments track delivered IDs independently.
            eligible = []
            for record in selected:
                if datetime.fromisoformat(revision(record)["created_at"]) > datetime.fromisoformat(eligibility_at):
                    if policy.get("export_format_version", 1) == 1:
                        break
                    continue
                eligible.append(record)
            selected = eligible
            selected_ids = {record["id"] for record in selected}
            selection = {"intake_cutoff": cutoff, "record_ids": sorted(selected_ids),
                         "eligibility_at": eligibility_at,
                         "deferred_request_ids": [key for key, request in state["requests"].items()
                             if request["status"] == "received"
                             and request.get("corrects_record_id") not in selected_ids]}
        editorial = None
        deferred_records = []
        if policy.get("export_format_version", 1) == 2 and selected:
            editorial, ready = [], []
            correction_targets = {request.get("corrects_record_id") for request in state["requests"].values()
                                  if request["status"] == "received"}
            for record in selected:
                review = review_for(state, record)
                try:
                    require(record["id"] not in correction_targets, "Unresolved correction targets this record")
                    validate_editorial(review, revision(record), origin_request(state, record),
                                       policy, state.get("url_rejections", []), now,
                                       require_quality=policy.get("compilation_quality_gate", True))
                except LedgerError as exc:
                    deferred_records.append({"id": record["id"], "reason": str(exc)})
                    continue
                ready.append(record)
                editorial.append(review)
            if replacement:
                require(not deferred_records, "Replacement editorial review incomplete; preserve frozen membership")
            selected = ready
            if selection is not None and not replacement:
                selected_ids = {record["id"] for record in selected}
                selection["record_ids"] = sorted(selected_ids)
                selection["deferred_request_ids"] = [key for key, request in state["requests"].items()
                    if request["status"] == "received" and request.get("corrects_record_id") not in selected_ids]
        intake_gate(state, selection)
        if not selected:
            return {"status": "empty", "checkpoint": state["checkpoint"], "deferred_records": deferred_records}
        refs = [reference(r) for r in selected]
        batch_id = digest(canonical({"checkpoint": state["checkpoint"], "records": refs}))[:24]
        require(batch_id not in state["batches"], "Batch identity already exists")
        entries = [revision(r) for r in selected]
        txt, js = render_txt(entries, editorial), encoded(github_items(entries, now[:10], editorial))
        base = ROOT + "batches/" + batch_id
        batch = {"batch_id": batch_id, "status": "prepared", "checkpoint_before": state["checkpoint"],
                 "prepared_at": now, "intake_cutoff": cutoff, "records": refs, "first_id": selected[0]["id"], "last_id": selected[-1]["id"],
                 "count": len(selected), "txt_path": base + ".txt", "json_path": base + ".json",
                 "txt_sha256": digest(txt), "json_sha256": digest(js), "delivery": {"status": "not_started", "attempts": []}}
        if editorial is not None:
            batch.update(format_version=2, editorial=copy.deepcopy(editorial), deferred_records=deferred_records)
        if selection:
            for key in ("eligibility_at", "deferred_request_ids"):
                if key in selection:
                    batch[key] = copy.deepcopy(selection[key])
        put_immutable(files, changes, batch["txt_path"], txt)
        put_immutable(files, changes, batch["json_path"], js)
        state["batches"][batch_id] = batch
        state["pending_batch_id"] = batch_id
        state["replacement_batch"] = None
        return {"status": "prepared", "retry": False, "batch": copy.deepcopy(batch)}
    if kind == "publish":
        batch = pending_batch(state, op)
        intake_gate(state, batch)
        frozen_conflict_gate(state, batch)
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
        frozen_conflict_gate(state, batch)
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
        checkpoint_after = state["checkpoint"]
        delivered = delivered_ids(state)
        for record in state["records"]:
            if record["id"] <= checkpoint_after:
                continue
            if record["id"] not in delivered:
                break
            checkpoint_after = record["id"]
        if batch.get("format_version", 1) == 2:
            batch["checkpoint_after"] = checkpoint_after
        state["checkpoint_history"].append({"kind": "delivery_acknowledgment", "before": state["checkpoint"],
                                            "checkpoint": checkpoint_after, "at": now,
                                            "batch_id": batch["batch_id"], "receipt": safe_receipt})
        state["checkpoint"] = checkpoint_after
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
    required_policy = {"summary_max_words", "forbidden_url_domains", "forbidden_url_suffixes", "forbidden_image_domains"}
    require(required_policy <= set(policy) <= required_policy | {"export_format_version", "min_image_width", "min_image_height", "quality_max_age_hours", "preserve_separate_submissions", "compilation_quality_gate"},
            "Invalid policy shape")
    require(integer(policy["summary_max_words"], 1) and all(isinstance(policy[key], list) and all(
        isinstance(v, str) and v for v in policy[key]) for key in required_policy - {"summary_max_words"}), "Invalid policy")
    require(policy.get("export_format_version", 1) in {1, 2}, "Invalid export format version")
    require(type(policy.get("preserve_separate_submissions", False)) is bool, "Invalid submission policy")
    require(type(policy.get("compilation_quality_gate", True)) is bool, "Invalid compilation quality policy")
    for key in ("min_image_width", "min_image_height", "quality_max_age_hours"):
        require(integer(policy.get(key, 1), 1), "Invalid quality policy")
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
                               for r in queued_records(state)]
        return {"base_sha": head, "changes": [], "result": result, "committed": False, "ready_to_send": False}
    require(LEDGER in files or kind in {"initialize", "import_archive"}, "Initialize or import the ledger first")
    op_id = opaque(operation.get("operation_id"), "operation ID")
    op_hash = digest(canonical(operation))
    if op_id in state["operations"]:
        prior = state["operations"][op_id]
        require(prior["sha256"] == op_hash, "Operation ID reused for a different operation")
        return {"base_sha": head, "changes": [], "result": {"status": "operation_replayed", "original_result": prior["result"],
                      "current_state": result_status(state)}, "replayed": True,
                "committed": True, "operation_id": op_id, "send_authorized": False, "ready_to_send": False,
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
            "send_authorized": False, "ready_to_send": False,
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
        sys.stdout.write(encoded({"status": "error", "saved": False, "ready_to_send": False, "checkpoint_advanced": False,
                                 "error": str(exc)}))
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
