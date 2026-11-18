# web/ conventions (Next.js + shadcn/ui)

Root rules in [../CLAUDE.md](../CLAUDE.md) apply. Design: [../docs/design.md](../docs/design.md), section "Platform and UI". The UX specs in `docs/ux/` (planned, Phase 11) are the spec for every screen; build from them.

Status: built: runs board, run workspace (phase rail, attempts, live activity), profile review, approval report, TA registry; the /api/engine proxy and proxy.ts (Host allowlist, CSP nonce, sign-in redirect); Phase 13 sign-in, MFA step, recovery code, first-run setup, MFA enrolment, account security, API tokens, users and audit log screens. Rules marked "planned" apply when that part lands.

## Language and tooling
- TypeScript (strict), Next.js App Router, shadcn/ui components on Tailwind.
- Use shadcn/ui components before writing custom ones.
- ESLint (`npm run lint`) and TypeScript (`npm run typecheck`); `npm audit` runs in `make security`.
- Commit `package-lock.json`; install with `npm ci`.
- e2e (`npx playwright test`, after `npm run build`): the engine is mocked in the browser. Every page test starts with a session cookie (`playwright.config.ts`) and `/auth/me` mocked as an admin (`test` from `e2e/fixtures.ts`); use `signedInAs(page, "viewer")` for the viewer run. `e2e/a11y.spec.ts` runs axe-core (already in the tree) on each new screen as admin and viewer.

## Architecture
- The UI holds no business logic and is never a security control; authorization lives in the engine.
- It reads job state and ledger events from FastAPI (server-sent events). Today it sends upload, confirm profile, approve and reject (admin); setup, sign in, MFA code or recovery code, sign out; own account: change password, MFA enrol/confirm/disable, new recovery codes, revoke a session, sign out everywhere, create and revoke API tokens; admin: add user, change role, disable, enable, sign a user out everywhere. It reads `/auth/me`, sessions, tokens, users (admin) and the audit log. As the API grows, it sends every action the API exposes to the user's role, and nothing else.
- Every engine path and method is allowlisted in `app/api/engine/[...path]/route.ts`; a new engine route needs a line there and a case in `e2e/proxy.spec.ts`. The proxy forwards only the `__Host-pmx_session` cookie, the browser's Origin (when it is on the allowed list) and the last `X-Forwarded-For` hop only when `X-Pmx-Hop` matches the secret in `PMX_PROXY_HOP_FILE` (never forwarding `X-Pmx-Hop`), and passes the engine's `Set-Cookie` back unchanged.
- The engine URL comes from server-side environment variables. No secrets in client code or `NEXT_PUBLIC_*` variables.
- Route groups: `(auth)` (`/login`, `/login/mfa`, `/login/recovery`, `/setup`, `/mfa/enrol`; minimal frame, no navigation) and `(app)` (everything else, inside `components/auth/shell.tsx`). Every screen lives inside one of them. The full app shell (sidebar, context switcher) is Phase 15, planned.
- Sessions: the engine's `__Host-pmx_session` cookie only (HttpOnly, set and cleared by the engine through `/api/engine`). Nothing about the session, tokens or codes in local storage, session storage, `NEXT_PUBLIC_*` or URLs. `proxy.ts` sends a page request with no cookie to `/login?next=<path>`; the shell asks `GET /auth/me` before rendering anything and routes by stage (`mfa` → `/login/mfa`, `enrol` → `/mfa/enrol`, 401 → `/login?next=…&ended=1`). `next` is always passed through `safeNext` (`lib/next-path.ts`): same-origin paths only.
- Shown-once values (API token, recovery codes, MFA secret) live only in the component state of the dialog or step that shows them and are dropped when it closes.
- Admin actions: `<AdminOnly>` (`components/auth/session.tsx`) is the one pattern; viewers see the control with `aria-disabled`, a lock and the description "Admin only", and its click does nothing. It is display only; the engine refuses viewers anyway. `useSession()` gives `me` and `isAdmin`.
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
