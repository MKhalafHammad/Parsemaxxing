# api

FastAPI routes: upload, runs, profile confirm, approve/reject, TA rollback (`POST /tas/{app_name}/rollback`, admin, audited as `ta_rollback`), the kill switch, and the server-sent event stream of ledger events for the UI.

Status: built: `app.py` (FastAPI), `intake.py` (upload checks) and `client.py` (the CLI's API client, standard library only). Every route has a role policy (Phase 13, `auth/policy.py`). The CLI's mutating commands (`run`, `update`, `approve`, `reject`, `promote`, `rollback`, `kill`) call this API with an API token; see [../auth/README.md](../auth/README.md).

Every error response is one envelope, `{"error": {"code", "message", "request_id"}, "detail": message}`, and every response carries `X-Request-ID` (generated per request, never taken from the client) and the security headers. `code` follows the status (`not_found`, `conflict`, `invalid_request`, `forbidden`, `payload_too_large`, `internal_error`, ...). Validation errors name fields, never values; an unexpected exception returns only "internal error" and is logged with the request id. `detail` is kept for the v1 web UI and goes once the web reads `error.message`. The Host check (DNS rebinding) runs in the same middleware, so its refusal uses the envelope too. See [docs/design.md](../../../docs/design.md), section "Platform and UI".
