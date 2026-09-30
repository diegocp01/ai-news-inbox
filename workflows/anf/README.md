# Forward-only ANF workflow

This deployment preserves the skill behavior and starts a new queue. It began with the two explicitly supplied pending ANFs as records 1–2, checkpoint 0; the live ledger now also tracks subsequent intake. No earlier queue/news/archive/checkpoint/export data is included. Existing `items/` publications are untouched.

`runtime_protocol.md` defines the required GitHub atomic-CAS/readback and native attachment receipt behavior. GitHub is the durable source of truth; local files are caches.

Compilation is enabled in the current `runtime_config.json`, with the recorded user cutover-confirmation digest. The intended saved schedule is Monday–Friday 08:00 America/New_York; scheduler state is external to this repository. No access to the old machine is needed or authorized.

Run isolated tests:

```sh
python3 -m unittest discover -s workflows/anf/tests -v
```

The initial finalized seeds preserve their exact supplied fields without a fresh image-verification assertion. New intake must follow the full editorial and image-verification workflow. Trusted upstream routes remain disabled by default.


## Required final-output gate

Every completed intake must be saved through the authorized GitHub plugin, then
read back from current `main` before `intake_output_gate.py` can release its exact
four-line blocks. The planner always returns `ready_to_send: false`; only the
read-only gate may return `ready_to_send: true` for an intake response. Follow
`runtime_protocol.md` for its input and connector-observation requirements.

The scripts have no network client or credentials. GitHub writes and fresh reads
remain connector operations. The gate deterministically validates those supplied
observations; it cannot independently authenticate GitHub or prevent the assistant
from bypassing the workflow in free-form chat. It does not authorize compilation
attachment delivery or resend an already answered intake.
