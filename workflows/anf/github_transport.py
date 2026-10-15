"""Authenticated GitHub Git Data transport; no Contents API, shell, or send path."""
from __future__ import annotations

import base64
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, build_opener, HTTPRedirectHandler

import ledger_engine as e


class TransportError(RuntimeError):
    def __init__(self, message, *, status=None, headers=None, uncertain=False):
        super().__init__(message)
        self.status = status
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}
        self.uncertain = uncertain


class Conflict(TransportError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward credentials to an API-supplied or issue-supplied host.
        return None


def git_blob_sha(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def retry_delay(error, attempt, now=None):
    """Respect server lower bounds. Long waits are deferred, never capped shorter."""
    h = error.headers
    now = time.time() if now is None else now
    lower = 0.0
    if h.get("retry-after"):
        try:
            lower = float(h["retry-after"])
        except ValueError:
            lower = parsedate_to_datetime(h["retry-after"]).timestamp() - now
    if h.get("x-ratelimit-remaining") == "0" and h.get("x-ratelimit-reset"):
        lower = max(lower, float(h["x-ratelimit-reset"]) - now + 1)
    return max(lower, min(2 ** attempt, 16), 0)


class GitHub:
    def __init__(self, repository, token=None, *, sleep=time.sleep, opener=None):
        e.require(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository), "Invalid repository")
        self.repository, self.token, self.sleep = repository, token, sleep
        self.opener = opener or build_opener(NoRedirect())
        self.prefix = "/repos/" + repository
        self.blobs = {}  # Expendable, verified, content-addressed; never a branch snapshot.

    def request(self, method, path, data=None):
        e.require(path.startswith(self.prefix + "/") or path == "/graphql", "API route outside repository")
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
                   "User-Agent": "anf-deterministic-executor", "Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        raw = None if data is None else json.dumps(data).encode()
        # Only reads retry here. Every uncertain mutation goes back to branch
        # reconciliation before a new plan/object/ref update is attempted.
        for attempt in range(4):
            try:
                with self.opener.open(Request("https://api.github.com" + path, data=raw,
                                              headers=headers, method=method), timeout=30) as response:
                    return json.load(response)
            except HTTPError as exc:
                err = TransportError(f"GitHub HTTP {exc.code} on {method} {path.split('?')[0]}",
                                     status=exc.code, headers=dict(exc.headers), uncertain=method != "GET")
                throttled = exc.code == 429 or (exc.code == 403 and (
                    err.headers.get("retry-after") or err.headers.get("x-ratelimit-remaining") == "0"))
                if method != "GET" or not (throttled or exc.code >= 500) or attempt == 3:
                    raise err from exc
                delay = retry_delay(err, attempt)
                if delay > 30:
                    raise err from exc
                self.sleep(delay)
            except (URLError, OSError, HTTPException, ValueError) as exc:
                raise TransportError("GitHub response unavailable or invalid", uncertain=method != "GET") from exc

    def api(self, method, suffix, data=None):
        return self.request(method, self.prefix + suffix, data)

    def head(self, branch):
        result = self.api("GET", "/git/ref/heads/" + quote(branch, safe=""))
        e.require(result["object"]["type"] == "commit", "Branch does not reference a commit")
        return result["object"]["sha"]

    def tree(self, head):
        commit = self.api("GET", "/git/commits/" + head)
        e.require(commit["sha"] == head, "Commit identity mismatch")
        root = commit["tree"]["sha"]
        listing = self.api("GET", "/git/trees/" + root + "?recursive=1")
        e.require(listing["sha"] == root, "Tree identity mismatch")
        if listing.get("truncated") is False:
            return root, listing["tree"]
        # Recursive endpoint is size-limited. Walk immutable non-recursive trees.
        entries = []
        def walk(sha, prefix="", depth=0):
            e.require(depth < 100, "Tree depth limit")
            node = self.api("GET", "/git/trees/" + sha)
            e.require(node.get("sha") == sha and node.get("truncated") is False,
                      "Incomplete Git tree; refuse snapshot")
            for item in node["tree"]:
                path = prefix + item["path"]
                e.require("/" not in item["path"] and item["path"] not in {".", ".."}, "Invalid tree path")
                entries.append({**item, "path": path})
                if item["type"] == "tree":
                    walk(item["sha"], path + "/", depth + 1)
        walk(root)
        return root, entries

    def blob(self, sha, size):
        if (sha, size) in self.blobs:
            return self.blobs[sha, size]
        blob = self.api("GET", "/git/blobs/" + sha)
        e.require(blob.get("sha") == sha and blob.get("encoding") == "base64", "Invalid encoded blob")
        raw = base64.b64decode("".join(blob.get("content", "").split()), validate=True)
        e.require(len(raw) == size == blob.get("size") and git_blob_sha(raw) == sha,
                  "Empty, truncated or altered blob; refuse snapshot")
        self.blobs[sha, size] = raw.decode("utf-8")
        return self.blobs[sha, size]

    def snapshot(self, branch, *, head=None):
        head = head or self.head(branch)
        tree, entries = self.tree(head)
        files = {}
        for item in entries:
            path = item["path"]
            if path.startswith(e.ROOT) or (path.startswith("items/") and path.endswith(".json")):
                if item["type"] == "tree":
                    continue
                e.require(item["type"] == "blob" and item["mode"] in {"100644", "100755"},
                          "Unsupported file type in authoritative snapshot")
                e.require(path not in files and not any(p in {"", ".", ".."} for p in path.split("/")),
                          "Duplicate or invalid snapshot path")
                files[path] = self.blob(item["sha"], item["size"])
        e.require({e.LEDGER, e.POLICY, e.CONFIG} <= files.keys(), "Mandatory snapshot paths missing")
        snap = {"head": head, "complete": True, "files": files}
        e.plan(snap, {"kind": "status"})
        return snap, tree

    def fresh(self, branch):
        for _ in range(3):
            snap, tree = self.snapshot(branch)
            if self.head(branch) == snap["head"]:
                return snap, tree
        raise Conflict("Branch moved during readback; no output released")

    def verify_applied(self, branch, snapshot, path, row):
        """Locate the reachable atomic commit, not merely an operation-shaped row.

        Query is pinned to current HEAD. It also recovers the candidate SHA when
        the PATCH response (or the whole runner) was lost. A journal path has few
        transitions; pagination avoids assuming a first-page history is complete.
        """
        for page in range(1, 11):
            commits = self.api("GET", "/commits?sha=" + snapshot["head"] + "&path=" + quote(path, safe="")
                               + f"&per_page=100&page={page}")
            for commit in commits:
                if [p["sha"] for p in commit["parents"]] != [row["planned_from_head"]]:
                    continue
                exact, _ = self.snapshot(branch, head=commit["sha"])
                e.require(exact["files"].get(path) == snapshot["files"][path], "Journal commit readback mismatch")
                e.require(all(e.digest(exact["files"].get(p, "")) == digest
                              for p, digest in row["changed_sha256"].items()), "Changed-file readback mismatch")
                return commit["sha"]
            if len(commits) < 100:
                break
        raise TransportError("Reachable atomic commit not found; reconciliation required")

    def commit(self, branch, snapshot, tree, changes, message):
        """One parent + non-force FF provides CAS against competing siblings."""
        base = snapshot["head"]
        if self.head(branch) != base:
            raise Conflict("Expected parent changed")
        elements = []
        for path, content in sorted(changes.items()):
            raw = content.encode("utf-8")
            blob = self.api("POST", "/git/blobs", {"content": base64.b64encode(raw).decode(), "encoding": "base64"})
            e.require(blob["sha"] == git_blob_sha(raw), "Created blob hash mismatch")
            elements.append({"path": path, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        created = self.api("POST", "/git/trees", {"base_tree": tree, "tree": elements})
        candidate = self.api("POST", "/git/commits", {"message": message, "tree": created["sha"], "parents": [base]})
        e.require([p["sha"] for p in candidate["parents"]] == [base], "Candidate parent mismatch")
        # Verify full candidate state and exact changed bytes before touching ref.
        check, _ = self.snapshot(branch, head=candidate["sha"])
        e.require(all(check["files"].get(p) == c for p, c in changes.items()), "Candidate readback mismatch")
        if self.head(branch) != base:
            raise Conflict("Expected parent changed after object creation")
        try:
            self.api("PATCH", "/git/refs/heads/" + quote(branch, safe=""),
                     {"sha": candidate["sha"], "force": False})
        except TransportError as exc:
            if exc.status in {409, 422}:
                raise Conflict("Non-force ref update rejected", status=exc.status) from exc
            raise
        return candidate["sha"]

    def issues(self):
        # Reconcile ALL states from the start; no cache or event-only watermark.
        # Created ascending means newly opened issues append rather than shift pages.
        page = 1
        while True:
            rows = self.api("GET", f"/issues?state=all&sort=created&direction=asc&per_page=100&page={page}")
            e.require(isinstance(rows, list), "Invalid issues page")
            yield from (r for r in rows if "pull_request" not in r)
            if len(rows) < 100:
                return
            page += 1

    def authenticated_issue(self, number, allowed_ids):
        issue = self.api("GET", f"/issues/{number}")
        e.require("pull_request" not in issue and issue["user"]["type"] == "User"
                  and issue["user"]["id"] in allowed_ids, "Submitter is not allowlisted")
        login = issue["user"]["login"]
        permission = self.api("GET", "/collaborators/" + quote(login, safe="") + "/permission")
        e.require(permission.get("permission") in {"admin", "maintain", "write"}, "Submitter lacks write permission")
        owner, name = self.repository.split("/")
        value = self.request("POST", "/graphql", {"query": "query($owner:String!,$name:String!,$number:Int!){repository(owner:$owner,name:$name){issue(number:$number){id body lastEditedAt author{login}}}}",
            "variables": {"owner": owner, "name": name, "number": number}})
        e.require(not value.get("errors"), "Issue edit provenance unavailable")
        node = value["data"]["repository"]["issue"]
        # Another writer can edit an owner's issue. Never trust original author
        # alone. Edits require a new issue, retaining the same operation identity.
        e.require(node["lastEditedAt"] is None and node["id"] == issue["node_id"]
                  and node["body"] == issue["body"] and node["author"]["login"] == login,
                  "Edited or inconsistent issue; submit an unedited replacement")
        return issue
