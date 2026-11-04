#!/usr/bin/env python3
"""Assemble a verified ANF snapshot from already-fetched connector responses.

Pure standard library; no network, credentials, Git writes, sends or scheduler.
The authenticated caller fetches the pinned commit, its recursive root tree by
TREE SHA, required blobs by SHA, then re-reads branch HEAD. This helper checks
the supplied observations; it cannot authenticate their origin or freshness.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = "workflows/anf/"
MANDATORY = {ROOT + name for name in ("ledger.json", "policy.json", "runtime_config.json")}


class SnapshotError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise SnapshotError(message)


def sha(value, label):
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value)
            and value != "0" * 40, "Invalid " + label + " SHA-1")
    return value


def git_hash(kind, raw):
    return hashlib.sha1(kind.encode("ascii") + b" " + str(len(raw)).encode("ascii")
                        + b"\0" + raw).hexdigest()


def utf8(value, label):
    require(isinstance(value, str), label + " must be text")
    try:
        return value.encode("utf-8")
    except UnicodeError as exc:
        raise SnapshotError(label + " is not valid UTF-8") from exc


def required_path(path):
    return path.startswith(ROOT) or (path.startswith("items/") and path.endswith(".json"))


def verified_entries(tree, root_sha):
    require(isinstance(tree, dict) and tree.get("sha") == root_sha,
            "Tree identity mismatch; fetch by the pinned commit's root tree SHA")
    require(tree.get("truncated") is False and isinstance(tree.get("tree"), list),
            "Incomplete recursive tree; refuse snapshot")
    entries, children = {}, {}
    modes = {"040000": "tree", "100644": "blob", "100755": "blob",
             "120000": "blob", "160000": "commit"}
    for entry in tree["tree"]:
        require(isinstance(entry, dict), "Invalid tree entry")
        path = entry.get("path")
        utf8(path, "Tree path")
        require("\0" not in path and "\\" not in path
                and all(part not in {"", ".", ".."} for part in path.split("/")),
                "Invalid tree path")
        require(path not in entries, "Duplicate tree path: " + path)
        require(entry.get("mode") in modes and modes[entry["mode"]] == entry.get("type"),
                "Invalid tree entry mode/type: " + path)
        sha(entry.get("sha"), "tree entry")
        if entry["type"] == "blob":
            require(type(entry.get("size")) is int and entry["size"] >= 0,
                    "Missing or invalid blob byte size: " + path)
        entries[path] = entry
        parent, _, name = path.rpartition("/")
        children.setdefault(parent, []).append((name, entry))
    for path in entries:
        parent = path.rpartition("/")[0]
        require(not parent or (parent in entries and entries[parent]["type"] == "tree"),
                "Missing directory in recursive tree: " + path)

    # Rebuild every directory object. This detects missing entries even if a
    # damaged response incorrectly says truncated=false, including outside ANF.
    directories = {"": root_sha, **{path: entry["sha"] for path, entry in entries.items()
                                    if entry["type"] == "tree"}}
    for path, expected_sha in directories.items():
        ordered = sorted(children.get(path, []), key=lambda item:
                         item[0].encode("utf-8") + (b"/" if item[1]["type"] == "tree" else b""))
        raw = b"".join(entry["mode"].lstrip("0").encode("ascii") + b" "
                       + name.encode("utf-8") + b"\0" + bytes.fromhex(entry["sha"])
                       for name, entry in ordered)
        require(git_hash("tree", raw) == expected_sha,
                "Incomplete or altered recursive tree: " + (path or "<root>"))
    return entries


def decode_blob(blob):
    require(isinstance(blob, dict), "Invalid fetched blob")
    blob_sha = sha(blob.get("sha"), "fetched blob")
    require(type(blob.get("size")) is int and blob["size"] >= 0, "Invalid fetched blob byte size")
    content = blob.get("content")
    require(isinstance(content, str), "Missing fetched blob content")
    if blob.get("encoding") == "base64":
        try:
            raw = base64.b64decode(re.sub(r"[\t\r\n ]", "", content), validate=True)
        except (ValueError, binascii.Error) as exc:
            raise SnapshotError("Invalid base64 fetched blob") from exc
    elif blob.get("encoding") == "utf-8":
        raw = utf8(content, "Fetched blob content")
    else:
        raise SnapshotError("Unsupported blob encoding; use fetch_blob, not empty Contents responses")
    require(len(raw) == blob["size"] and git_hash("blob", raw) == blob_sha,
            "Empty, truncated or altered fetched blob")
    try:
        return blob_sha, raw.decode("utf-8"), len(raw)
    except UnicodeError as exc:
        raise SnapshotError("Required blob is not UTF-8") from exc


def assemble_snapshot(observation):
    """Return only {head, complete: true, files}, or raise SnapshotError.

    Input keys: head, observed_head, commit, tree, blobs. commit is a Git Data
    commit response ({sha, tree: {sha}}) or REST commit response with commit.tree.
    blobs is a list of unique {sha, size, encoding, content} envelopes from
    fetch_blob, one per distinct required blob SHA. UTF-8 content must be exact;
    a connector that returns decoded text may label it encoding='utf-8'.
    """
    require(isinstance(observation, dict) and set(observation) == {
        "head", "observed_head", "commit", "tree", "blobs"}, "Invalid snapshot observation fields")
    head = sha(observation["head"], "pinned commit")
    require(sha(observation["observed_head"], "final observed commit") == head,
            "Branch HEAD changed; refetch a complete snapshot at the new HEAD")
    commit = observation["commit"]
    require(isinstance(commit, dict) and commit.get("sha") == head, "Pinned commit identity mismatch")
    body = commit if "tree" in commit else commit.get("commit")
    require(isinstance(body, dict) and isinstance(body.get("tree"), dict), "Missing pinned commit root tree")
    root_sha = sha(body["tree"].get("sha"), "root tree")
    entries = verified_entries(observation["tree"], root_sha)
    required = {path: entry for path, entry in entries.items()
                if required_path(path) and entry["type"] != "tree"}
    require(MANDATORY <= required.keys(), "Mandatory snapshot paths missing")
    for path, entry in required.items():
        require(entry["type"] == "blob" and entry["mode"] in {"100644", "100755"},
                "Unsupported file type in authoritative snapshot: " + path)
    require(isinstance(observation["blobs"], list), "Fetched blobs must be a list")
    wanted = {entry["sha"] for entry in required.values()}
    blobs = {}
    for blob in observation["blobs"]:
        require(isinstance(blob, dict), "Invalid fetched blob")
        blob_sha = sha(blob.get("sha"), "fetched blob")
        require(blob_sha not in blobs, "Duplicate fetched blob: " + blob_sha)
        require(blob_sha in wanted, "Unexpected fetched blob: " + blob_sha)
        _, content, size = decode_blob(blob)
        blobs[blob_sha] = (content, size)
    require(blobs.keys() == wanted, "Required fetched blobs missing")
    files = {}
    for path, entry in sorted(required.items()):
        content, size = blobs[entry["sha"]]
        require(size == entry["size"], "Blob size differs from pinned tree: " + path)
        files[path] = content
    return {"head": head, "complete": True, "files": files}


def strict_json(text):
    def pairs(values):
        result = {}
        for key, value in values:
            require(key not in result, "Duplicate JSON key")
            result[key] = value
        return result

    def invalid(value):
        raise SnapshotError("Non-finite JSON number")

    return json.loads(text, object_pairs_hook=pairs, parse_constant=invalid)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="Observation JSON; defaults to stdin")
    parser.add_argument("--output", type=Path, help="Snapshot JSON; defaults to stdout")
    args = parser.parse_args()
    status = 0
    try:
        result = assemble_snapshot(strict_json(args.input.read_text(encoding="utf-8")
                                               if args.input else sys.stdin.read()))
    except (ValueError, TypeError, KeyError, OSError) as exc:
        status = 1
        result = {"status": "snapshot_blocked", "complete": False, "error": str(exc)}
    output = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(output, encoding="utf-8")
    else:
        sys.stdout.write(output)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
