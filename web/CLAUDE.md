# web/ conventions (Next.js + shadcn/ui)

Root rules in [../CLAUDE.md](../CLAUDE.md) apply. Design: [../docs/design.md](../docs/design.md), section "Platform and UI". The UX specs in `docs/ux/` (planned, Phase 11) are the spec for every screen; build from them.

Status: built: runs board, run workspace (phase rail, attempts, live activity), profile review, approval report, TA registry; the /api/engine proxy and proxy.ts (Host allowlist, CSP nonce). Rules marked "planned" apply when that part lands.

## Language and tooling
- TypeScript (strict), Next.js App Router, shadcn/ui components on Tailwind.
- Use shadcn/ui components before writing custom ones.
- ESLint (`npm run lint`) and TypeScript (`npm run typecheck`); `npm audit` runs in `make security`.
- Commit `package-lock.json`; install with `npm ci`.

## Architecture
- The UI holds no business logic and is never a security control; authorization lives in the engine.
- It reads job state and ledger events from FastAPI (server-sent events). Today it sends upload, confirm profile, approve and reject. As the API grows, it sends every action the API exposes to the user's role, and nothing else.
- The engine URL comes from server-side environment variables. No secrets in client code or `NEXT_PUBLIC_*` variables.
- App shell (Phase 15, planned): route groups `(auth)` for login and MFA, `(app)` for the shell with navigation; every screen lives inside one of them.
- Sessions (Phase 13, planned): the engine's `__Host-` session cookie only; nothing about the session in local storage or session storage.
- Admin actions (planned): `<AdminOnly>` is the one pattern; viewers see the action disabled with "Admin only".
- Secret fields (planned): write-only. Show "set" with the last update time and a "replace" action; never render or prefill a secret value.

## Safety conventions
- Log text and every API string are rendered only as escaped text. Highlights in the raw vs parsed view are built as React elements from offsets, never as HTML strings.
- Never use `dangerouslySetInnerHTML`, `eval` or raw HTML from logs or API responses.
- Approve and reject always require a second confirmation that names the package hash.
- Accessible by default: labelled controls, keyboard navigation, visible focus.

## UI conventions
- Actors are defined once in `lib/actors.ts` and shown with `components/actors/actor.tsx`; never invent another icon or colour for an agent.
- The UI reads the engine's event labels (`stage`, `attempt`, `visit`, `actor`, `kind`, `detail`) through `lib/events.ts`; it never parses the text line.
- Colours come from the tokens in `app/globals.css`: today one dark glass theme (`.glass` panels, `.bubble` pills, `.btn-primary`); light and dark tokens are planned (Phase 15). Every text and status pair at WCAG AA. Status is always icon + word + colour.
- Charts (Phase 19, planned): from the chosen chart library only, each with a data-table toggle, never colour alone.
- Configuration is shown as the .conf file in an editor-style pane (line numbers, syntax colours, an "Explain settings" toggle); diffs stay as rows.
- Runs recorded before the event labels are read by `lib/legacy.ts` (display only); never extend it for new events, which carry their own labels.
- Diffs are rows (`components/run/config-view.tsx`): no `---`, `+++`, `@@` or leading `+`/`-`; `e2e/xss.spec.ts` asserts it.
