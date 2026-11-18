# Information architecture and navigation

Status: **planned**. Spec for Phase 15 (app shell, navigation, context switcher, search, "Needs you"), with the sections filled in by the phase that builds each one (see the table in [README.md](README.md)). Source: master prompt 7.13, 7.3, D3, D6, D7.

## Users and what they come for

| User | Comes to | Must never |
| --- | --- | --- |
| Admin (Splunk engineer at a SOC or MSP) | Start a run, clear "Needs you", approve, deploy, fix a failing connection, move on | Act on the wrong customer's Splunk; lose an add-on version |
| Viewer (analyst, team lead, auditor) | Status, evidence, history, "what runs where" | Wonder whether a click changes something |

## App shell

```
+--------------------------------------------------------------------------------------+
| [=] Parsemaxxing | [Customer: Globex v] [Environment: (#) globex-prod  Production v] |
|                  |         [ Search runs, add-ons, environments...  Ctrl K ]  [Bell 3] [MK v] |
+------------+-------------------------------------------------------------------------+
| Overview   |  Breadcrumb: Add-ons / TA-parsemaxxing-acme-fw / 1.3.0                  |
| Runs       |                                                                         |
| Discovery  |  <h1> Page title                                    [Primary action]    |
| Add-ons    |                                                                         |
| Deployments|  content                                                                |
| Drift      |                                                                         |
| Environments                                                                         |
| Knowledge  |                                                                         |
| Analytics  |                                                                         |
| ---------- |                                                                         |
| Settings   |                                                                         |
| [<<]       |                                                                         |
+------------+-------------------------------------------------------------------------+
```

| Region | Content | Rules |
| --- | --- | --- |
| Skip link | "Skip to content" (kept from v1) | First focusable element on every page |
| Left sidebar | The ten sections below, icon plus label; Settings separated at the bottom; collapse toggle | Collapsed shows icons with a visible tooltip and the accessible name; state remembered per user (profile setting, not local storage). Below 1024 px it becomes a drawer opened from the menu button. Current section has `aria-current="page"` and a non-colour marker (bar plus bold label). |
| Top bar | Product name (link to Overview), context switcher, global search, "Needs you" bell with count, user menu | Always visible (sticky). Never scrolls away during a dialog. |
| Environment strip | When an environment is selected: a 4 px band in the environment's colour under the top bar plus its name and kind badge in the switcher | Colour is never the only signal: the name and the "Production" or "Sandbox" badge (icon plus word) are always shown with it |
| Breadcrumb | Section / object / sub-object | Every object page; the last item is the page and is not a link |
| Page header | `h1`, one-line description, at most one primary action button (right) | Secondary actions go in a "More" menu or inline; destructive actions never sit next to the primary action without a gap and a different variant |
| Main | The page | Max width 90rem as today; tables may use the full width at 1920 px |

Engine banners (above the page header, full width, `role="status"` or `role="alert"`): kill switch on, ledger integrity check failed, setup not finished, the platform not yet hardened for exposure beyond localhost (until Phases 12 to 14 land), session about to expire (2 minutes before idle timeout, with "Stay signed in").

## Navigation

| # | Section | Route | Contains | Viewer | Admin | Built in |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Overview | `/` | "Needs you", setup checklist (until complete), KPI tiles, environment health, recent activity | Read | Read, act from cards | 15 (shell, checklist, Needs you); 19 (KPIs, trends) |
| 2 | Runs | `/runs`, `/runs/[id]` | Runs board, run workspace, profile review, approval report | Read | Start, review, approve, reject | v1, rehomed in 15 |
| 3 | Discovery | `/discovery`, `/discovery/scans/[id]`, `/discovery/findings/[id]` | Index scans, findings, "Start a run from this finding" | Read | Scan, start run, start overlay fix | 21 (overlay action 21b) |
| 4 | Add-ons | `/addons`, `/addons/[app]`, `/addons/[app]/versions/[v]`, `/addons/[app]/compare`, `/addons/[app]/compare-installed` | List, where each version runs, timeline and lineage, files, compare, download | Read, compare, download | Plus deploy, revert, deprecate | 17b (replaces v1 `/tas`) |
| 5 | Deployments | `/deployments`, `/deployments/[id]`, `/deployments/new` | Deployment list, plan, impact, approval, delivery (console), verify, rollback | Read, watch console | Plan, approve, mark delivered, cancel, roll back | 18 |
| 6 | Drift | `/drift`, `/drift/[id]` | Drift signals per environment and add-on, the update run, the proposed deployment | Read | Dismiss, start update, open proposed deployment | 22 |
| 7 | Environments | `/environments`, `/environments/new`, `/environments/[env]/[tab]`, `/environments/customers`, `/environments/customers/[customer]`, `/environments/cim-library` | Environments list, add-environment wizard, per-environment tabs, customers, CIM library | Read (secrets never shown) | Full | 17 (CIM library 17c) |
| 8 | Knowledge | `/knowledge`, `/knowledge/sources`, `/knowledge/import`, `/knowledge/retrieval` | Manual checklist, sources and tiers, quarantine, import, test retrieval | Read | Import, approve, reject, re-index | 20 (spec bundle upload 17c) |
| 9 | Analytics | `/analytics/[area]` with areas `runs`, `addons`, `cost`, `environments`, `knowledge` | Charts with data-table toggle, drill-down | Read | Read | 19 |
| 10 | Settings | `/settings/[page]` | Sub-pages below | Read (secrets show "Set"), own account actions | Full | 15 (shell, Users, API tokens, Audit log, Security health, About, General); 13 (login, MFA, tokens back end); 14 (LDAP); 16 (LLM, Budgets); 21 (Data policies retention) |

Settings sub-pages, in this order: General · LLM providers and agents · Budgets · Authentication and LDAP · Users · API tokens · Data policies · Security health · Audit log · About. Routes: `/settings/general`, `/settings/llm`, `/settings/budgets`, `/settings/authentication`, `/settings/users`, `/settings/api-tokens`, `/settings/data-policies`, `/settings/security-health`, `/settings/audit-log`, `/settings/about`. Settings holds **platform** settings only. Environment and per-customer settings live on the environment's page, never here, so platform and environment scopes cannot be confused (see [screens-environments.md](screens-environments.md)).

Customers sit under Environments (a tab on the Environments list page) because a customer is defined by the environments and indexes it owns. The context switcher is the everyday way to pick one.

## Route groups

| Group | Routes | Shell | Session |
| --- | --- | --- | --- |
| `(auth)` | `/login`, `/login/mfa`, `/login/recovery`, `/setup` (first run, needs the setup token), `/mfa/enrol` (forced enrolment) | Minimal: product name, theme toggle, no navigation | None or partial (MFA pending) |
| `(app)` | Everything else | Full shell | Required; an expired session redirects to `/login?next=<path>` and returns to the same page and context after sign-in |

`/setup` exists only until the first admin is created; afterwards it returns "Setup is already complete" with a link to sign in. Routes are server-checked: the UI hides or disables admin actions, but the engine is the control (7.3).

## Role-aware visibility

One rule: **viewers see the same pages as admins, with every admin action shown disabled and labelled "Admin only"**. They never see a button that looks clickable and then fails.

| Pattern | Viewer sees | Admin sees |
| --- | --- | --- |
| Primary action button (Start run, Deploy, Approve, Add environment) | The button, `aria-disabled="true"`, a lock icon, a tooltip and accessible description "Admin only" | The button |
| Row actions and "More" menu items | Same, disabled with "Admin only" | Enabled |
| Write-only secret fields | "Set, updated 3 days ago" or "Not set"; no input | Same status plus "Replace" and "Test" |
| Forms (settings, environment tabs) | Read-only values with their source ("default", "set for this environment") | Editable |
| Raw samples | Shown by default (owner decision); each view audited; if "mask raw samples for viewers" is on, masked values with a "Masked for viewers" note | Raw |
| Live relay console | Watch and replay | Watch and replay (nobody can type into it) |
| Own account (password, MFA, own sessions) | Full | Full |
| Own API tokens | See open question UX-Q1 in [README.md](README.md) | Create (role no higher than their own), revoke |

The pattern is one component (`<AdminOnly>`). A user menu badge shows the role ("Viewer" or "Admin") so a viewer knows at once why actions are locked.

Pages for which a viewer has nothing useful to do still render: there are no admin-only routes except `/setup`. Secret values are never sent to the browser for anyone.

## Context switcher (customer, then environment)

Purpose: filter every list, chart and action to one customer and, optionally, one environment, and keep that choice in view.

```
[ Customer: All customers v ]  [ Environment: All environments v ]

Customer menu                      Environment menu (customer Globex)
  All customers                      All Globex environments
  ----------                         Dedicated
  Globex      2 environments           (#) globex-prod      Production  Healthy
  Initech     1 environment            (#) globex-sbx       Sandbox     Healthy
                                     Shared (MSSP)
                                       (#) msp-shared-1     Production  Warning
                                           Globex indexes: cus_globex_*
```

| Rule | Detail |
| --- | --- |
| Order | Customer first, then environment. The environment menu lists the customer's dedicated environments, then each shared environment where the customer has indexes, then the linked sandboxes. With "All customers" it lists every environment, grouped by customer, shared environments in their own group. |
| Where it lives | In the URL query (`?customer=globex&env=globex-prod`) so links and the browser back button keep the context; the shell carries it across sections. The last choice is saved to the user's profile and restored on sign-in. |
| What it filters | Runs (by target environment and customer), Discovery, Add-ons ("where it runs" columns), Deployments, Drift, Analytics, Overview, global search ranking. Environments list highlights rather than hides. Knowledge and Settings are platform-wide and show "Not filtered by customer" next to the page title. |
| Shown everywhere it matters | Environment name, colour and kind badge in the top bar; repeated in the header of every deploy, revert, approve and roll back dialog, and on every environment tab. |
| Filter, never target | The switcher only filters. A dialog's target always comes from the object being acted on (the deployment's environment, the environment picked in the dialog). If the target differs from the current context, the dialog says so: "You are viewing Initech. This deploys to globex-prod (Globex)." |
| Shared environments | Picking a customer and a shared environment shows that customer's view of it (its indexes, its HFs). Actions that touch shared search heads say "shared by 3 customers" in the dialog. |
| Keyboard | Each switcher is a button that opens a listbox with type-ahead; `Esc` closes and returns focus. Shortcut `g` then `c` focuses the customer switcher, `g` then `e` the environment switcher. |
| Clear | An "x" next to a set value returns to "All"; the page announces "Showing all customers" in a polite live region. |

## Global search

| Item | Spec |
| --- | --- |
| Open | Search field in the top bar; `Ctrl K` or `Cmd K`, and `/` when focus is not in a text field |
| Scope | Runs (run ID, source file, vendor, product, sourcetype), add-ons (app name, sourcetype), versions (`TA-parsemaxxing-acme-fw 1.3.0`, SHA-256 prefix of 8 or more characters), environments (name, host name of a node), customers, deployments (ID), discovery findings (index, sourcetype) |
| Results | Grouped by type, 5 per group, each with its status word and its customer and environment; "Show all results" opens `/search?q=` |
| Context | Results in the current customer and environment are ranked first and marked "In current context"; others are still shown, with their customer named |
| Pattern | ARIA combobox with a listbox; arrow keys move, `Enter` opens, `Esc` closes; result count announced |
| Empty | "No runs, add-ons or environments match "fw-02". Try a run ID, an add-on name or a SHA-256 prefix." |
| Never | Searches log content or secrets; returns objects the user's role cannot read (none in v2, both roles read all) |

## "Needs you" (notifications)

The bell in the top bar and the first section of Overview show the same list.

| Item type | Appears when | Primary link | Clears when |
| --- | --- | --- | --- |
| Profile review | A run is in `profile_review` | Review profile | Profile confirmed |
| Version approval | A run is in `awaiting_approval` | Review and decide | Approved or rejected |
| Deployment approval | A deployment is `awaiting_approval` (four-eyes: hidden from its requester, shown to other admins) | Review plan | Approved, cancelled |
| Handoff delivery | A handoff deployment waits for "Mark delivered" | Open runbook | Marked delivered or cancelled |
| Failed deployment | `failed` (verify or delivery) | Open deployment | Rolled back, redeployed or dismissed with a reason |
| Drift | A drift signal is open or its update run needs review | Open drift | Resolved or dismissed |
| Connection failing | A node test failed twice in a row | Open environment Connection tab | Next test passes |
| Token or key expiring | Splunk token or API token within 14 days (warning) or 3 days (urgent) | Open Credentials or API tokens | Replaced |
| Integrity failed | A stored package or the ledger fails its hash check | Open add-on version or Security health | Cleared by an admin after investigation |
| CIM version missing | An environment's installed CIM version has no matching library upload | Open CIM library | Matching upload |
| Knowledge import waiting | An imported source is quarantined | Review source | Approved or rejected |
| Real data expiring | A run waiting on a human will expire within 3 days (7.19) | Open run | Human acts or data deleted |

Rules:
- Grouped by customer and environment, newest first, each item names the customer, environment and object ("Approve deployment: TA-parsemaxxing-acme-fw 1.3.0 to globex-prod").
- The count on the bell is for items the user can act on. Viewers see the same items under "Waiting on an admin", count shown, no action buttons, just "Open".
- Filtered by the context switcher, with "3 more in other customers" when hidden items exist, so nothing is silently out of view.
- New items are announced once in a polite live region ("New: deployment awaiting approval for globex-prod"); never focus-stealing.
- Urgent (red) items are failed deployments, integrity failures and tokens expiring within 3 days; each still carries an icon and a word.

## URL and deep links

Every view that someone may share is a URL: run phase and attempt (`/runs/<id>?phase=extraction&attempt=2`, kept from v1), approval report section anchors, version file (`/addons/<app>/versions/1.3.0?file=default/props.conf`), compare (`/addons/<app>/compare?from=1.2.0&to=1.4.0&file=default/props.conf`, from 7.15), deployment step, environment tab (`/environments/globex-prod/credentials`), analytics filters. The context query is appended to all of them.

## What changes from v1

| v1 | v2 | Phase |
| --- | --- | --- |
| Top navigation with "Runs" and "TA registry" | Left sidebar, ten sections, top bar with context | 15 |
| Runs board at `/` | Runs board at `/runs`; `/` becomes Overview, whose "Needs you" and "Recent runs" link to the board. `/tas` redirects to `/addons` (permanent) | 15, 17b |
| "Needs you" on the board only | "Needs you" in the bell and on Overview; the board keeps its pinned section | 15 |
| Single dark glass theme | Light and dark themes from tokens, dark glass kept as the dark theme ([accessibility.md](accessibility.md)) | 15 |
| Tagline "Agents propose · code acts · Splunk judges · you approve" in the header | Moves to the About page and the login screen; the top bar needs the space for context | 15 |
