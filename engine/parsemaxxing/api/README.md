# api

FastAPI routes: upload, runs, profile confirm, approve/reject, and the server-sent event stream of ledger events for the UI.

Status: built: `app.py` (FastAPI) and `intake.py` (upload checks). No login yet: localhost only (residual risk R1); login and role checks are planned (Phase 13).

Every error response is one envelope, `{"error": {"code", "message", "request_id"}, "detail": message}`, and every response carries `X-Request-ID` (generated per request, never taken from the client) and the security headers. `code` follows the status (`not_found`, `conflict`, `invalid_request`, `forbidden`, `payload_too_large`, `internal_error`, ...). Validation errors name fields, never values; an unexpected exception returns only "internal error" and is logged with the request id. `detail` is kept for the v1 web UI and goes once the web reads `error.message`. The Host check (DNS rebinding) runs in the same middleware, so its refusal uses the envelope too. See [docs/design.md](../../../docs/design.md), section "Platform and UI".
