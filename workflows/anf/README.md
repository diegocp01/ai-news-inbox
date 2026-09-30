# Forward-only ANF workflow

This deployment preserves the skill behavior and starts a new queue. It contains only the two explicitly supplied pending ANFs as records 1–2, checkpoint 0. No earlier queue/news/archive/checkpoint/export data is included. Existing `items/` publications are untouched.

`runtime_protocol.md` defines the required GitHub atomic-CAS/readback and native attachment receipt behavior. GitHub is the durable source of truth; local files are caches.

Compilation is intentionally paused in `runtime_config.json` until the user confirms the old compiler will no longer run. Record the confirmation digest and enable the flag in one authorized Git commit, verify it, then resume the saved Monday–Friday 08:00 America/New_York schedule. No access to the old machine is needed or authorized.

Run isolated tests:

```sh
python3 -m unittest discover -s workflows/anf/tests -v
```

The initial finalized seeds preserve their exact supplied fields without a fresh image-verification assertion. New intake must follow the full editorial and image-verification workflow. Trusted upstream routes remain disabled by default.
