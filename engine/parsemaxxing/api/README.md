# api

FastAPI routes: upload, runs, profile confirm, approve/reject, and the server-sent event stream of ledger events for the UI.

Status: built: `app.py` (FastAPI) and `intake.py` (upload checks). No login yet: localhost only (residual risk R1); login and role checks are planned (Phase 13). See [docs/design.md](../../../docs/design.md), section "Platform and UI".
