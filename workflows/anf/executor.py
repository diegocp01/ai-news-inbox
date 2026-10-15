#!/usr/bin/env python3
"""Durable issue-to-ANF executor. Dot researches/edits; this process commits.

Jobs contain data, never code, paths, credentials, shell commands or prompts.
Git is the job journal and queue. Actions concurrency only reduces contention.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import ledger_engine as e
import intake_output_gate as gate
from github_transport import GitHub, TransportError, Conflict, retry_delay

CONFIG = Path(__file__).with_name("executor_config.json")
JOBS = e.ROOT + "executor-jobs/"
TITLE = "[ANF job v1]"
MAX_JOB_BYTES = 24000
COMMON = {"kind", "operation_id", "at"}
READ_ONLY = {"status", "preview", "job_status"}
# Required fields, optional fields. Nested semantic validation remains in engine.
FIELDS = {
    "status": (set(), set()), "preview": (set(), set()),
    "job_status": ({"issue_number"}, set()),
    "receive": ({"request_id", "expected_items"}, {"mode", "corrects_record_id", "origin",
        "trusted_route_sha256", "image_review_deferral_evidence_sha256"}),
    "finalize": ({"request_id", "items"}, set()),
    "correct": ({"request_id", "record_id", "block"}, {"source", "image_verified"}),
    "review_record": ({"record_id", "expected_reference", "editorial"}, set()),
    "prepare": ({"eligibility_at"}, set()), "publish": ({"batch_id"}, set()),
    "reject_url": ({"url", "field", "scope", "environment", "reason", "evidence_sha256"}, {"evidence_kind"}),
    "resolve_url_rejection": ({"rejection_id", "evidence_sha256"}, set()),
    "cancel_intake": ({"request_id", "reason_code", "authorization_sha256", "expected_request_sha256"}, set()),
    "reconcile_intake": ({"request_id", "record_ids", "evidence_sha256", "reconciliation_reason", "authorization_sha256"}, set()),
}


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def strict_json(text):
    def pairs(values):
        result = {}
        for key, value in values:
            e.require(key not in result, "Duplicate JSON key")
            result[key] = value
        return result
    def invalid(value):
        raise e.LedgerError("Non-finite JSON number")
    return json.loads(text, object_pairs_hook=pairs, parse_constant=invalid)


def validate_job(body, config):
    e.require(isinstance(body, str) and 0 < len(body.encode()) <= MAX_JOB_BYTES,
              "Job exceeds 24,000 bytes; submit small operations, never truncated plans")
    job = strict_json(body)
    e.require(isinstance(job, dict) and set(job) == {"version", "job_id", "operation"}
              and type(job["version"]) is int and job["version"] == 1, "Invalid job envelope")
    e.opaque(job["job_id"], "job ID")
    op = job["operation"]
    e.require(isinstance(op, dict) and isinstance(op.get("kind"), str) and op["kind"] in FIELDS,
              "Operation not allowed; delivery requires an authenticated native receipt adapter")
    kind = op["kind"]
    required, optional = FIELDS[kind]
    common = {"kind"} if kind in READ_ONLY else COMMON
    e.require(required | common <= op.keys() <= required | optional | common, "Unknown or missing operation fields")
    if kind not in READ_ONLY:
        e.opaque(op["operation_id"], "operation ID")
        e.timestamp(op["at"])
        e.require(datetime.fromisoformat(e.timestamp(op["at"])) <= datetime.now(timezone.utc), "Future operation")
    if "request_id" in op:
        e.opaque(op["request_id"], "request ID")
    if kind == "job_status":
        e.require(e.integer(op["issue_number"], 1), "Invalid status target issue")
    if kind == "receive":
        e.require(e.integer(op["expected_items"], 1) and op["expected_items"] <= 20, "Small jobs allow 1–20 items")
    if kind == "finalize":
        e.require(isinstance(op["items"], list) and 1 <= len(op["items"]) <= 20, "Invalid items")
        for item in op["items"]:
            e.require(isinstance(item, dict) and {"block"} <= item.keys() <= {"block", "source", "image_verified"},
                      "Invalid finalized item fields")
            e.require(isinstance(item["block"], str), "Block must be text")
            if "image_verified" in item:
                e.require(type(item["image_verified"]) is bool, "Image assertion must be boolean")
    if kind == "prepare":
        e.timestamp(op["eligibility_at"])
    # A digest supplied IN an issue cannot authenticate privilege or approval.
    privileged = kind in {"cancel_intake", "reconcile_intake"} or (
        kind == "receive" and (op.get("mode", "standard") != "standard" or "origin" in op)) or (
        kind == "review_record" and isinstance(op.get("editorial"), dict) and "origin" in op["editorial"])
    if privileged:
        e.require(e.digest(e.canonical(op)) in config["authorized_operation_sha256"],
                  "Operation needs independently verified authorization in trusted executor config")
    return job


def validate_config(config):
    e.require(set(config) == {"enabled", "repository", "branch", "submitter_ids", "authorized_operation_sha256",
                            "production_cutover_sha256", "max_jobs_per_run"}, "Invalid executor configuration")
    e.require(type(config["enabled"]) is bool and e.integer(config["max_jobs_per_run"], 1)
              and config["max_jobs_per_run"] <= 50, "Invalid executor bounds")
    e.require(isinstance(config["submitter_ids"], list) and config["submitter_ids"]
              and all(e.integer(x, 1) for x in config["submitter_ids"]), "Invalid submitter allowlist")
    e.require(config["repository"] == gate.REPOSITORY, "Unapproved executor repository")
    e.require(config["branch"] == "main" or re.fullmatch(r"anf-executor-sandbox(?:-[a-z0-9-]+)?", config["branch"]),
              "Executor target must be main or an isolated sandbox")
    for digest in config["authorized_operation_sha256"]:
        e.sha(digest)
    if config["branch"] == "main":
        e.sha(config["production_cutover_sha256"], "new executor cutover confirmation")
        e.require(config["production_cutover_sha256"] != "0" * 64, "Missing new writer cutover")
    return config


def job_path(number):
    e.require(e.integer(number, 1), "Invalid issue number")
    return JOBS + str(number) + ".json"


class Executor:
    def __init__(self, github, config):
        self.gh, self.config = github, validate_config(config)
        e.require(config["enabled"] is True, "Executor disabled; separate deployment/cutover approval required")
        e.require(github.repository == config["repository"], "Transport/config repository mismatch")
        self.branch = config["branch"]

    def transaction(self, build, marker):
        """Re-read branch FIRST on every retry, including ambiguous ref replies.

        Marker detects the atomic journal+ledger write after process death. An
        unreachable commit is never accepted as evidence of successful execution.
        """
        for attempt in range(4):
            snap, tree = self.gh.fresh(self.branch)
            if marker(snap):
                return snap
            changes = build(snap)
            if not changes:
                return snap
            try:
                candidate = self.gh.commit(self.branch, snap, tree, changes, "ANF executor durable transition")
                committed, _ = self.gh.snapshot(self.branch, head=candidate)
                e.require(all(committed["files"].get(p) == c for p, c in changes.items()), "Exact commit readback failed")
                current, _ = self.gh.fresh(self.branch)
                e.require(marker(current), "Commit not present on current branch; reconcile before retry")
                return current
            except TransportError as exc:
                throttled = exc.status == 429 or (exc.status == 403 and (
                    exc.headers.get("retry-after") or exc.headers.get("x-ratelimit-remaining") == "0"))
                delay = retry_delay(exc, attempt)
                if throttled:
                    if delay > 30:
                        raise TransportError("Retry deferred until server backoff expires", headers=exc.headers) from exc
                    self.gh.sleep(delay)
                # Reconcile before any mutation retry, but respect a server's
                # throttle before even a read. Never switch identity on denial.
                current, _ = self.gh.fresh(self.branch)
                if marker(current):
                    return current
                retryable = isinstance(exc, Conflict) or exc.status is None or throttled or (exc.status >= 500)
                if not retryable or attempt == 3:
                    raise
                if delay > 30:
                    raise TransportError("Retry deferred until server backoff expires", headers=exc.headers) from exc
                if not throttled:
                    self.gh.sleep(delay)
        raise TransportError("Retry budget exhausted")

    def ingest(self, number):
        issue = self.gh.authenticated_issue(number, self.config["submitter_ids"])
        e.require(issue["title"].startswith(TITLE), "Not an ANF job issue")
        job = validate_job(issue["body"], self.config)
        path = job_path(number)
        row = {"schema": 1, "issue_number": number, "issue_node_id": issue["node_id"],
               "submitter_id": issue["user"]["id"], "submitted_at": issue["created_at"],
               "body_sha256": e.digest(issue["body"]), "job": job, "status": "received"}
        def marker(snap):
            if path not in snap["files"]:
                return False
            saved = strict_json(snap["files"][path])
            e.require(all(saved.get(k) == v for k, v in row.items() if k != "status"), "Immutable job identity conflict")
            return True
        def build(snap):
            # Stable job identity may be retried via another pristine issue, but
            # cannot be rebound to a different operation body.
            for p, text in snap["files"].items():
                if p.startswith(JOBS):
                    other = strict_json(text)
                    if other["job"]["job_id"] == job["job_id"]:
                        e.require(other["job"] == job, "Job ID reused with different payload")
            return {path: e.encoded(row)}
        return self.transaction(build, marker)

    def apply(self, number):
        path = job_path(number)
        def marker(snap):
            return strict_json(snap["files"][path])["status"] == "applied"
        def build(snap):
            row = strict_json(snap["files"][path])
            # Recheck revocation and issue provenance before applying frozen data.
            issue = self.gh.authenticated_issue(number, self.config["submitter_ids"])
            e.require(issue["node_id"] == row["issue_node_id"] and e.digest(issue["body"]) == row["body_sha256"],
                      "Issue changed after durable receipt")
            job = validate_job(e.canonical(row["job"]), self.config)
            op = job["operation"]
            if op["kind"] == "job_status":
                target = strict_json(snap["files"][job_path(op["issue_number"])])
                e.require(target["job"]["operation"]["kind"] != "job_status", "Status requests cannot chain")
                plan = {"base_sha": snap["head"], "changes": [],
                        "result": {"status": "job_status_requested", "issue_number": op["issue_number"]}}
            else:
                plan = e.plan(snap, op)
            e.require(plan["base_sha"] == snap["head"], "Planner parent mismatch")
            changes = {entry["path"]: entry["content"] for entry in plan["changes"]}
            e.require(len(changes) == len(plan["changes"]), "Duplicate plan paths")
            for p, content in changes.items():
                e.require(p == e.LEDGER or re.fullmatch(r"workflows/anf/batches/[0-9a-f]{24}\.(txt|json)", p)
                          or re.fullmatch(r"items/\d{4}-\d{2}-\d{2}(?:-\d+)?\.json", p), "Forbidden plan path")
                e.require(p == e.LEDGER or p not in snap["files"] or snap["files"][p] == content, "Immutable artifact overwrite")
            row.update(status="applied", applied_at=utcnow(), planned_from_head=snap["head"],
                       operation_sha256=e.digest(e.canonical(job["operation"])), result=plan["result"],
                       changed_sha256={p: e.digest(c) for p, c in changes.items()})
            row.pop("blocker", None)
            changes[path] = e.encoded(row)
            return changes
        self.transaction(build, marker)
        return self.status(number)

    def status(self, number):
        snap, _ = self.gh.fresh(self.branch)
        path = job_path(number)
        e.require(path in snap["files"], "Job not durably received")
        row = strict_json(snap["files"][path])
        op = row["job"]["operation"]
        result = {"status": row["status"], "issue_number": number, "job_id": row["job"]["job_id"],
                  "verified_head": snap["head"], "observed_at": utcnow(),
                  "snapshot_sha256": e.digest(e.canonical(snap)), "journal_path": path,
                  "journal_sha256": e.digest(snap["files"][path]), "ready_to_send": False,
                  "attachment_delivery_authorized": False, "ledger": e.plan(snap, {"kind": "status"})["result"]}
        if row["status"] == "applied":
            result["applied_commit"] = self.gh.verify_applied(self.branch, snap, path, row)
            if op["kind"] not in READ_ONLY:
                persisted = strict_json(snap["files"][e.LEDGER])["operations"].get(op["operation_id"])
                e.require(persisted and persisted["sha256"] == e.digest(e.canonical(op)), "Applied operation missing from branch")
            result["result"] = row["result"]
            if op["kind"] == "job_status":
                target = strict_json(snap["files"][job_path(op["issue_number"])])
                e.require(target["job"]["operation"]["kind"] != "job_status", "Status requests cannot chain")
                result["job_status"] = self.status(op["issue_number"])
            if op["kind"] in {"finalize", "correct"}:
                if self.branch == "main":
                    observation = {k: result[k] for k in ("observed_at", "snapshot_sha256")}
                    observation.update(repository=self.gh.repository, branch=self.branch, head=snap["head"])
                    result["intake_output"] = gate.verify_intake_output(snap, op, observation)
                else:
                    result["output_blocker"] = "Sandbox results never authorize a production intake response"
        if "blocker" in row:
            result["blocker"] = row["blocker"]
        return result

    def blocked(self, number, error):
        path = job_path(number)
        # Do not expose arbitrary issue text or API response bodies in errors.
        reason = str(error)[:1000]
        observed_at = utcnow()
        def marker(snap):
            row = strict_json(snap["files"][path])
            return row["status"] == "applied" or row.get("blocker", {}).get("observed_at") == observed_at
        def build(snap):
            row = strict_json(snap["files"][path])
            row.update(status="blocked", blocker={"reason": reason, "observed_at": observed_at,
                       "observed_head": snap["head"], "retry": "Reconcile same operation; never infer cancellation"})
            return {path: e.encoded(row)}
        self.transaction(build, marker)

    def reconcile(self):
        outcomes = []
        # Discover missing runs. Persist every accepted job before processing.
        # A bounded pass can be resumed by schedule/manual wakeup without a cache.
        snap, _ = self.gh.fresh(self.branch)
        known = {int(p[len(JOBS):-5]) for p in snap["files"] if p.startswith(JOBS) and p.endswith(".json")}
        count = 0
        for issue in self.gh.issues():
            if not issue["title"].startswith(TITLE) or issue["number"] in known:
                continue
            if count >= self.config["max_jobs_per_run"]:
                break
            try:
                self.ingest(issue["number"])
                count += 1
            except (e.LedgerError, ValueError, TypeError, KeyError) as exc:
                outcomes.append({"issue_number": issue["number"], "status": "rejected", "reason": str(exc)[:1000]})
        snap, _ = self.gh.fresh(self.branch)
        rows = [strict_json(text) for p, text in snap["files"].items() if p.startswith(JOBS)]
        pending = sorted((row for row in rows if row["status"] != "applied"),
                         key=lambda r: (r.get("blocker", {}).get("observed_at", ""), r["issue_number"]))
        for row in pending[:self.config["max_jobs_per_run"]]:
            number = row["issue_number"]
            try:
                outcomes.append(self.apply(number))
            except (e.LedgerError, TransportError, ValueError, KeyError, TypeError) as exc:
                # Applied but output-gate blocked is different from failed save.
                if isinstance(exc, TransportError):
                    raise  # No extra write on a denial, outage, or server backoff.
                self.blocked(number, exc)
                outcomes.append({"issue_number": number, "status": "needs_attention", "reason": str(exc)[:1000],
                                 "ready_to_send": False, "journal_path": job_path(number)})
        return {"status": "reconciled", "outcomes": outcomes,
                "remaining_jobs": max(0, len(pending) - self.config["max_jobs_per_run"]),
                "attachment_delivery_authorized": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status-issue", type=int)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    def emit(result):
        output = e.encoded(result)
        if args.output:
            temporary = args.output.with_suffix(args.output.suffix + ".tmp")
            temporary.write_text(output)
            temporary.replace(args.output)
        else:
            sys.stdout.write(output)
    # Invalidate stale success before network I/O, including cancellation/crash.
    if args.output:
        emit({"status": "running_unverified", "ready_to_send": False})
    code = 0
    try:
        config = validate_config(strict_json(CONFIG.read_text()))
        token = os.environ.get("GITHUB_TOKEN")
        e.require(bool(token), "An authorized runner GITHUB_TOKEN is required; ChatGPT credentials are not inherited")
        runner = Executor(GitHub(config["repository"], token), config)
        result = runner.status(args.status_issue) if args.status_issue else runner.reconcile()
    except (e.LedgerError, TransportError, OSError, ValueError, KeyError, TypeError, RecursionError) as exc:
        result = {"status": "executor_blocked", "ready_to_send": False, "error": str(exc)[:1000]}
        code = 1
    emit(result)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
