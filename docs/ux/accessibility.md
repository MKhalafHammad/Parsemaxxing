# Accessibility and theming requirements

Status: **planned**, Phase 15 (shell, tokens, axe in CI), then every phase with UI. Target: **WCAG 2.2 level AA** on every screen, in light and dark, at 1280 px and 1920 px, and usable down to 320 px wide (reflow, 1.4.10) without loss of function.

## Testing (Definition of done for UI work)

| Check | How | Gate |
| --- | --- | --- |
| Automated rules | `@axe-core/playwright` on every route, as admin and as viewer, light and dark; rules for WCAG 2.0, 2.1 and 2.2 A and AA | No serious or critical violation. New dependency: add it to the design doc's tech stack table with the reason (D8) in Phase 15. |
| Keyboard paths | Playwright, keyboard only, per flow in [flows.md](flows.md) (the v1 `e2e/flow.spec.ts` is the model) | Every flow completes by keyboard |
| Viewer | Playwright as viewer on every screen | Every admin control absent or `aria-disabled="true"` with the "Admin only" description; no request that changes state is possible from the UI |
| Contrast | A token contrast test over every text and status pair in both themes | AA ratios below |
| Screen reader | Manual pass with NVDA plus Firefox and VoiceOver plus Safari on: sign in, run workspace, approval, deploy approve, revert, environment wizard | Recorded in `docs/ux/reviews/<phase>.md` |
| Zoom and reflow | 200% zoom and 320 px viewport on the same screens | No horizontal scroll except data tables and code panes, which scroll in their own region |
| Reduced motion | `prefers-reduced-motion: reduce` | No spinning loaders (static icon plus word), no animated transitions |

## Requirements by area

### Structure and names
- One `h1` per page; headings in order; landmarks: `banner` (top bar), `navigation` "Main" (sidebar), `navigation` "Settings" or "Breadcrumb", `main`, `complementary` for side panels.
- Page titles: "<Object> · <Section> · Parsemaxxing", for example "TA-parsemaxxing-acme-fw 1.3.0 · Add-ons · Parsemaxxing". Title updates on client navigation, and focus moves to the `h1` (WCAG 2.4.2, 2.4.3).
- Skip link kept from v1.
- Every icon-only button has an accessible name; decorative icons `aria-hidden` (as v1).

### Status, colour and environment identity
- Status is always icon plus word plus colour (1.4.1), as in v1 `StatusBadge`.
- Environment colour is chosen from a fixed palette of 8 tokens (`--env-1` to `--env-8`), each meeting 3:1 against the top bar in both themes (1.4.11). The name and the kind badge are always shown with it; colour never carries meaning alone.
- Field colours in raw vs parsed keep tint plus swatch plus the field name (kept).
- Charts: direct labels, markers or dash patterns per series, table toggle.

### Keyboard
- Everything operable by keyboard, in a logical order, with a visible focus ring of at least 2 px in `--focus` meeting 3:1 against adjacent colours (2.4.7, 2.4.13 as good practice).
- **Focus not obscured (2.4.11):** sticky elements (top bar, approval decision bar, environment header) never cover the focused element; scrolling containers use `scroll-padding` equal to the sticky heights.
- Dialogs: focus trapped, initial focus on Cancel for destructive or production confirms (as v1 `data-autofocus`), `Esc` closes, focus returns to the trigger.
- Menus and switchers: ARIA menu or listbox patterns with arrow keys and type-ahead.
- Tabs: environment tabs are links in a `tablist`-styled nav (each has a URL); in-page tabs (version page) use the ARIA tabs pattern with arrow keys.
- Trees (lineage, file tree): ARIA tree with arrow keys, `Home`, `End`; never drag-only (2.5.7).
- Shortcuts: `Ctrl K`/`Cmd K` and `/` for search, `g c` and `g e` for the switchers; single-key shortcuts are off when focus is in a field and can be turned off in Profile (2.1.4).

### Pointer and targets
- Targets at least 24 by 24 CSS px, or spaced so a 24 px circle fits (2.5.8). Table row actions included.
- Reordering (LDAP servers) uses Up and Down buttons, not drag (2.5.7).

### Forms
- Every input has a visible label; help text and errors linked by `aria-describedby`; required marked in text ("required"), not only an asterisk.
- Errors: inline plus a summary at the top after submit with links to the fields (3.3.1, 3.3.3).
- **Redundant entry (3.3.7):** the wizards never ask for the same value twice.
- **Accessible authentication (3.3.8):** paste allowed in password, token and TOTP fields; no cognitive tests; password managers supported (`autocomplete` values set).
- Write-only secret fields never show a placeholder that looks like a value.
- Typed confirmations show the exact text to type and match case-sensitively; the confirm button's disabled state is announced.

### Live content
- Run activity feed and relay console: `role="log"` with `aria-live="polite"` off by default for streams (too chatty) and a "Announce new lines" toggle; the Now banner is `role="status"`.
- Status messages after an action (queued, saved, deployed) are `role="status"`; errors that block are `role="alert"`.
- Updates never move focus. Polling and streams pause when the tab is hidden (as v1).
- Timeouts: the idle-timeout warning gives 2 minutes and "Stay signed in" (2.2.1).

### Text and code
- Log lines, conf and console output are escaped text in monospace, wrapped or horizontally scrollable in their own focusable region with a label ("props.conf, 42 lines").
- Line height and spacing survive user text-spacing overrides (1.4.12); no text in images.
- Consistent help (3.2.6): the help link sits in the user menu on every page.

## Theme tokens (light and dark)

The dark theme keeps v1's dark glass look; a light theme is added. Both are driven by the same semantic tokens in `web/app/globals.css`, selected by `data-theme` on `<html>` (light, dark) with "system" following `prefers-color-scheme`. The choice is saved to the user's profile (not local storage); before sign-in the system theme is used.

| Token | Use | Dark (v1 value, kept) | Light (proposed) | Minimum contrast |
| --- | --- | --- | --- | --- |
| `--bg` | page background | `#060914` | `#f7f8fb` | |
| `--surface` | panels | `rgb(22 28 48 / 0.62)` (glass) | `#ffffff` (solid, no glass) | |
| `--surface-solid` | dialogs, menus | `#121829` | `#ffffff` | |
| `--surface-2` | subtle fills | `rgb(255 255 255 / 0.06)` | `#eef1f6` | |
| `--border` | dividers | `rgb(255 255 255 / 0.1)` | `#d9dee8` | |
| `--border-strong` | input borders, focusable edges | `rgb(255 255 255 / 0.2)` | `#8a94a8` | 3:1 against surface (1.4.11) |
| `--text` | body | `#eef1f8` | `#0f172a` | 4.5:1 (aim 7:1) |
| `--text-muted` | secondary | `#b9c1d4` | `#475569` | 4.5:1 |
| `--text-subtle` | tertiary, timestamps | `#a3abc0` | `#526074` | 4.5:1 |
| `--focus` | focus ring | `#7dd3fc` | `#0369a1` | 3:1 against neighbours |
| `--good` / `--good-bg` | success | `#4ade80` / 12% | `#15803d` / `#e8f5ec` | text 4.5:1 on its bg and on surface |
| `--warn` / `--warn-bg` | waiting, warning | `#fbbf24` / 12% | `#a16207` / `#fdf4e3` | same |
| `--bad` / `--bad-bg` | failure, destructive | `#fd8a9b` / 13% | `#b91c1c` / `#fdecec` | same |
| `--run` / `--run-bg` | running, info | `#7dd3fc` / 12% | `#0369a1` / `#e6f2fa` | same |
| `--prod` | production badge and production confirm button | new | new | 4.5:1 for its text |
| `--env-1` to `--env-8` | environment colours | new palette | new palette | 3:1 against the top bar |
| `--a-*` | actor accents (kept, none green or red) | v1 values | darker variants for light | 3:1 for the avatar ring |
| `--f0` to `--f7` | field tints and swatches | v1 values | lighter tints, darker swatches | text over tint 4.5:1 |
| `--ed-*` | conf editor | v1 values | light editor palette | 4.5:1 for every syntax colour |

Light values are proposals; the Phase 15 contrast test decides the final values and fails the build if any pair is below its minimum. The glass effect (`backdrop-filter`) is dark-theme only and is disabled when `prefers-reduced-transparency: reduce` is set.

Button variants: primary, secondary (outline), destructive (`--bad`), **production** (a distinct variant for confirms that change a production environment: solid `--prod` with a shield icon and the word "Production" in the dialog's context block). Destructive and production buttons are never the default focus.
