"""Incident acceptance tests. Synthetic Git Data service, real transport code.

Live connector evidence is recorded separately in docs/EXECUTOR-VALIDATION.md.
No fixture reads or mutates the production ledger and no sender exists here.
"""
import base64
import copy
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, unquote, urlsplit

from test_ledger_engine import Repository, ROOT, T, HASH, block, e
from test_editorial_quality import review

sys.path.insert(0, str(ROOT))
sys.modules["ledger_engine"] = e
import executor as x
import github_transport as g


def sha(value):
    return hashlib.sha1(e.canonical(value).encode()).hexdigest()


class Service(g.GitHub):
    """Emulate only GitHub responses; production snapshot/commit/retry code runs."""
    def __init__(self, fixture=None):
        super().__init__("diegocp01/ai-news-inbox", "synthetic", sleep=lambda n: self.waits.append(n))
        self.fixture = fixture or Repository().initialize()
        self.fixture.files[e.POLICY] = (ROOT / "policy.json").read_text()
        self.objects, self.trees, self.commits, self.issue_rows = {}, {}, {}, {}
        self.calls, self.waits = [], []
        self.fault = None
        self.before_patch = None
        self.current = self.seed(self.fixture.files)

    def seed(self, files, parent=None):
        entries = {}
        for path, text in files.items():
            raw = text.encode()
            bid = g.git_blob_sha(raw)
            self.objects[bid] = {"sha": bid, "size": len(raw), "encoding": "base64",
                                 "content": base64.b64encode(raw).decode()}
            entries[path] = {"path": path, "sha": bid, "mode": "100644", "type": "blob", "size": len(raw)}
        tid = sha(entries)
        self.trees[tid] = entries
        cid = sha([tid, parent])
        self.commits[cid] = {"sha": cid, "tree": {"sha": tid}, "parents": [{"sha": parent}] if parent else []}
        return cid

    def api(self, method, suffix, data=None):
        self.calls.append((method, suffix, copy.deepcopy(data)))
        url = urlsplit(suffix)
        path, query = unquote(url.path), parse_qs(url.query)
        if path.startswith("/git/ref/heads/"):
            return {"object": {"type": "commit", "sha": self.current}}
        if path.startswith("/git/blobs/"):
            return copy.deepcopy(self.objects[path.rsplit("/", 1)[1]])
        if path.startswith("/git/trees/"):
            tid = path.rsplit("/", 1)[1]
            return {"sha": tid, "truncated": False, "tree": list(self.trees[tid].values())}
        if path.startswith("/git/commits/"):
            return self.commits[path.rsplit("/", 1)[1]]
        if path == "/git/blobs":
            raw = base64.b64decode(data["content"])
            bid = g.git_blob_sha(raw)
            self.objects[bid] = {**data, "sha": bid, "size": len(raw)}
            return {"sha": bid}
        if path == "/git/trees":
            self.assert_tree_fields(data)
            entries = copy.deepcopy(self.trees[data["base_tree"]])
            for entry in data["tree"]:
                entries[entry["path"]] = {**entry, "size": self.objects[entry["sha"]]["size"]}
            tid = sha(entries)
            self.trees[tid] = entries
            return {"sha": tid}
        if path == "/git/commits":
            cid = sha(data)
            value = {"sha": cid, "tree": {"sha": data["tree"]}, "parents": [{"sha": p} for p in data["parents"]]}
            self.commits[cid] = value
            return value
        if path.startswith("/git/refs/heads/"):
            if self.before_patch:
                callback, self.before_patch = self.before_patch, None
                callback()
            fault, self.fault = self.fault, None
            if fault == "orphan":
                raise g.TransportError("UNKNOWN", uncertain=True)
            if fault == "cancel_before":
                raise KeyboardInterrupt()
            if fault == "denied":
                raise g.TransportError("GitHub HTTP 403", status=403)
            if fault == "throttled":
                raise g.TransportError("Rate limit", status=429, headers={"Retry-After": "120"})
            if data["force"] is not False or [p["sha"] for p in self.commits[data["sha"]]["parents"]] != [self.current]:
                raise g.TransportError("Not fast forward", status=422)
            self.current = data["sha"]
            if fault == "lost":
                raise g.TransportError("Lost accepted response", uncertain=True)
            if fault == "cancel_after":
                raise KeyboardInterrupt()
            return {"object": {"sha": self.current}}
        if path == "/commits":
            cid = query["sha"][0]
            result = []
            while cid:
                result.append(self.commits[cid])
                parents = self.commits[cid]["parents"]
                cid = parents[0]["sha"] if parents else None
            return result
        raise AssertionError((method, suffix, data))

    @staticmethod
    def assert_tree_fields(data):
        assert set(data) == {"base_tree", "tree"}, "REST fields differ from connector wrapper fields"

    def issues(self):
        return iter(copy.deepcopy(list(self.issue_rows.values())))

    def authenticated_issue(self, number, allowed_ids):
        value = self.issue_rows[number]
        e.require(value["user"]["id"] in allowed_ids and not value.get("edited"), "Unauthenticated or edited issue")
        return copy.deepcopy(value)

    def job(self, operation, number=None, job_id=None):
        number = number or len(self.issue_rows) + 1
        job = {"version": 1, "job_id": job_id or f"job_{number}", "operation": operation}
        self.issue_rows[number] = {"number": number, "node_id": f"issue_{number}", "title": x.TITLE,
            "body": e.canonical(job), "user": {"id": 154387858}, "created_at": T, "state": "open"}
        return number


class ExecutorTests(unittest.TestCase):
    def setUp(self):
        self.service = Service()
        self.config = {**json.loads(x.CONFIG.read_text()), "enabled": True}
        self.runner = x.Executor(self.service, self.config)
        self.seq = 0

    def op(self, kind, **kw):
        self.seq += 1
        return {"kind": kind, "operation_id": f"incident_{self.seq}", "at": T, **kw}

    def run_job(self, kind, **kw):
        n = self.service.job(self.op(kind, **kw))
        self.runner.ingest(n)
        return self.runner.apply(n)

    def state(self):
        return json.loads(self.service.fresh(self.runner.branch)[0]["files"][e.LEDGER])

    def test_lost_ref_response_reconciles_and_never_double_applies(self):
        n = self.service.job(self.op("receive", request_id="a", expected_items=1))
        self.runner.ingest(n)
        self.service.fault = "lost"
        result = self.runner.apply(n)
        before = self.service.current
        self.runner.apply(n)
        self.assertEqual(self.service.current, before)
        self.assertEqual(result["status"], "applied")
        self.assertEqual(list(self.state()["requests"]), ["a"])

    def test_orphan_object_is_not_success_and_is_replanned(self):
        n = self.service.job(self.op("receive", request_id="a", expected_items=1))
        self.runner.ingest(n)
        self.service.fault = "orphan"
        result = self.runner.apply(n)
        self.assertEqual(result["status"], "applied")
        self.assertEqual(len(self.service.waits), 1)
        self.assertEqual(len(self.state()["requests"]), 1)

    def test_two_writers_replan_preserving_both_operations(self):
        a = self.service.job(self.op("receive", request_id="a", expected_items=1))
        b = self.service.job(self.op("receive", request_id="b", expected_items=1))
        self.runner.ingest(a); self.runner.ingest(b)
        competitor = x.Executor(self.service, self.config)
        self.service.before_patch = lambda: competitor.apply(b)
        self.runner.apply(a)
        self.assertEqual(set(self.state()["requests"]), {"a", "b"})
        self.assertTrue(all(c[2]["force"] is False for c in self.service.calls if c[0] == "PATCH"))

    def test_restart_cancelled_before_and_after_ref_and_vanished_cache(self):
        for fault in ("cancel_before", "cancel_after"):
            with self.subTest(fault=fault):
                self.setUp()
                n = self.service.job(self.op("receive", request_id="a", expected_items=1))
                self.runner.ingest(n)
                self.service.fault = fault
                with self.assertRaises(KeyboardInterrupt):
                    self.runner.apply(n)
                self.service.blobs.clear()
                self.runner = x.Executor(self.service, self.config)
                self.runner.reconcile()
                self.assertEqual(self.runner.status(n)["status"], "applied")
                self.assertEqual(len(self.state()["requests"]), 1)

    def test_missed_runs_and_closed_issues_recovered_without_events(self):
        for i in range(3):
            n = self.service.job(self.op("receive", request_id=f"r{i}", expected_items=1))
            self.service.issue_rows[n]["state"] = "closed"
        self.runner.reconcile()
        self.assertEqual(len(self.state()["requests"]), 3)

    def test_separate_identical_story_and_same_operation_retry(self):
        for request in ("first", "second"):
            self.run_job("receive", request_id=request, expected_items=1)
            op = self.op("finalize", request_id=request, items=[{"block": block(), "image_verified": True}])
            n = self.service.job(op)
            self.runner.ingest(n); self.runner.apply(n)
            retry = self.service.job(op)
            self.runner.ingest(retry); self.runner.apply(retry)
        self.assertEqual([r["id"] for r in self.state()["records"]], [1, 2])

    def test_preview_and_review_interruption_do_not_imply_delivery(self):
        self.run_job("receive", request_id="a", expected_items=1)
        self.run_job("finalize", request_id="a", items=[{"block": block(), "image_verified": True}])
        before = self.state()
        n = self.service.job({"kind": "preview"})
        self.runner.ingest(n)
        self.service.fault = "cancel_after"
        with self.assertRaises(KeyboardInterrupt): self.runner.apply(n)
        self.assertEqual(self.state(), before)
        self.runner.reconcile()
        ed = review(block()); ed.pop("quality")
        n = self.service.job(self.op("review_record", record_id=1, expected_reference=e.reference(before["records"][0]), editorial=ed))
        self.runner.ingest(n)
        self.service.fault = "cancel_after"
        with self.assertRaises(KeyboardInterrupt): self.runner.apply(n)
        self.runner.reconcile()
        self.assertEqual(len(self.state()["editorial_reviews"]["1:1"]), 1)
        self.assertEqual(self.state()["checkpoint"], 0)

    def test_delayed_compilation_keeps_original_cutoff_and_frozen_bytes(self):
        for request, at in (("early", T), ("late", "2026-09-30T17:00:00+00:00")):
            self.run_job("receive", request_id=request, expected_items=1, at=at)
            self.run_job("finalize", request_id=request, items=[{"block": block(request), "image_verified": True}], at=at)
            record = self.state()["records"][-1]
            ed = review(block(request)); ed.pop("quality")
            self.run_job("review_record", record_id=record["id"], expected_reference=e.reference(record), editorial=ed, at=at)
        result = self.run_job("prepare", eligibility_at=T, at="2026-09-30T18:00:00+00:00")
        batch = result["result"]["batch"]
        self.assertEqual([r["id"] for r in batch["records"]], [1])
        replay = self.run_job("prepare", eligibility_at="2026-09-30T19:00:00+00:00", at="2026-09-30T19:00:00+00:00")
        self.assertEqual(replay["result"]["batch"], batch)

    def test_forged_delivery_receipts_and_imports_are_never_issue_operations(self):
        for kind in ("initialize", "import_archive", "begin_delivery", "delivery_failed", "delivery_uncertain", "reconcile_not_sent", "acknowledge"):
            n = self.service.job(self.op(kind, receipt={"accepted": True}))
            with self.assertRaisesRegex(e.LedgerError, "not allowed"): self.runner.ingest(n)
        self.assertEqual(self.state()["checkpoint"], 0)

    def test_uncertain_attachment_remains_blocking_after_restart(self):
        r = Repository().initialize(); r.add(); bid = r.published(); r.begin(bid)
        r.execute("delivery_uncertain", batch_id=bid, attempt_id="attempt_1", evidence_sha256=HASH)
        self.service = Service(r); self.runner = x.Executor(self.service, self.config)
        n = self.service.job({"kind": "status"})
        self.runner.ingest(n); self.runner.apply(n)
        self.assertEqual(self.state()["batches"][bid]["delivery"]["status"], "uncertain")
        self.assertEqual(self.state()["checkpoint"], 0)
        # Existing engine independently refuses send retries and accepts only
        # matching accepted receipts; this issue adapter deliberately cannot ack.
        with self.assertRaises(e.LedgerError): r.begin(bid, "retry")
        r.acknowledge(bid)
        self.assertEqual(r.state["checkpoint"], 1)

    def test_403_is_not_retried_or_relabelled_cas(self):
        n = self.service.job(self.op("receive", request_id="a", expected_items=1))
        self.runner.ingest(n); self.service.fault = "denied"
        with self.assertRaises(g.TransportError): self.runner.apply(n)
        self.assertEqual(self.service.waits, [])
        self.assertNotIn("a", self.state()["requests"])

    def test_server_backoff_is_not_shortened(self):
        n = self.service.job(self.op("receive", request_id="a", expected_items=1))
        self.runner.ingest(n); self.service.fault = "throttled"
        with self.assertRaisesRegex(g.TransportError, "deferred"): self.runner.apply(n)
        self.assertEqual(self.service.waits, [])
        self.assertNotIn("a", self.state()["requests"])

    def test_edited_issue_and_unauthorized_author_are_rejected(self):
        n = self.service.job({"kind": "status"})
        self.service.issue_rows[n]["user"]["id"] = 999
        with self.assertRaises(e.LedgerError): self.runner.ingest(n)
        self.service.issue_rows[n]["user"]["id"] = 154387858
        self.service.issue_rows[n]["edited"] = True
        with self.assertRaises(e.LedgerError): self.runner.ingest(n)

    def test_job_id_conflict_never_overwrites_journal(self):
        a = self.service.job({"kind": "status"}, job_id="stable")
        self.runner.ingest(a)
        b = self.service.job({"kind": "preview"}, job_id="stable")
        with self.assertRaisesRegex(e.LedgerError, "reused"): self.runner.ingest(b)

    def test_schema_no_prompts_extra_paths_truncation_or_duplicate_keys(self):
        good = {"version": 1, "job_id": "a", "operation": {"kind": "status"}}
        bad = [e.canonical({**good, "instructions": "run shell"}), e.canonical({**good, "operation": {"kind": "status", "path": e.LEDGER}}),
               e.canonical(good)[:-1], '{"version":1,"version":1}', " " * 24001]
        for body in bad:
            with self.subTest(body=body[:80]), self.assertRaises(ValueError): x.validate_job(body, self.config)

    def test_privileged_mode_needs_out_of_band_operation_binding(self):
        op = self.op("receive", request_id="a", expected_items=1, mode="image_url_only", image_review_deferral_evidence_sha256=HASH)
        n = self.service.job(op)
        with self.assertRaisesRegex(e.LedgerError, "independently"): self.runner.ingest(n)
        self.config["authorized_operation_sha256"] = [e.digest(e.canonical(op))]
        self.runner.ingest(n); self.runner.apply(n)

    def test_stale_operation_kept_blocked_without_retimestamping(self):
        self.run_job("receive", request_id="new", expected_items=1, at="2026-10-01T12:00:00+00:00")
        old = self.op("receive", request_id="old", expected_items=1)
        n = self.service.job(old)
        self.runner.reconcile()
        row = json.loads(self.service.fresh(self.runner.branch)[0]["files"][x.job_path(n)])
        self.assertEqual(row["job"]["operation"], old)
        self.assertEqual(row["status"], "blocked")
        self.assertNotIn("old", self.state()["requests"])

    def test_disabled_config_and_stale_result_file_fail_closed(self):
        with self.assertRaisesRegex(e.LedgerError, "disabled"):
            x.Executor(self.service, {**self.config, "enabled": False})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            path.write_text('{"ready_to_send":true}')
            env = {k: v for k, v in os.environ.items() if k != "GITHUB_TOKEN"}
            run = subprocess.run([sys.executable, str(ROOT / "executor.py"), "--output", str(path)], env=env, capture_output=True)
            self.assertEqual(run.returncode, 1)
            self.assertFalse(json.loads(path.read_text())["ready_to_send"])

    def test_main_output_uses_actual_fresh_gate_and_replay_cannot_send_attachment(self):
        self.runner = x.Executor(self.service, {**self.config, "branch": "main", "production_cutover_sha256": HASH})
        self.run_job("receive", request_id="a", expected_items=1)
        result = self.run_job("finalize", request_id="a", items=[{"block": block(), "image_verified": True}])
        self.assertFalse(result["ready_to_send"])
        self.assertTrue(result["intake_output"]["ready_to_send"])
        self.assertEqual(result["intake_output"]["items"][0]["block"], block())
        self.assertFalse(result["attachment_delivery_authorized"])
        target = result["issue_number"]
        n = self.service.job({"kind": "job_status", "issue_number": target})
        self.runner.ingest(n)
        recovered = self.runner.apply(n)["job_status"]
        self.assertTrue(recovered["intake_output"]["ready_to_send"])
        self.assertEqual(recovered["issue_number"], target)

    def test_blocked_jobs_rotate_and_do_not_starve_later_jobs(self):
        self.config["max_jobs_per_run"] = 1
        a = self.service.job(self.op("finalize", request_id="missing", items=[{"block": block(), "image_verified": True}]))
        self.runner.ingest(a)
        b = self.service.job(self.op("receive", request_id="independent", expected_items=1))
        self.runner.ingest(b)
        self.runner.reconcile()
        self.assertEqual(self.runner.reconcile()["remaining_jobs"], 1)
        self.assertEqual(self.runner.status(a)["status"], "blocked")
        self.assertEqual(self.runner.status(b)["status"], "applied")

    def test_reachable_commit_readback_rejects_wrong_changed_digest(self):
        n = self.service.job(self.op("receive", request_id="a", expected_items=1))
        self.runner.ingest(n); self.runner.apply(n)
        snap, _ = self.service.fresh(self.runner.branch)
        row = json.loads(snap["files"][x.job_path(n)])
        row["changed_sha256"][e.LEDGER] = "0" * 64
        # Preserve journal equality, then check the original changed-file evidence.
        with self.assertRaisesRegex(e.LedgerError, "Changed-file"):
            self.service.verify_applied(self.runner.branch, snap, x.job_path(n), row)


class TransportTests(unittest.TestCase):
    def test_large_ledger_blob_and_empty_or_truncated_encoded_response(self):
        service = Service()
        raw = (e.encoded(service.fixture.state) + " " * (1024 * 1024)).encode()
        bid = g.git_blob_sha(raw)
        service.objects[bid] = {"sha": bid, "size": len(raw), "encoding": "base64", "content": base64.b64encode(raw).decode()}
        self.assertEqual(service.blob(bid, len(raw)).encode(), raw)
        for content in ("", base64.b64encode(raw[:-1]).decode()):
            service.blobs.clear(); service.objects[bid]["content"] = content
            with self.assertRaisesRegex(e.LedgerError, "truncated"): service.blob(bid, len(raw))

    def test_missing_mandatory_path_does_not_initialize_empty_ledger(self):
        service = Service()
        files = dict(service.fixture.files); files.pop(e.LEDGER)
        service.current = service.seed(files)
        with self.assertRaisesRegex(e.LedgerError, "Mandatory"): service.fresh("sandbox")

    def test_truncated_recursive_tree_falls_back_and_truncated_subtree_blocks(self):
        client = g.GitHub("diegocp01/ai-news-inbox")
        def api(method, path, data=None):
            if path.startswith("/git/commits/"): return {"sha": "a" * 40, "tree": {"sha": "b" * 40}}
            if "recursive" in path: return {"sha": "b" * 40, "truncated": True, "tree": []}
            if path.endswith("b" * 40): return {"sha": "b" * 40, "truncated": False, "tree": [{"path": "dir", "type": "tree", "sha": "c" * 40}]}
            return {"sha": "c" * 40, "truncated": False, "tree": [{"path": "file", "type": "blob", "sha": "d" * 40}]}
        client.api = api
        self.assertEqual(client.tree("a" * 40)[1][-1]["path"], "dir/file")
        client.api = lambda *a, **k: {**api(*a, **k), "truncated": True}
        with self.assertRaisesRegex(e.LedgerError, "Incomplete"): client.tree("a" * 40)

    def test_actual_response_headers_drive_read_retry(self):
        class Opener:
            calls = 0
            def open(self, request, timeout):
                self.calls += 1
                if self.calls == 1:
                    raise HTTPError(request.full_url, 429, "limited", {"Retry-After": "7"}, io.BytesIO())
                return io.BytesIO(b'{"ok":true}')
        waits = []
        client = g.GitHub("diegocp01/ai-news-inbox", sleep=waits.append, opener=Opener())
        self.assertEqual(client.api("GET", "/issues"), {"ok": True})
        self.assertEqual(waits, [7])
        self.assertEqual(g.retry_delay(g.TransportError("limit", headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1100"}), 0, now=1000), 101)
        self.assertEqual(g.retry_delay(g.TransportError("limit", headers={"Retry-After": "Thu, 01 Jan 1970 00:18:20 GMT"}), 0, now=1000), 100)

    def test_issue_pagination_covers_closed_and_skips_prs(self):
        client = g.GitHub("diegocp01/ai-news-inbox")
        calls = []
        def api(method, path):
            calls.append(path)
            return [{"number": n} for n in range(100)] if parse_qs(urlsplit(path).query)["page"] == ["1"] else [{"number": 101}, {"pull_request": {}, "number": 102}]
        client.api = api
        self.assertEqual(len(list(client.issues())), 101)
        self.assertTrue(all("state=all" in p for p in calls))

    def test_auth_checks_numeric_id_permission_and_edit_provenance(self):
        client = g.GitHub("diegocp01/ai-news-inbox")
        issue = {"node_id": "I_1", "body": "{}", "user": {"id": 154387858, "type": "User", "login": "diegocp01"}}
        node = {"id": "I_1", "body": "{}", "lastEditedAt": None, "author": {"login": "diegocp01"}}
        permission = {"permission": "admin"}
        client.api = lambda method, path: permission if path.endswith("permission") else issue
        client.request = lambda *a, **kw: {"data": {"repository": {"issue": node}}}
        self.assertEqual(client.authenticated_issue(1, [154387858]), issue)
        node["lastEditedAt"] = T
        with self.assertRaisesRegex(e.LedgerError, "Edited"): client.authenticated_issue(1, [154387858])
        node["lastEditedAt"] = None; permission["permission"] = "read"
        with self.assertRaisesRegex(e.LedgerError, "permission"): client.authenticated_issue(1, [154387858])


if __name__ == "__main__":
    unittest.main()
