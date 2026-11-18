# UX specs

Written in Phase 11 by the `ux` agent. These files are the spec the `frontend` agent builds from in Phase 13 onward; nothing here is built yet unless a row says so. Source of truth for features is `docs/design.md` (v2 sections); if a spec here conflicts with it, the design doc wins and the conflict is raised, not guessed.

## Files

| File | Covers | Status |
| --- | --- | --- |
| [information-architecture.md](information-architecture.md) | App shell, navigation, route groups `(auth)` and `(app)`, role-aware visibility, context switcher, global search, "Needs you", URLs | planned (Phase 15) |
| [flows.md](flows.md) | First-run setup, sign in and MFA, connect an environment, build run, profile review with format check, approval with the data model decision, deploy to rollback, add-on versions (view, compare, download, revert, roll forward), discovery, drift, LDAP, API tokens, offline environments | planned (phase per flow) |
| [screens.md](screens.md) | One section per screen: purpose, primary action, content, states, viewer vs admin, progressive disclosure, acceptance checks | planned (phase per screen) |
| [screens-environments.md](screens-environments.md) | Environments list, customers, CIM library, per-environment tabs, add-environment wizard, inherited and overridden settings, isolation walkthrough | planned (Phase 17, 17c, 18) |
| [screens-settings.md](screens-settings.md) | Settings sub-pages | planned (Phases 13 to 21) |
| [copy.md](copy.md) | Voice, vocabulary, status words, button labels, error pattern, confirmation dialogs, empty states | planned (Phase 15 for all screens) |
| [accessibility.md](accessibility.md) | WCAG 2.2 AA requirements, axe and keyboard testing, light and dark tokens | planned (Phase 15) |
| `reviews/<phase>.md` | Findings from reviewing built screens | [13](reviews/13.md) |

## Status by screen and phase

| Phase | Screens and flows | Spec status |
| --- | --- | --- |
| 13 | Sign in, MFA, recovery; setup token; forced MFA enrolment; Account security; API tokens, Users and Audit log screens (interim shell, ahead of Phase 15); `<AdminOnly>` | built (Phase 13), reviewed in [reviews/13.md](reviews/13.md): 3 must-fix items open |
| 14 | Authentication and LDAP (LDAP part), F11 | planned |
| 15 | App shell, Overview (without KPIs), first-run setup wizard (F1), Settings (General, Users, API tokens, Security health, Audit log, About, Data policies page), user menu pages, search, light and dark tokens; **v1 screens rehomed**: runs board, new run sheet, run workspace, profile review, approval report | planned |
| 16 | LLM providers and agents, Budgets, kill switch | planned |
| 17 | Environments list, customers, environment page and tabs, add-environment wizard (F3), offline environments (F13 part), target environment in the new run sheet | planned |
| 17b | Add-ons list (replaces `/tas`), add-on page, version page, compare, compare with installed, revert on the sandbox (F8) | planned |
| 17c | CIM library, CIM and versions tab, spec bundle upload, format check in profile review (F5), data model decision in the approval report (F6) | planned |
| 18 | Deployments list, new deployment dialog, deployment page with relay console and handoff runbook (F7), relay setup, revert per production environment | planned |
| 19 | Overview KPIs, Analytics | planned |
| 20 | Knowledge (overview, sources, import, retrieval), references in the approval report, offline knowledge pack (F13 part) | planned |
| 21 | Discovery (F9), retention and "Delete real data now" | planned |
| 21b | "Start an overlay fix", overlay badge | planned |
| 22 | Drift (F10), Discovery and drift tab (drift part) | planned |
| 23 | Router actor and routing in the plan | planned |
| 24 | Usability pass over everything | planned |

v1 screens that exist today (`web/app/page.tsx` runs board, `web/app/runs/[id]` run workspace with profile review and approval report, `web/app/tas` TA registry): **rehome into the shell in Phase 15** (the TA registry becomes the Add-ons section in 17b). What is kept and what changes is listed in each screen's section in [screens.md](screens.md).

## How these specs are used

1. Before a phase with UI, the `ux` agent updates the relevant sections and marks them ready for that phase.
2. The `frontend` agent builds to the spec. Acceptance checks in each screen section become Playwright tests; every screen also gets the axe, viewer and keyboard checks in [accessibility.md](accessibility.md).
3. A spec gap found while building is raised to `ux`, not guessed; the answer is written here in the same change.
4. When a screen ships, its status in this file changes from "planned" to "built (Phase N)".

## How built screens are reviewed

At the end of each phase with UI, the `ux` agent runs the app (light and dark, 1280 px and 1920 px, as admin and as viewer), runs the Playwright suite, and writes `reviews/<phase>.md`: findings ranked by impact, each with the screen, the problem, who it hurts and the smallest fix. Checklist:

- Can an MSSP admin always tell which customer's environment they are acting on before confirming?
- Can someone answer "what changed between 1.2.0 and 1.4.0, and what runs in production now?" in under a minute?
- Does the revert dialog say that newer versions are kept?
- Can a new admin finish setup without docs? (Phase 15 acceptance: recorded walkthrough.)
- Can a viewer tell in 5 seconds what needs attention?
- Is every admin action clearly absent or disabled for viewers?
- Is wording consistent with [copy.md](copy.md)?
- Are there dead ends (a state with no next action)?
- Does every long task show progress and resume?
- Can an admin set up a second environment without touching or seeing the first one's settings? ([walkthrough](screens-environments.md#isolation-walkthrough))

## Open questions for the owner

| # | Question | Spec assumes until decided |
| --- | --- | --- |
| UX-Q1 | Can a viewer create and revoke their own viewer-role API tokens? D6 says viewers change nothing; 7.3 says a token's role is no higher than its creator's, which implies viewers can create one. | Viewers may manage only their own viewer tokens and their own account security (password, MFA, sessions); everything else is admin only. |
| UX-Q2 | Data policy (hosted models allowed, retention) is stored per customer (section 6) but 7.13 also lists a per-environment Data policy tab. Which scope wins when both are set? | Customer policy is the base; an environment (or a customer inside a shared environment) can only make it stricter; the tab shows the effective value and its source. |
| UX-Q3 | Run status names after the build/deploy split (D7): `promoting` and `done` no longer mean installed on an environment. | UI words "Registering version" and "Version registered" ([copy.md](copy.md#runs)); the engine owner confirms in Phase 17b. |
| UX-Q4 | Dark glass theme: keep as the dark theme, or rework? 7.13 allows rework. | Keep it as the dark theme, add a solid light theme ([accessibility.md](accessibility.md#theme-tokens-light-and-dark)). |
