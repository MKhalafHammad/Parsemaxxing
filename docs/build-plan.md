# Parsemaxxing build plan

> Phases 0 to 10 built v1 (Oct 27 to Nov 4, 2026; tagged `v1.0.0`). Phases 11 to 25 build v2, the multi-environment platform. Source of truth for *what* to build: [design.md](design.md). Rules for *how*: [../CLAUDE.md](../CLAUDE.md).

## Status

Updated at the end of every phase.

| # | Phase | Target date (v1) | Status | Date completed |
| --- | --- | --- | --- | --- |
| 0 | Repository foundation | Oct 27 | Done | Oct 27 |
| 1 | Threat model and lab verification | Oct 27 | Done | Oct 27 |
| 2 | Walking skeleton (JSON, CLI, end to end) | Oct 28 | Done | Oct 27 |
| 3 | Extraction, CIM mapper, full Validator, generator | Oct 29–30 | Done | Oct 28 |
| 4 | Guardrails, adversarial suite, workflow integrity | Oct 31 | Done | Oct 28 |
| 5 | Job queue, workers, ledger, FastAPI, event stream | Nov 1 | Done (clean-install check passed Nov 4) | Oct 28 |
| 6 | Next.js UI (four screens) | Nov 2 | Done | Oct 28 |
| 7 | Parser updates | Nov 3 (morning, only if ahead) | Done | Oct 28 (lab promotion and rollback Oct 30) |
| 7b | UI redesign (agent-centred, readable, navigable) | Before Phase 8 | Done | Oct 30 |
| 7c | Logs without a truth manifest (upload just the log) | Before Phase 10 ends | Done | Nov 2 |
| 8 | Drift pipeline | — | Superseded by Phase 22 | |
| 9 | Mixed-feed routing | — | Superseded by Phase 23 | |
| 10 | One-command Docker setup, README, scenario scripts | Nov 3 | Done (clean-VM test passed; image digests deferred, R12) | Nov 4 |
| 11 | Foundation: tag, rename, licence, cleanup, v2 design and security docs, lab probes | — | In progress | |
| 12 | Hardened runtime, settings store and vault | — | Planned | |
| 13 | Authentication and RBAC | — | Planned | |
| 14 | LDAP | — | Planned | |
| 15 | App shell and UX architecture | — | Planned | |
| 16 | LLM providers and per-agent models | — | Planned | |
| 17 | Customers, environments and topology | — | Planned | |
| 17b | Add-on version control | — | Planned | |
| 17c | Parsing coverage: CIM library, data model selection, spec key table, formats | — | Planned | |
| 18 | Deployment pipeline | — | Planned | |
| 19 | Analytics dashboard | — | Planned | |
| 20 | Knowledge base (RAG) | — | Planned | |
| 21 | Discovery, masking and real-log retention | — | Planned | |
| 21b | Overlay fixes for existing add-ons | — | Planned | |
| 22 | Drift pipeline, multi-environment (replaces Phase 8) | — | Planned | |
| 23 | Mixed-feed routing, topology-aware (replaces Phase 9) | — | Planned | |
| 24 | Security verification, UX usability pass, release 2.0.0 | — | Planned | |
| 25 | Onboarding governance design (no code) | — | Planned | |

## Releases

SemVer for the platform, independent of TA versions.

| Tag | When | Means |
| --- | --- | --- |
| `v1.0.0` | Phase 11, first step (OWNER ACTION) | v1 as released, MIT licence, kept reachable |
| `2.0.0-alpha.1` | After Phase 15 | A team can run it on a shared server: hardened, logged in, LDAP, app shell |
| `2.0.0-alpha.2` | After Phase 18 | Multi-environment deployments |
| `2.0.0-beta.1` | After Phase 23 | Every v2 feature in place |
| `2.0.0` | End of Phase 24 | Security verified, docs truthful |

## How to read this plan

- **Order is priority.** A working product exists after Phase 2; each later phase is an addition. In v2, Phases 12 to 14 must land before the platform is ever exposed beyond localhost; the README says so until then.
- **Phases 8 and 9 are superseded** by Phases 22 and 23, which add multiple environments and topology. Their entries below stay as the base those phases extend.
- **Branches.** v1 used one pull request per phase from `dev` into `main`. From Phase 11, each phase uses its own branch `phase-<nn>-<slug>` (a phase may have several), merged into `main` by a pull request. CI must be green, `main` must always build, and the owner merges. The Status table is updated in the same pull request.
- **Every v2 phase ends with** `make lint`, `make test`, `make security` and the e2e suite green, a `docs/build-log.md` entry, the Status table updated, and an `appsec` review. Each phase entry lists the docs it updates.
- **Phase workflow (v2):** `ux` spec (for UI work) → owner agents implement → `qa` tests → `appsec` review → `docs` update → build-log entry.
- **Scenario scripts.** The `demo/` folder holds repeatable scenario scripts that reproduce a behaviour end to end (for example a gate block). A phase that adds such a behaviour adds a script and names it in its entry.
- **Non-negotiables apply from Phase 2, not Phase 4.** CLAUDE.md requires them from the first deploy, so Phase 2 already contains minimal versions of:
  - the escaping conf writer;
  - the test identity;
  - the `pmx_` ingest check;
  - the TA-name pattern.

  Phase 4 makes them complete, adds every other Must guardrail, and adds the adversarial suite.
- **OWNER ACTION** marks anything that needs real Splunk, an LLM API key, money, a GitHub setting or a decision. Code can be written without these, but the phase is not done until they are completed.
- **Credit budget (v1: $150).**
  - Phases 2–4 use real model calls on small samples.
  - From Phase 2, every run has a per-run token ceiling.
  - From Phase 5, there is also a daily global cap and a kill switch.

---

## Phase 1 — Threat model and lab verification

**Goal:** know the threats before writing code that touches Splunk, and turn every open question in design.md into a verified fact or a decision.
**Target date:** Tue Oct 27.
**Owners:**
- The main session writes the threat model, and `appsec` reviews it.
- `splunk` writes the lab probes.
- `agents-ai` writes the LLM probe.

### Deliverables
- **`docs/threat-model.md`**, filling in the skeleton's sections:
  - assets;
  - actors and trust boundaries: browser ↔ API ↔ orchestrator ↔ model, Splunk REST, uploads;
  - data flows;
  - the threats per area;
  - a table that maps each threat to the design's guardrails, with priority and the phase that delivers it;
  - residual risks.
- **`docs/lab-findings.md`**: each open question, how it was tested, the result, and the design decision it causes.
- **`engine/parsemaxxing/tools/probes/`**, small read-only scripts the owner runs against the lab:
  - `probe_llm.py`: does the Meta Model API accept `response_format` with a JSON schema, or do we need a forced tool call? It reports the token usage of one tiny request.
  - `probe_splunk.py`: tests token auth, a scoped search, the reload endpoint and the ingest path, against `pmx_probe` only.
- **design.md updates** for every question answered, each with a dated note.

### Open questions to settle
- **From design.md:**
  - `response_format` support.
  - "Contributor mode".
  - Whether index-time settings apply to the next oneshot right after a reload.
  - Which edge cases are in scope.
  - Four agents or three.
- **Added by this plan** (the design assumes these work over REST; they must be proven):
  1. **Deploy path.**
     - Option A: install the TA as a package through `apps/local`. This needs the `.tgz` on the Splunk host, which means a shared volume.
     - Option B: write stanzas through the `configs/conf-*` endpoints into the app.
     - Decision needed.
  2. **`btool check`.** It needs a shell on the Splunk host. Running it from the engine would need the Docker socket, which is too dangerous. Decide between:
     - a local conf-syntax check;
     - REST reload plus the reload messages;
     - a minimal sidecar.
  3. **Ingest path.** `data/inputs/oneshot` reads a file on the Splunk host, so it also needs a shared volume. The alternative, `receivers/simple`, must be checked for the full index-time pipeline: line breaking, timestamps and the `sourcetype`/`index` parameters.
  4. **Deploy role capabilities.** Which ones `parsemaxxing_deploy` needs to install apps, reload and ingest into `pmx_*`. The design flags this "for day 1".
  5. **CIM add-on.** It is installed, and `pmx_*` is added to the `cim_<Model>_indexes` macros.

### Acceptance criteria
- `docs/threat-model.md` has no empty section, and every threat row names a guardrail and a phase.
- `appsec` has reviewed it, and every finding is either fixed in the document or listed under residual risk.
- `docs/lab-findings.md` has a verified answer for all 5 added questions and the 5 design questions. Each answer shows the probe output or the exact manual step.
- `python -m parsemaxxing.tools.probes.probe_llm` prints which structured-output mode works and the token count for one call.
- `python -m parsemaxxing.tools.probes.probe_splunk` runs a search as `parsemaxxing_search` and gets results. It is refused when it searches a non-`pmx_` index. It ingests 3 lines into `pmx_probe` and reads back a count of 3.
- `make lint test security` passes.

### OWNER ACTION
- **Splunk lab:** start the lab, either with `make up` or on the Proxmox VM. Then create:
  - the three roles and accounts (`parsemaxxing_search`, `parsemaxxing_deploy`, `parsemaxxing_drift`);
  - their tokens, written into `.env`;
  - the `pmx_probe` index.
- **CIM add-on:** install the Splunk Common Information Model add-on in the lab and edit its index macros.
- **Meta credits:** claim the $150 credits, set the spend limit on the billing page, and put `LLM_API_KEY` in `.env`.
- **Run the probes:** run both scripts and paste the output into `docs/lab-findings.md`. If you'd rather, give me the output and I'll write it in.
- **Decide** deploy path A or B, the `btool` approach, and four agents or three.
- **GitHub:** set `main` as the default branch and turn on branch protection and private vulnerability reporting. *(2026-10-27: branch protection skipped by the owner. The owner still merges every PR from `dev`, and CI runs on each PR, but nothing on GitHub enforces it.)*

### Appsec review focus
- Completeness of the threat model, especially:
  - prompt injection via logs;
  - conf injection;
  - the Docker-socket temptation.
- That the probes are read-only apart from `pmx_probe`.
- That no token appears in probe output or in `lab-findings.md`.

### Suggested commits
- `docs: write threat model`
- `feat: add lab and model API probes`
- `docs: record lab findings and design decisions`

### If late, cut
- Write the threat model at table level only, without prose. Never skip questions 1–4: Phase 2 cannot deploy without them.

---

## Phase 2 — Walking skeleton (one JSON log, CLI only, end to end)

**Goal:** `parsemaxxing run <file.json>` profiles one synthetic JSON log, proposes index-time settings, deploys them under the test identity, ingests them into a fresh `pmx_` index, and passes one Validator check. A working product exists from this point.
**Target date:** Wed Oct 28.
**Owners:**
- `engine`: the CLI and a minimal orchestrator.
- `agents-ai`: the LLM client, the Profiler and the Index-time agent.
- `splunk`: the Splunk client, conf writer, TA builder, deploy, ingest and Validator check.
- `qa`: tests.

### Deliverables
- **Fixture:** a hand-built synthetic JSON log of about 60 events in `engine/parsemaxxing/generator/fixtures/`, with a truth manifest giving the event count and epochs.
- **Agents:**
  - `agents/llm.py`: an OpenAI-SDK client configured from the environment. It has timeouts and a per-run token ceiling, and uses the structured-output mode chosen in Phase 1.
  - `agents/profiler.py` returns a `LogProfile` (Pydantic).
  - `agents/index_time.py` returns an index-time stanza (Pydantic).
  - Untrusted text is passed as delimited data.
- **TA builder:**
  - `ta_builder/conf_writer.py` is the one escaping writer and rejects newlines.
  - `ta_builder/naming.py` holds the TA-name pattern, the test-identity suffix and the `pmx_` index naming.
- **Splunk tools:** `tools/splunk_client.py` provides scoped-token search, deploy using the path chosen in Phase 1, reload, and ingest, which rejects any index that doesn't start with `pmx_`.
- **Validator:** `validator/index_time.py` runs one check, the event count from `| tstats count`, polling until two reads in a row match.
- **Orchestrator:** `orchestrator/run.py` runs Profile → (auto-approved review) → Index-time, retrying up to 5 times with evidence. Its state lives in memory; PostgreSQL arrives in Phase 5.
- **CLI:** `parsemaxxing run <file>`, a `[project.scripts]` entry, prints the stage, attempt, check result and evidence.

### Carried over from Phase 1 (lab findings and appsec review)
- **Deploy:** install the complete `.tgz` through `apps/local` with `update=true` (Q6).
  - The packages folder is checked: a real directory, owned by the engine user, not group- or world-writable.
  - Packages are written with `O_EXCL|O_NOFOLLOW` under a unique name, and the SHA-256 is re-checked just before install (T5.9).
  - The package file allowlist arrives now, not in Phase 4 (T2.2, T3.4).
  - The install and delete helpers assert the app-name pattern and the package path before every call (T7.4).
- **Ingest:**
  - `receivers/simple` into the one shared `PARSEMAXXING_TEST_INDEX` (Q8, Q9).
  - The sourcetype is `<st>__test_<job>_a<attempt>`, and before ingest the code asserts it has 0 events, else bumps the attempt number (T4.5).
  - No reload is needed (Q3); keep one `conf-props` reload only as a logged safety net.
- **LLM client:** uses `response_format` with a strict JSON schema, and `max_tokens` leaves headroom for reasoning (Q1). Hitting the cap counts as bad output.
- **Agent `run_search`:** code owns the base search (`search index=<test index> sourcetype=<own attempt>`); the agent appends only a `|` pipeline (T1.2). *(Moved to Phase 3: in Phase 2 the agents get Validator evidence and no search tool.)*
- **Gate:** the index-time key allowlist with typed values and bounds. A post-ingest `_internal` warning check fails closed (Q7, T2.11).

### Acceptance criteria
- `parsemaxxing run engine/parsemaxxing/generator/fixtures/<sample>.json` exits 0 against the lab and prints `index-time: PASS (event count 60/60)`.
- During the run, Splunk shows the app `TA-parsemaxxing-<vendor>-<product>__test_<job>` and the sourcetype `<st>__test_<job>`. The real names never appear.
- The data lands in the shared test index (`PARSEMAXXING_TEST_INDEX`) under the sourcetype `<st>__test_<job>_a<attempt>`, and its count for that sourcetype equals the manifest's.
- Unit tests:
  - the conf writer rejects a value containing `\n` or `\r`;
  - the TA-name pattern rejects `../x`, `A-B` and `x y`;
  - ingest raises an error for `main` and for `pw` without the underscore;
  - Pydantic rejects malformed agent output.
- The LLM client's token ceiling stops a run, and a test covers this with a fake client.
- No real network in the tests. Splunk and the LLM are faked, and the lab run is a manual step.
- `make lint test security` passes.

### OWNER ACTION
- Lab running, with tokens in `.env`.
- Run the end-to-end command once against the lab and confirm the PASS line.
- Check the token spend on the Meta billing page after the run.

### Appsec review focus
- Escaping in the conf writer.
- Path handling in the TA builder (resolved paths stay inside the app).
- That deploy and ingest use the correct scoped tokens.
- Prompt construction: logs passed as data.
- That nothing logs tokens or full prompts.

### Suggested commits
- `feat: add escaping conf writer and TA naming rules`
- `feat: add Splunk client with scoped deploy and pmx_ ingest`
- `feat: add Profiler and Index-time agents`
- `feat: add parsemaxxing run CLI for the index-time stage`

### Scenario script
- `demo/01_fix_loop.sh`: an Index-time attempt fails a Validator check, the agent gets the evidence and the next attempt passes.

### If late, cut
- Profile review UI-equivalent prompts (auto-approve only).
- Retries beyond 2.
- Keep the one Validator check and the test identity.

---

## Phase 3 — Extraction and CIM mapper stages, full Validator, synthetic generator

**Goal:** the full three-stage pipeline on all four formats and three CIM models, scored against generated truth.
**Target dates:**
- Thu Oct 29: the generator and the Extraction stage.
- Fri Oct 30: the CIM mapper and the full Validator.

**Owners:**
- `splunk`: the Validator and `cim_spec/`.
- `agents-ai`: the Extraction and CIM mapper agents, and `test_regex`.
- `qa`: the generator fixtures and tests.
- `engine`: orchestrator stage order, regression re-runs and the one-time backtrack.

### Deliverables
- **Synthetic generator** in `generator/`: JSON, key=value, syslog and CSV. It writes event categories that match Authentication, Network_Traffic and Web, plus a truth manifest with:
  - the count;
  - the true epoch per event;
  - true field values;
  - the category per event.
- **Committed fixtures:** one per format, plus one with a missing timezone and one multi-line case if Phase 1 put it in scope.
- **Agents:**
  - `agents/extraction.py` returns `KV_MODE`, `EXTRACT-` and `REPORT-` settings plus transforms.
  - `agents/cim_mapper.py` returns `FIELDALIAS`, `EVAL`, eventtypes and tags.
- **Tools:**
  - `tools/regex_test.py` provides `test_regex`, using the `regex` package with a timeout.
  - `tools/search_guard.py` provides `run_search` with a command allowlist, 50 rows and a timeout.
- **`cim_spec/`:** required fields and allowed values for the 3 models, pinned from the CIM documentation, with the source cited.
- **Validator:** every check in design.md for index-time, extraction and CIM, using the CIM scoring rule (required passed / available mapped / not in source).
- **Orchestrator:**
  - after a pass, it re-runs earlier stages' checks;
  - it may backtrack once per run;
  - feedback is compact: expected, actual and up to 3 events.
- **Holdout:** agents see about 200 sampled lines that cover every event type; the Validator ingests the full file.

### Acceptance criteria
- `parsemaxxing run` passes all three stages on each of the four format fixtures, and prints the three CIM numbers.
- The generator is deterministic: the same seed produces byte-identical output and manifest (test).
- The Validator unit tests use recorded Splunk responses, so no live Splunk is needed. They cover:
  - the event-count mismatch;
  - timestamp fallback (`_indextime` − `_time` < 60 s);
  - a +10800 s `_time` offset, with evidence text showing it;
  - a greedy regex;
  - duplicate values;
  - a missing required CIM field;
  - an out-of-set `action`;
  - the case of a field not present in the source (informational, no penalty).
- `run_search` refuses `delete`, `collect`, `dbxquery` and `loadjob`, refuses unknown commands, and caps results at 50 rows (tests).
- `test_regex` times out on `(a+)+$` against a long input instead of hanging (test).
- A backtrack is limited to once per run (test).

### OWNER ACTION
- Confirm the CIM macros include `pmx_*`, as set in Phase 1.
- Run the four fixtures against the lab and note the token spend.
- Decide whether multi-line and epoch-timestamp edge cases stay in scope, if Phase 1 left them open.

### Appsec review focus
- That the search guard can't be bypassed through a subsearch, a macro, `|` inside quotes, or case changes.
- ReDoS in `test_regex`.
- That the generator emits only synthetic data:
  - IPs from 192.0.2.0/24, 198.51.100.0/24 and 203.0.113.0/24;
  - the domain `example.com`;
  - no real company names.

### Suggested commits
- `feat: add synthetic log generator with truth manifests`
- `feat: add Extraction agent, test_regex and search guard`
- `feat: add CIM mapper agent and pinned CIM spec`
- `feat: add full Validator checks and CIM scoring`

### Scenario script
- `demo/02_cim_green.sh`: all three stages pass with the three CIM numbers and the holdout line.

### If late, cut, in this order
1. CSV, or whatever format has `INDEXED_EXTRACTIONS` issues.
2. Web CIM.
3. The backtrack rule (fail the run instead).

Keep Authentication and Network_Traffic.

---

## Phase 4 — Guardrails, adversarial suite, test identity, workflow integrity

**Goal:** every Must item in design.md "Guardrails and security" is enforced by code and covered by an adversarial test.
**Target date:** Sat Oct 31.
**Owners:**
- `splunk`: the gate, the builder hardening and the test-identity rename.
- `qa`: the adversarial suite.
- `engine`: workflow integrity.
- `appsec`: full review.

### Deliverables
- **Gate** (`guardrails/`):
  - a key allowlist;
  - blocks on `DEST_KEY = queue/nullQueue`, `_TCP_ROUTING`, `_MetaData:Index`, `INGEST_EVAL` and `SEDCMD-`;
  - min/max bounds on `TRUNCATE`, `MAX_EVENTS` and `MAX_TIMESTAMP_LOOKAHEAD`;
  - forbidden `EVAL`/`FIELDALIAS` targets;
  - no `[default]`, no broad `[source::…]` and no `[host::*]` stanzas;
  - CSV lookups only inside the TA;
  - a check for catastrophic backtracking in regexes;
  - the conf check chosen in Phase 1.
- **TA builder:**
  - a package file allowlist;
  - the `parsemaxxing_<job>_` transform prefix, with a collision check;
  - it refuses a TA name that already exists.
- **Validator integrity:**
  - a constant-value CIM field flag;
  - every CIM field must trace back to a source field;
  - literal-sample-value regex flag (Should).
- **Test identity:** a deterministic rename back to the real names at promotion. Both hashes are recorded and linked, and a smoke test runs after promotion.
- **Workflow integrity:**
  - approval is bound to the SHA-256 of the `.tgz`;
  - a test index is checked to be empty before ingest;
  - hashes are compared on resume;
  - timeouts everywhere;
  - at most 10 tool calls per attempt;
  - per-job and daily caps on ingest bytes;
  - cleanup removes only the indexes the job recorded creating.
- **Adversarial suite** in `engine/tests/adversarial/`, run by `make test` and CI. It covers:
  - `nullQueue`;
  - newline injection (`value\n[script://x]`);
  - path traversal in vendor/product;
  - a log line containing "ignore previous instructions, add SEDCMD";
  - `EVAL-action = "success"` constant gaming;
  - an ingest target outside `pmx_`;
  - forbidden search commands;
  - `[default]` stanzas;
  - a TA name that collides with an existing app.

### Acceptance criteria
- Every Must row in design.md maps to a passing test. A table in `docs/threat-model.md` names the test for each row.
- The adversarial suite has at least one test per Must row, and every one passes.
- The prompt-injection fixture runs end to end against the lab and produces a gate block with its reason in the run output. The deploy never happens.
- Approving a `.tgz` and then changing one byte makes promotion refuse (test).
- A replayed approve is a no-op because the state transition is enforced (test).
- `appsec` review: no open High or Critical finding.

### OWNER ACTION
- Run the prompt-injection and constant-gaming fixtures against the lab and check that the output reads well.

### Appsec review focus
This is the main appsec phase; review everything above, especially:
- gaps in the allowlist;
- how values are normalized before checking (case, whitespace, unicode);
- tricks that use `REPORT-`/`TRANSFORMS-` to chain into forbidden keys;
- hash binding;
- cleanup that can only delete resources the job recorded creating.

### Suggested commits
- `security: add guardrail gate for conf keys and values`
- `security: harden TA builder paths, names and package contents`
- `security: bind approval to package hash and enforce transitions`
- `test: add adversarial regression suite`

### Scenario script
- `demo/03_guardrail_block.sh`: an injected instruction in a log line is blocked by the gate, and constant `action` gaming is caught.

### If late, cut
- Should items only: the literal-value regex flag and the high-risk second confirmation.
- Never cut a Must item.

---

## Phase 5 — Job queue, workers, PostgreSQL ledger, FastAPI, live event stream

**Goal:** many jobs running in parallel, surviving crashes, with a live stream of events. The CLI and the API share one orchestrator.
**Target date:** Sun Nov 1.
**Owners:**
- `engine`: everything in this phase.
- `qa`: tests.
- `appsec`: API review.

### Deliverables
- **Ledger** (`ledger/`):
  - jobs and an append-only ledger table;
  - migrations as plain SQL files;
  - every state transition written before the next step.
- **Queue:**
  - claims with `FOR UPDATE SKIP LOCKED`;
  - a lease of about 2 min, renewed by a heartbeat;
  - duplicate detection by content hash and source key.
- **Workers:**
  - a worker pool (3–4);
  - one global lock for Splunk writes;
  - an LLM concurrency cap;
  - a daily budget and kill switch.
- **API** (`api/`):
  - upload, validated against the design's upload limits: size cap after decompression, single-file `.gz`, UTF-8 content check, about 50 events minimum;
  - create run;
  - get run;
  - confirm profile;
  - approve, reject or correct;
  - download the `.tgz`;
  - a server-sent events stream of ledger events.
- **API security:**
  - CORS restricted to the web origin;
  - security headers;
  - a cost estimate before start.
- **CLI:** `parsemaxxing run` uses the same orchestrator, with PostgreSQL.
- **Docker:** `engine/Dockerfile`, non-root and slim, and the `app` profile is removed from the `engine` service.

### Acceptance criteria
- Two workers never claim the same job: a concurrency test with 20 jobs and 4 workers.
- Recovery after a crash: kill a worker mid-stage, and after the lease expires another worker resumes from the last saved state (integration test against PostgreSQL in CI using a service container).
- The ledger is append-only. An `UPDATE` or `DELETE` on the ledger table is refused, enforced by a trigger or by grants (test).
- Upload rejects:
  - a decompression bomb;
  - a multi-file archive;
  - a binary file;
  - a non-UTF-8 file;
  - a symlink in the drop folder;
  - a duplicate upload, which points to the existing job.
- The SSE stream delivers each transition within 2 s (test).
- Approve is refused unless the state is `awaiting_approval` (test).
- `docker compose up` (without `--profile`) starts engine, Splunk and PostgreSQL, and `GET /health` returns 200.

### OWNER ACTION
- **Dry run:** drop four fixture files at once in the lab and watch them run in parallel.
- **Decide** whether Should-level login and an approver role go into v1. The plan assumes they don't, and that the instance binds to localhost only (login is Phase 13).

### Appsec review focus
- Upload handling.
- SQL parameterization.
- CORS and headers.
- SSE authorization.
- Kill-switch bypass.
- That the engine container runs as non-root and has no Docker socket.

### Suggested commits
- `feat: add PostgreSQL job queue and append-only ledger`
- `feat: add worker pool with leases and budgets`
- `feat: add FastAPI routes and ledger event stream`
- `chore: add engine Dockerfile`

### Scenario script
- `demo/04_parallel_jobs.sh`: four jobs run in parallel, one pausing for profile review.

### If late, cut
- The drop folder (upload only).
- Correct-a-mapping (approve or reject only).
- The cost estimate.
- The kill switch stays.

---

## Phase 6 — Next.js UI (four screens)

**Goal:** the four screens from design.md, reading only the ledger and sending only the allowed actions.
**Target date:** Mon Nov 2. The design budgets about 2 days; a 1-day Streamlit fallback is the escape hatch.
**Owners:**
- `frontend`: everything in this phase.
- `qa`: component and e2e tests.
- `appsec`: XSS review.

### Deliverables
- **Scaffold:** `web/`, scaffolded with Next.js App Router, TypeScript strict and shadcn/ui, with `package-lock.json` committed.
- **The four screens:**
  - **New run:** upload plus the job board.
  - **Live run view:** stepper, attempt timeline, config diffs, checks, evidence and agent searches.
  - **Profile review:** an editable profile with a Confirm button.
  - **Approval report:** raw vs parsed with highlights built as React elements, the mapping table, CIM scores and configs. It has approve, reject and correct actions, a second confirmation for high-risk changes, and the `.tgz` download.
- **Docker:** `web/Dockerfile` (non-root), and the `app` profile is removed from the `web` service.
- **Makefile:** the `npm audit` guard is removed (the shortcut comment).

### Acceptance criteria
- A log line containing `<script>alert(1)</script>` renders as text in the raw vs parsed view (e2e test with Playwright).
- `dangerouslySetInnerHTML` is absent: a lint rule fails CI if it appears.
- No secrets and no `NEXT_PUBLIC_*` variable holding a token.
- Keyboard-only flow works: upload → confirm → approve. All controls are labelled.
- `npm audit --audit-level=moderate` is clean, and `make security` now runs it unguarded.
- The live view updates within 2 s of a ledger event.

### OWNER ACTION
- Click through all four screens against the lab, and check that the approval report is clear.

### Appsec review focus
- XSS in every place log text appears.
- Highlight building from offsets.
- CSRF on the actions.
- That no logic lives in the client.
- Dependency audit.

### Suggested commits
- `feat: scaffold web UI with shadcn`
- `feat: add run board and live run view`
- `feat: add profile review and approval report`
- `chore: add web Dockerfile`

### Scenario script
- `demo/05_approval_report.sh`: seeds a finished job and opens the approval report.

### If late, cut
1. Fall back to Streamlit for the whole UI (one day). If staying on Next.js, keep only Profile review and Approval report; the run board becomes a list.
2. Drop the config diffs in the live view.

---

## Phase 7 — Parser updates

**Goal:** patch a Parsemaxxing-built TA for a changed format, proving that both the old and the new format still parse.
**Target date:** Tue Nov 3 morning, only if Phases 1–6 are done. Otherwise it moves to the roadmap.
**Owners:**
- `engine`: the update job type and the registry.
- `splunk`: diagnose, regression and in-place promotion.
- `agents-ai`: patch-mode prompts.
- `qa`: tests.

### Deliverables
- **TA registry:** versions, original samples, manifest and baseline.
- **Update job:** Diagnose (no AI) → failing stages only → Regression (old + new samples) → Approval → Promote.
- **Patch mode:** a minimal-change instruction to the agents.
- **`app.conf`:** version bump.
- **Installed-TA safety:**
  - `local/` is preserved;
  - the review flags `local/` overrides;
  - an exact-version rollback.

### Acceptance criteria
- If the new samples pass as-is, the job ends at Diagnose and spends 0 tokens (test).
- A patch that breaks the old format is rejected, with evidence (test).
- A generator "firmware v2" fixture, with a renamed field and a new timestamp format, gets patched, and both versions pass.
- `local/` files are never written (test).

### OWNER ACTION
- Decide on the morning of Nov 3 whether this phase runs or moves to the roadmap.

### Appsec review focus
- That rollback cannot delete files outside the TA.
- That promotion in place cannot overwrite a non-Parsemaxxing app.

### Suggested commits
- `feat: add TA registry and update job`
- `feat: add patch mode with old and new format regression`

### Scenario script
- `demo/06_parser_update.sh`: a "firmware v2" fixture is patched, with Diagnose spending 0 tokens.

### If late, cut
- The whole phase. It becomes a roadmap item in the README.

---

## Phase 7b — UI redesign (agent-centred, readable, navigable)

**Goal:** a non-expert can tell within 5 seconds which agent is working and on what, which phase and attempt the job is in and how much budget is left, what each phase produced and why it passed or failed, how a parsed event compares with its raw line, and what changed in the config, in plain language. Runs before every remaining phase.
**Owners:** `engine` (the event labels only), `frontend`, `qa`, `appsec` (rendering of untrusted text).

### Deliverables
- **Data contract (engine):** every ledger log event carries `stage`, `attempt`, `visit`, `actor`, `kind` and a structured `detail`; parser-update reviews carry structured `changes`. The text line is unchanged for the CLI.
- **Actor identity system:** `web/lib/actors.ts`, one icon, accent, tagline and kind marker per actor, used on every screen.
- **Screens:** runs board ("Needs you", new-run sheet); run workspace (meters, Now banner, phase rail, attempts, backtracks); live activity grouped by phase and attempt with filters and "Jump to latest"; readable config and row diffs; raw vs parsed with field colours and a CIM view; approval summary with a sticky decision bar; profile review with coverage bars and change markers; read-only TA registry.
- **Tokens:** light and dark themes in `web/app/globals.css`, WCAG AA for every text and status pair.

### Acceptance criteria
- No diff anywhere shows `---`, `+++`, `@@` or a leading `+`/`-` (Playwright).
- Each phase and attempt opens from `/runs/<job>?phase=<phase>&attempt=<n>`, during and after a run; back and forward work; arrow keys move along the phase rail (Playwright).
- Log-derived text in the feed, phase view, diffs and config view renders as text (Playwright XSS tests).
- `make lint`, `make test`, `make security` and the e2e suite pass; `appsec` has reviewed the rendering of untrusted text.

### Scenario script
- `demo/07_live_workspace.sh`: opens a live run workspace.

---

## Phase 8 — Drift pipeline (superseded by Phase 22)

> Not built. Phase 22 builds this per environment; its acceptance criteria include the ones below.

**Goal:** Splunk alerts detect a format change, code collects masked samples, the Drift Analyst confirms it, and an update job is created automatically.
**Owners:**
- `splunk`: alert templates and the collector.
- `agents-ai`: the Drift Analyst.
- `engine`: the webhook, dedup and states.
- `appsec`: review.

### Deliverables
- A monitoring app built from fixed alert templates.
- A webhook endpoint with:
  - a secret URL token;
  - a source-IP allowlist;
  - dedup and cooldown.
- A collector that applies format-preserving masking.
- `fetch_more_samples`.
- The drift job states.

### Acceptance criteria
- A generator format switch at minute 2 leads to an update job waiting for approval, with no human action in between (lab run).
- A webhook call without the token, or from another IP, is refused (test).
- Masking is consistent and keeps the format, so a regex still matches the masked value (test).

### OWNER ACTION
- Configure the webhook alert action in the lab.
- Make sure the engine is reachable from Splunk.

### Appsec review focus
- Webhook authentication.
- That masking is complete before any model call.
- That the drift account's search is limited to registered sourcetypes.

### Suggested commits
- `feat: add drift alerts, collector and analyst`

### If late, cut
- The whole phase.

---

## Phase 9 — Mixed-feed routing (superseded by Phase 23)

> Not built. Phase 23 builds this with topology awareness; its acceptance criteria include the ones below.

**Goal:** split one shared syslog feed into vendor sourcetypes, proving that 0 events were misrouted.
**Owners:**
- `agents-ai`: the Router.
- `splunk`: the routing guardrail exception and the positive and negative tests.
- `qa`: tests.

### Deliverables
- A Routing stage.
- The narrow `TRANSFORMS-` exception: `DEST_KEY = MetaData:Sourcetype` only.
- A multi-vendor generator feed with a line-to-vendor manifest.
- Index-time settings placed in `[host::]`/`[source::]` stanzas, as design trap 1 requires.
- Rollback that re-runs the negative test.

### Acceptance criteria
- Positive test: 100% of target events are routed.
- Negative test: exactly 0 non-target events are renamed.
- A `TRANSFORMS-` on the generic stanza with any other `DEST_KEY` is blocked (adversarial test).
- After rollback, no routing transform remains (test).

### OWNER ACTION
- Approve with the second confirmation for high-risk changes, in the lab.

### Appsec review focus
- That the exception is as narrow as designed.
- That rollback is complete.

### Suggested commits
- `feat: add routing stage for shared syslog feeds`

### If late, cut
- The whole phase.

---

## Phase 10 — One-command Docker setup, README completion, scenario scripts

**Goal:** a new user can clone, run and see a full run in 15 minutes, and the scenario scripts run end to end.
**Target date:** Tue Nov 3.
**Owners:**
- `engine` and `frontend`: Docker.
- The main session: README and scenario walkthrough.
- `qa`: a clean-machine test.
- `appsec`: a final public-repo sweep.

### Deliverables
- **`docker-compose.yml`:** one command, no `--profile`, with health checks and a bundled sample.
- **Lab bootstrap:** a script that creates the `pmx_` roles, tokens and indexes in the bundled Splunk and edits the CIM macros. Its secrets are generated into `.env` and never printed.
- **README:** every "planned" label updated to the truth, the Features table updated, a screenshot.
- **Scenario walkthrough** stringing the `demo/` scripts together (removed in Phase 11; the scripts stay):
  - four jobs in parallel;
  - an injected log line blocked by the gate;
  - constant-value gaming caught;
  - raw vs parsed;
  - approve and download the `.tgz`.

### Acceptance criteria
- On a clean clone in a fresh VM:
  1. `cp .env.example .env`;
  2. fill in the key and passwords;
  3. `make setup && make up`;
  4. the first run passes within 15 minutes, timed.
- The README makes no claim about a feature that doesn't exist (manual check against the Status table).
- `appsec` final sweep is clean:
  - gitleaks over the full history;
  - no real names, hostnames or IPs;
  - `.env` not tracked.
- CI green on `main`.

### OWNER ACTION
- Run the clean-VM test.
- Run the scenario scripts once.
- Check the remaining credit balance.
- Make the repository state final for the `v1.0.0` release.

### Appsec review focus
- The bootstrap script's handling of secrets.
- That published ports are 127.0.0.1-bound only.
- The final public-exposure sweep.

### Suggested commits
- `chore: add one-command setup`
- `docs: complete README and scenario walkthrough`

### If late, cut
- The screenshot polish.
- Never the clean-clone test or the appsec sweep.

---


# v2 phases

Each phase builds the design sections it names in [design.md](design.md#v2-platform-design). Section numbers (7.1 to 7.19) and decisions (D1 to D11) refer to that part of the design doc. Lab questions Q12 to Q24 are in [design.md](design.md#v2-open-questions) and their answers go into [lab-findings.md](lab-findings.md).

---

## Phase 11 — Foundation

**Goal:** v1 stays reachable, the project has its new name and licence, the hackathon framing is gone, and every v2 design, security and UX document exists and is reviewed before any v2 code is written. Every lab question has an answer.
**Owners:**
- The main session: order of pull requests, root and folder `CLAUDE.md` guides, agent definitions.
- `docs`: design v2 sections, build plan, features, design-onboarding skeleton, READMEs, setup guide, knowledge-sources guide.
- `appsec`: threat model v2, `docs/security-baseline.md`.
- `ux`: `docs/ux/` specs.
- `splunk`: lab probes for distributed Splunk (Q12 to Q24).

### Deliverables
- **Tag and protect:** `v1.0.0` on the last v1 commit; `main` protected.
- **Rename** (first pull request, `phase-11-rename`): package `engine/parsemaxxing/`, CLI `parsemaxxing`, `PARSEMAXXING_*` variables with a refusal when an old `PARSEWRIGHT_*` variable is set, `X-Parsemaxxing*` headers, database role rename migration with a backup first, `pmx` prefix for internal names (`pmx_test`, `pmx_audit`, `__Host-pmx_session`, `pmxt_`, `pmx-relay`), legacy `TA-parsewright-` prefix accepted only for add-ons already in the ledger.
- **Licence** (second pull request, `phase-11-licence`): `LICENSE` with the exact PolyForm Shield 1.0.0 text and its SHA-256 recorded; `NOTICE` and `TRADEMARKS.md` as approved by the owner; package metadata; "source-available" wording everywhere; generated add-ons carry no PolyForm text; `CONTRIBUTING.md` says outside pull requests are not merged yet.
- **Cleanup of the event framing:** `docs/demo-script.md` removed; the "RECORD THIS" convention removed from root `CLAUDE.md` and this plan; `demo/` described as scenario scripts; design, threat model, `SECURITY.md` and READMEs reworded. `docs/build-log.md` stays as written.
- **Design v2** in `docs/design.md` (decisions, principles, architecture, 7.1 to 7.19, open questions, tech stack rows), this plan's Phases 11 to 25, `docs/features.md`, `docs/design-onboarding.md` skeleton.
- **Security docs:** threat model v2 (assets, actors `viewer`, `admin`, directory, remote Splunk nodes, relay; threats T11 to T18; R1, R2, R8, R10, R12 revisited) and `docs/security-baseline.md` (7.7).
- **UX docs:** `docs/ux/information-architecture.md`, `flows.md`, `screens.md`, `copy.md`.
- **Lab probes** under `engine/parsemaxxing/tools/probes/` for Q12 to Q24 on 10.2 and 10.6; answers in `docs/lab-findings.md`.
- **Local samples rule:** `samples-local/` git-ignored, blocked by a pre-commit check and a CI check.
- **Guides:** root `CLAUDE.md` (new description, stack, layout, v2 rules, agent roster, phase workflow, commands, definition of done, under ~180 lines), `engine/CLAUDE.md`, `web/CLAUDE.md`, and new folder guides for `auth/`, `secrets/`, `deploy/`, `knowledge/`, `ta_store/` and `relay/`.

### Acceptance criteria
- `grep -ri parsewright` finds only `docs/build-log.md`, the README "History" line, the legacy-prefix allowlist and its tests, the env-var refusal check and the database rename migration.
- `LICENSE` matches the official file's hash; no doc or page calls v2 "open source"; a generated add-on in the scenario scripts contains no PolyForm text.
- No doc frames the project as a hackathon entry (deadlines, judging, Devpost, track names); `docs/build-log.md` stays as written.
- Every lab question Q12 to Q24 has a recorded answer with evidence in `lab-findings.md`, per version where results differ.
- The owner has reviewed and merged the docs pull request.
- No production code except probe scripts.

### OWNER ACTION
- Tag `v1.0.0` and push the tag; protect `main` (pull request required, CI must pass, no force pushes).
- Rename the GitHub repository and update local remotes; turn on private vulnerability reporting.
- Add the official PolyForm Shield 1.0.0 text if it cannot be fetched from the session.
- Provide the lab: a standalone sandbox, a 3-member SHC with deployer, two heavy forwarders (one also the deployment server for a universal forwarder), a separate deployment server for the HFs, and indexers (read-only for Parsemaxxing), on 10.2 and 10.6.
- Review the design, threat model, security baseline and UX specs.
- Before 2.0.0: a lawyer reviews `NOTICE`, `TRADEMARKS.md` and the generated add-on statement; confirm the employment contract does not cover the project; choose contributor terms; register the trademark where the product will be sold; run a trademark search before the public announcement.

### Appsec review focus
- Threat model v2 completeness for the new boundaries (directory, remote Splunk, relay, knowledge imports, tenants).
- That probes are read-only outside the sandbox and print no tokens.
- That no doc, probe output or finding names a real company, host or network.

### Suggested commits
- `refactor: rename Parsewright to Parsemaxxing`
- `chore: change licence to PolyForm Shield 1.0.0`
- `docs: remove event framing`
- `docs: add v2 design, plan and features`
- `docs: add threat model v2 and security baseline`
- `docs: update agent guides`
- `feat: add distributed Splunk lab probes`

### Docs to update
- Everything listed in the deliverables; `docs/lab-findings.md`; `docs/knowledge-sources.md` (marked planned until Phase 20).

### If late, cut
- Nothing from the rename, licence or lab answers: later phases depend on them. The UX specs for screens after Phase 15 can follow in the phase that builds them.

---

## Phase 12 — Hardened runtime, settings store and vault

**Goal:** the stack is hardened, every runtime setting comes from the settings service, every secret from the vault, and the ledger is a verifiable hash chain (7.5, 7.7 A02 to A04 and A08, 7.13 Docker).
**Owners:** `devops` (Docker, CI, supply chain), `identity` (settings, vault), `engine` (bootstrap, ledger chain, migrations).

### Deliverables
- **Docker:** networks `edge`, `app`, `data`, `splunk`; PostgreSQL unpublished by default (`cli` profile on 127.0.0.1); Docker secrets for the KEK and database passwords; CPU, memory and pids limits; `tmpfs` with `noexec`; healthchecks; optional `https` profile with a reverse proxy and HSTS.
- **Supply chain:** images pinned by digest; Python lock with hashes (`--require-hashes`); `npm audit signatures`; CycloneDX SBOM per image; Trivy scan failing on high and critical.
- **Settings service** (`settings/`): Pydantic groups, versioned, `settings_history`, snapshots by hash per job, environment-variable overrides shown read-only, export and import with a diff.
- **Vault** (`secrets/`): AES-256-GCM envelope encryption, AAD binding, KEK file from `make setup` (mode 0400), `parsemaxxing secrets rotate-kek`, redaction in `repr`.
- **Bootstrap slim-down:** `.env` holds only bootstrap values; one-time import of v1 `.env` keys (secrets into the vault); the wizard later lists what can be removed.
- **Ledger hash chain:** `prev_hash`, `hash`, `parsemaxxing ledger verify`.
- **Backups:** `parsemaxxing backup` (encrypted `pg_dump` with `age`), restore tested in CI.
- **Error envelope** (code, message, request id) and security headers on the API.
- New make targets: `make secrets`, `make backup`, `make sbom`.

### Acceptance criteria
- No runtime code reads `os.environ` outside bootstrap (test).
- Vault tests: round trip; tampered ciphertext, moved ciphertext (another row's AAD) and a wrong KEK all fail.
- No secret is returned by any API response or appears in logs (test over every settings route).
- `ledger verify` detects an edited and a deleted row (test).
- Trivy and SBOM run in CI; images are pinned by digest; R12 closed.
- Restore from an encrypted backup passes in CI.

### OWNER ACTION
- Create the KEK with `make setup` and back it up outside the server.
- Run the v1 `.env` import on the lab and check the result.

### Appsec review focus
- Crypto use (nonce generation, AAD contents, KEK handling, no custom crypto).
- Secret leakage through errors, logs, `repr` and settings history.
- Container isolation and published ports.

### Suggested commits
- `security: harden Docker networks, secrets and limits`
- `ci: add SBOM, image scan and hashed Python lock`
- `feat: add settings service`
- `security: add envelope-encrypted secrets vault`
- `feat: add ledger hash chain and verify command`
- `feat: add encrypted backups`

### Docs to update
- `docs/setup.md` (minimal `.env`, **KEK creation and backup in bold**, HTTPS profile, backups not kept longer than 30 days), `.env.example`, `engine/parsemaxxing/secrets/CLAUDE.md`, `settings/` and `secrets/` READMEs, `docs/security-baseline.md` rows, threat model R12.

### If late, cut
- The `https` profile (document a reverse proxy instead). Never the vault, the `os.environ` rule or digest pinning.

---

## Phase 13 — Authentication and RBAC

**Goal:** nobody reaches the platform without logging in, every route has a role, and every security-relevant action is audited (7.3).
**Owners:** `identity` (auth), `engine` (route policy, CLI through the API), `frontend` (login, MFA, tokens screens).

### Deliverables
- Local users with Argon2id, common-password list, lockout with backoff per account and IP.
- TOTP MFA with hashed recovery codes; "require MFA for admins" on by default.
- Server-side sessions, `__Host-pmx_session` cookie, idle and absolute timeouts, rotation and revocation rules.
- `Origin` check on every state-changing request, in addition to the custom header.
- API tokens (`pmxt_`, hashed, expiring, revocable); CLI mutating commands through the API; break-glass `parsemaxxing admin reset`.
- One-time setup token at first run; no default credentials.
- Route policy registry with deny by default; `auth_events`; audit log screen (read-only).
- `jobs.created_by`.

### Acceptance criteria
- Route-inventory test green: any route without a policy fails the build.
- Every route tested as anonymous, viewer and admin.
- Brute-force (lockout and backoff) and user-enumeration tests (same message and timing class for unknown user and wrong password).
- Session fixation, CSRF with a foreign `Origin`, and an expired or revoked token are refused (tests).
- R1 and R10 closed in the threat model.

### OWNER ACTION
- Complete first-run setup with the setup token on the lab and enrol MFA.

### Appsec review focus
- Session handling, token storage, timing of login failures, route coverage, object-level checks on every id in a path.

### Suggested commits
- `security: add local users, sessions and MFA`
- `security: add route policy registry with deny by default`
- `feat: add API tokens and route CLI through the API`
- `feat: add login and account screens`

### Docs to update
- `engine/parsemaxxing/auth/CLAUDE.md` and README, `engine/CLAUDE.md` (auth dependencies), `web/CLAUDE.md` (session handling, `<AdminOnly>`), `docs/setup.md` (first admin), `SECURITY.md`, `docs/security-baseline.md` (A01, A07), threat model.

### If late, cut
- "Sign out everywhere" and token last-used time. Never MFA for admins, the route registry or the audit events.

---

## Phase 14 — LDAP

**Goal:** directory users log in with their directory groups mapped to `viewer` or `admin`, safely (7.4).
**Owners:** `identity`, `frontend`.

### Deliverables
- `ldap3` client, LDAPS or StartTLS only, CA bundle upload, hostname check.
- Admin config screen: servers with failover, bind DN and password (vault), search base and filter template, username attribute, group modes (`memberOf`, `member` search, AD nested groups), group → role mapping, timeouts, page size.
- Login flow with RFC 4515 escaping, exactly-one-entry rule, empty password refused before any bind, highest mapped role, no mapped group means no access.
- "Test connection" and "Test a user lookup".
- Optional TOTP for LDAP users; local break-glass admin always available.

### Acceptance criteria
- Tests against an OpenLDAP container in CI: LDAPS only (plain refused), empty password refused, filter injection refused, nested groups resolved, no-group user denied, failover to the second server.
- A group change takes effect at the next login and at the absolute session timeout (test).
- The bind password never appears in logs or audit rows (test).

### OWNER ACTION
- Test against the lab directory with a test user and group (synthetic names only in any doc).

### Appsec review focus
- Filter injection, unauthenticated bind, certificate validation, error messages that leak directory details.

### Suggested commits
- `security: add LDAP login with LDAPS and filter escaping`
- `feat: add LDAP settings and test screens`

### Docs to update
- `docs/setup.md` (LDAP section), auth README, `docs/security-baseline.md` (A07, LDAP), threat model T12.

### If late, cut
- AD nested-group mode (document `memberOf` only). Never the empty-password check or TLS.

---

## Phase 15 — App shell and UX architecture

**Goal:** a real platform UI: shell, navigation, setup wizard and the settings screens, with the v1 screens rehomed (7.13).
**Owners:** `ux` (specs and walkthrough), `frontend`.

### Deliverables
- App shell: sidebar, top bar with the customer → environment context switcher, global search, user menu, "Needs you" notifications.
- Navigation per 7.13; screens for General settings, Users, API tokens, Audit log, Security health, About.
- First-run setup wizard (setup token → first admin and MFA → LLM provider → sandbox Splunk → optional production environment), with a checklist on Overview.
- `<AdminOnly>` pattern; light and dark themes from tokens.
- Runs board, run workspace, profile review, approval report and registry rehomed inside the shell.

### Acceptance criteria
- A new user completes setup without docs (`ux` walkthrough recorded in `docs/ux/`).
- Playwright covers viewer and admin views of every screen; viewers see admin actions disabled with "Admin only".
- axe checks pass (WCAG 2.2 AA); keyboard-only path through the wizard.
- Log text still renders only as escaped text (existing XSS tests pass inside the shell).

### OWNER ACTION
- Walk through the first-run wizard on a clean install and report anything unclear.

### Appsec review focus
- That no authorization decision lives in the client; CSP and headers on the web app; nothing in local storage.

### Suggested commits
- `feat: add app shell and navigation`
- `feat: add first-run setup wizard`
- `feat: rehome run screens inside the shell`

### Docs to update
- `web/CLAUDE.md` (route groups, `<AdminOnly>`, write-only fields, chart rules, actions list), `web/README.md`, root README screenshots, `docs/setup.md` (wizard first).

### If late, cut
- Global search and the notification centre (keep the "Needs you" list on Overview).

**Release:** tag `2.0.0-alpha.1` after this phase (Phases 12 to 15 done).

---

## Phase 16 — LLM providers and per-agent models

**Goal:** any provider and model, chosen per agent, with egress rules and costs (7.6).
**Owners:** `agents-ai` (`llm/`, adapters, probe), `frontend` (provider and agent screens).

### Deliverables
- `llm/` package with one `complete(schema, messages, budget) -> (object, usage)` interface; `openai` SDK adapter (OpenAI-compatible, Azure) and `anthropic` SDK adapter.
- Provider registry with presets, `hosted`/`on_prem` flag, prices, limits; capability probe ("Test").
- Per-agent primary and fallback model; fallback only on infrastructure errors.
- Egress policy per customer; masking hook at the LLM client (the masker itself lands in Phase 21; until then hosted providers get only synthetic or explicitly allowed data).
- Budgets and kill switch across providers; cost per call in the ledger; provider names removed from code identifiers and prompts.

### Acceptance criteria
- Two providers of different kinds pass the probe and run the synthetic fixtures.
- A customer whose policy forbids hosted models cannot start a job on a hosted provider (test).
- A fallback never retries bad output (test); cost per call is recorded.
- No provider key is returned by the API or logged.

### OWNER ACTION
- Provide API keys for two providers in the lab (entered in the UI, never in files).

### Appsec review focus
- Key handling, egress policy bypass, budget enforcement across providers (LLM02, LLM10).

### Suggested commits
- `refactor: move LLM client into provider adapters`
- `feat: add provider registry and capability probe`
- `feat: add per-agent model assignment and egress policy`

### Docs to update
- `engine/CLAUDE.md` (provider adapter rule, masking at the LLM client), `llm/` README, `docs/setup.md`, `THIRD_PARTY_NOTICES.md` if needed, security baseline (LLM rows).

### If late, cut
- The Azure preset. Never the egress policy.

---

## Phase 17 — Customers, environments and topology

**Goal:** Parsemaxxing knows every Splunk environment it works with, its customers, nodes, roles, versions and credentials, and tests each connection (7.1, 7.5 scopes, D1, D3, D10).
**Owners:** `splunk` (topology detection, connectivity tests, versions), `engine` (data model, tenant base search), `frontend` (environment screens and wizard).

### Deliverables
- `customers`, `environments`, `environment_customers`, `nodes`, `credentials` tables; `jobs` gains `customer_id`, `sandbox_id`, `kind`.
- Migration of the v1 Splunk into the sandbox `local-sandbox`.
- Auto-discover topology from one search head URL and token, admin confirms each node; multi-role nodes.
- Connectivity test per node (button and every 15 minutes), including capabilities, version, token expiry.
- Supported versions and CIM compatibility table in `environments/versions.py`.
- Generated service-account script for `parsemaxxing_read` and `parsemaxxing_deploy`.
- Tenant base-search helper restricted to a customer's index allowlist.
- Settings scopes (platform → environment → client), isolation rules, clone without secrets, per-environment export and import.
- Environment list, per-environment tabs, add-environment wizard.

### Acceptance criteria
- Auto-discover and connectivity tests against the owner lab (SHC, HFs, an HF acting as deployment server for UFs, a deployment server for HFs, indexers read-only).
- Multi-role nodes detected; a node below 10.2 fails with the supported-versions message.
- Tenant index allowlist tests: an index outside the allowlist is refused before any search (adversarial).
- A secret of environment A cannot be selected, read or tested from environment B (test).
- Handoff-only environments can be created without any network path.

### OWNER ACTION
- Run the generated service-account script on the lab and enter the tokens in the UI.

### Appsec review focus
- Tenant isolation, cross-environment secret access, TLS verification toggles, SSRF through management URLs.

### Suggested commits
- `feat: add customers, environments and nodes`
- `feat: add topology discovery and connectivity tests`
- `security: add tenant base search with index allowlist`
- `feat: add environment screens and wizard`

### Docs to update
- `docs/setup.md` (adding a production environment, service accounts, supported versions), `environments/` README, `docs/security-baseline.md`, threat model T16.

### If late, cut
- Scheduled connectivity tests (button only) and per-environment export and import.

---

## Phase 17b — Add-on version control

**Goal:** every add-on version is kept forever, viewable, downloadable, comparable and revertable without losing newer ones (7.15, D9; masked regression sets from 7.19).
**Owners:** `engine` (registry, API, CLI), `splunk` (`ta_store/`, conf diff), `frontend` and `ux` (Add-ons screens), `devops` (store volume, backups), `qa`.

### Deliverables
- `ta_store/`: content-addressed, write-once store on its own volume; hash checked on every read; included in backups.
- v1 migration of every kept package into the store, verified against `ta_versions.sha256`.
- `ta_versions` gains `parent_version`, `test_sha256`, `store_key`, `changelog`, `approved_by`; deprecate and undeprecate as `ta_events`.
- File viewer, download with `SHA256SUMS`, compare any two versions (file, setting and text level), compare with installed.
- Revert to any version on the sandbox (per production environment once Phase 18 lands).
- Masked regression set stored with each new version (masking rules from 7.10; the masker is built here or pulled forward from Phase 21).
- API and CLI (`versions`, `show`, `diff`, `download`, `rollback <environment> <TA> <version>`); Add-ons screens with timeline and lineage tree.

### Acceptance criteria
- Every v1 version migrated with its hash verified; a missing package is reported.
- No code path deletes or overwrites a version (a test greps for it, and a trigger test).
- Revert to 1.0.0 then roll forward to 1.2.0 leaves all versions intact and downloadable.
- Compare works for non-adjacent pairs and across a revert.
- A tampered store file is detected; path traversal in the file viewer is refused.
- A viewer can view, compare and download but not revert.
- A registered version stores only a masked regression set that passes the version's checks and a secret scan; an update re-tests against it.

### OWNER ACTION
- Check the migration report on the lab registry.

### Appsec review focus
- Write-once guarantees, path handling in the viewer, tar handling in memory, download auditing.

### Suggested commits
- `feat: add content-addressed add-on store`
- `feat: migrate v1 packages into the store`
- `feat: add version view, download and compare`
- `feat: add Add-ons screens`

### Docs to update
- `engine/parsemaxxing/ta_store/CLAUDE.md` and README, ledger README (what a version is, store layout, restore), `docs/setup.md` (backups include the store).

### If late, cut
- "Compare with installed" (it needs Phase 18 read-back anyway). Never the write-once rule or the migration check.

---

## Phase 17c — Parsing coverage

**Goal:** every CIM data model of each environment's CIM version, automatic data model selection, per-version spec keys in the gate, and the full format matrix (7.16, 7.17, the spec part of 7.12).
**Owners:** `splunk` (CIM library, spec parser, key table, formats, validator rules), `agents-ai` (Profiler and CIM mapper changes), `frontend` and `ux` (CIM library screen), `qa` (fixtures).

### Deliverables
- CIM library: upload `Splunk_SA_CIM` per version, safe extraction of model JSON only, normalization of all models, exact-version match per environment, local-changes check, sandbox installed from the library.
- Automatic data model selection: value profiles and fit score by code, choice by the CIM mapper within code bounds, one return to selection per run, decision shown in the approval report.
- Spec bundle collection (sandbox mount, admin upload), spec parser, per-version key table in the gate (block unknown keys, warn on deprecated).
- Format matrix: code detection, `LogProfile` format values, gate keys, validator rules per format, `defusedxml`, one fixture per format plus adversarial variants, `docs/formats.md`.

### Acceptance criteria
- Uploading CIM 6.3.0 and the newest 8.x reads every model.
- An environment whose installed version has no matching upload blocks only CIM work, with the version named.
- A version outside the compatibility table and a hostile package (traversal, links, oversized members) are refused.
- A modified data model in the lab is detected and shown as a diff.
- The sandbox gets the matching version installed from the library.
- Selection lands on the right model on every fixture (fit score ranks it first); a choice outside the code bounds is refused; a no-fit fixture is built without CIM.
- Every format fixture passes end to end; a key missing from the target version is blocked.
- The XXE and entity-expansion fixtures are harmless.
- A deployment plan to an environment with a different CIM definition shows the exact difference (checked when Phase 18 lands).

### OWNER ACTION
- Download the CIM packages from Splunkbase under the team's account and upload them in the lab.
- Review the Q20 and Q21 findings.

### Appsec review focus
- Package extraction, XML parsing, new gate keys and their adversarial tests, prompt injection inside CEF and XML fixtures.

### Suggested commits
- `feat: add CIM library and model normalizer`
- `feat: add automatic data model selection`
- `feat: add spec parser and per-version key table`
- `feat: add format detection and fixtures`

### Docs to update
- `docs/formats.md`, `cim_spec/` and `guardrails/` READMEs, `docs/setup.md` (CIM library), `THIRD_PARTY_NOTICES.md` (`defusedxml` if bundled), security baseline (A05).

### If late, cut
- The last formats in the order of work (fixed-width, encodings). Never the hostile-package and XXE tests.

---

## Phase 18 — Deployment pipeline

**Goal:** approved add-ons reach production environments safely per topology, in handoff or managed mode, with impact analysis, verification and rollback (7.2, D2, D7, D11).
**Owners:** `splunk` (planner, delivery adapters, relay, preview, verify), `engine` (deployment state machine, approvals), `frontend` (deploy dialog, plan, console, command library), `devops` (relay packaging).

### Deliverables
- `deployments`, `deployment_events`, `environment_tas`; deployment states with checked transitions.
- Planner per topology with the tier rule, HF-first order and per-target reasons; refusal of UF server classes and indexers.
- Handoff bundle (`.tgz`, `SHA256SUMS`, numbered runbook); command library with copy buttons, checked in the lab.
- Managed delivery: REST `apps/local` where Q12 allows; relay (`relay/pmx-relay`) with its fixed verbs, forced command, host key pinning, Ed25519 keys in the vault, live read-only console.
- Search-time preview, shared search head check, impact analysis; approval with hash, environment and tiers named; four-eyes setting; high-risk typed confirmation.
- Verify per tier and rollback to any registered version per environment.
- `make relay-test`.

### Acceptance criteria
- One TA deployed in handoff and in managed mode to standalone, SHC, HFs directly, HFs via their deployment server, and the HF that is also the UF deployment server, in the owner's lab.
- Never to indexers or UF server classes (tests).
- The relay refuses every verb outside its list, a wrong hash and a traversal path (tests); a changed host key blocks every call.
- No code outside `deploy/` writes to a non-sandbox Splunk (test).
- Rollback per environment to any version; a failed verification never retries a push.
- Secrets never appear in the console, command lines or copied text (tests).

### OWNER ACTION
- Install the relay on the lab deployer and DS from `relay/README.md` and confirm the host key fingerprints.
- Approve the first production deployments in the lab.

### Appsec review focus
- Relay command surface, credential passing over stdin, approval binding, tier rule bypasses, console rendering (A01, A05, A08, LLM06, ASI02).

### Suggested commits
- `feat: add deployment model and planner`
- `feat: add handoff bundles and command library`
- `feat: add restricted SSH relay`
- `feat: add managed delivery, verify and rollback`
- `feat: add search-time preview and impact analysis`

### Docs to update
- `relay/README.md` (install, `authorized_keys` line, verbs, logs, uninstall), `relay/CLAUDE.md`, `engine/parsemaxxing/deploy/CLAUDE.md` and README, `docs/setup.md` (relay), threat model T15, security baseline.

### If late, cut
- Managed delivery to the SHC deployer (handoff only for SHC). Never handoff mode, verification or the tier rule.

**Release:** tag `2.0.0-alpha.2` after this phase.

---

## Phase 19 — Analytics dashboard

**Goal:** analytics on runs, add-ons, deployments, cost, environments and knowledge (7.8), plus optional `pmx_audit` forwarding.
**Owners:** `engine` (views, endpoints, `analytics_ro` role), `frontend` (Overview and Analytics screens).

### Deliverables
- PostgreSQL views per 7.8, read through `analytics_ro`; filtered endpoints.
- Overview KPI tiles and trends; Analytics section with drill-down; data table toggle per chart; chart library chosen in Q19.
- Optional forwarding of ledger, audit and deployment events to `pmx_audit` with a dashboard and alert templates.

### Acceptance criteria
- Every metric in 7.8 backed by a view with a test on fixture data.
- Charts accessible: status never by colour alone, data table toggle, axe clean.
- `analytics_ro` cannot write (test).

### OWNER ACTION
- Decide whether `pmx_audit` forwarding is on in the lab and which environment receives it.

### Appsec review focus
- Read-only role grants, data exposure across customers in analytics, audit forwarding credentials.

### Suggested commits
- `feat: add analytics views and endpoints`
- `feat: add Overview and Analytics screens`
- `feat: add optional pmx_audit forwarding`

### Docs to update
- `analytics/` README, `web/CLAUDE.md` (chart rules), `THIRD_PARTY_NOTICES.md` (chart library), features.

### If late, cut
- Knowledge metrics (they need Phase 20) and `pmx_audit` forwarding.

---

## Phase 20 — Knowledge base (RAG)

**Goal:** retrieval that lowers attempts and tokens, fully offline, never a judge (7.12, D4).
**Owners:** `knowledge` (ingest, chunking, packs, embeddings, retrieval, evaluation, project notes drafts), `agents-ai` (`references_used`, prompt blocks), `frontend` (Knowledge screens).

### Deliverables
- pgvector image pinned by digest; `knowledge_sources`, `knowledge_chunks`, `run_references`.
- Tiers 1 to 8: spec chunks (one setting each), pinned `splunk-agent-skills` with its licence, CIM chunks, project notes reviewed by the owner, imported documents (direct PDF import and signed offline packs, quarantine), approved add-ons, reference add-ons, fix memory.
- `fastembed` local embeddings, hybrid retrieval with reciprocal rank fusion, version matching (strict, nearest).
- `parsemaxxing pack build`; sandboxed PDF worker with no network; size and page caps.
- Retrieval in the orchestrator (at most 6 chunks), references in the ledger, approval report and deployment plan.
- Golden set and A/B harness in `engine/tests/knowledge/`.

### Acceptance criteria
- Golden-set recall@6 ≥ 0.8.
- A/B shows fewer attempts or tokens on 2+ fixtures with no lower pass rate.
- Poisoning tests: an imported doc with instructions changes nothing the gate allows.
- The priority 1 manual PDFs import directly and through a signed offline pack on a server with no network; a tampered pack is refused; retrieval cites them with version and page.
- Fix memory returns the right past fix for a repeated synthetic failure and never a rejected or rolled-back fix.
- A reference add-on upload is read without executing anything; a hostile package is refused.

### OWNER ACTION
- Download the priority 1 Splunk manual PDFs for 10.2 and 10.6 under the team's access and import them in the lab.
- Review each project note before it is merged.

### Appsec review focus
- SSRF in URL import, pack signature checks, PDF parser isolation, poisoning and prompt injection through retrieved text (LLM01, LLM04, LLM08).

### Suggested commits
- `feat: add knowledge store with local embeddings`
- `feat: add document import and offline packs`
- `feat: add retrieval to agent context`
- `test: add knowledge golden set and A/B harness`

### Docs to update
- `docs/knowledge-sources.md` (status from planned to built for what lands), `engine/parsemaxxing/knowledge/CLAUDE.md` and README, `THIRD_PARTY_NOTICES.md` (agent skills, embedding model, PDF library), threat model T14, T18.

### If late, cut
- URL import, reference add-ons library upload, nearest-version fallback. Never quarantine or pack signatures.

---

## Phase 21 — Discovery, masking and real-log retention

**Goal:** find what needs a parser in a connected environment and start a job from it, with masking before any hosted model and real logs deleted on schedule (7.9, 7.10 masking, 7.19).
**Owners:** `splunk` (discovery searches, masking), `engine` (findings, purge job), `frontend` (Discovery screens, retention UI), `qa` (property and purge tests).

### Deliverables
- `discovery_scans`, `discovery_findings`; fixed SPL checks and verdicts per 7.9; index scan; create a job from a finding.
- `masking/` with consistent, format-preserving pseudonyms and secret placeholders, at the LLM client.
- Real-log purge job (hourly, idempotent, ledger records counts and ids); evidence and reports rewritten with masked lines; per-client retention 0 to 30 days; "Delete real data now".
- Sandbox `pmx_` index retention set no higher than 30 days; job-end removal per Q24.

### Acceptance criteria
- A synthetic broken sourcetype in the lab gets the right verdict.
- An out-of-allowlist index is refused (adversarial).
- Masked samples keep regex shapes (property tests).
- Real samples, evidence lines, console transcripts and masking maps are gone after the client's setting (30 days by default, 0 to 30), proven by a purge test that searches the database and files for a planted marker string.
- The sandbox index retention is never above 30 days (test).

### OWNER ACTION
- Plant a synthetic broken sourcetype in the lab and run a scan.

### Appsec review focus
- Masking completeness, discovery data exposure (T17), purge completeness, tenant isolation of discovery searches.

### Suggested commits
- `feat: add discovery checks and findings`
- `security: add masking at the LLM client`
- `feat: add real-log purge and retention settings`

### Docs to update
- `docs/setup.md` and `SECURITY.md` (data retention: what is deleted and when, what stays, backups no longer than 30 days), `discovery/` and `masking/` READMEs, threat model T17.

### If late, cut
- Index scan (single sourcetype only). Never masking or the purge.

---

## Phase 21b — Overlay fixes for existing add-ons

**Goal:** fix another add-on's parsing with a separate overlay add-on, without touching it (7.18). Starts only after Q23 is answered.
**Owners:** `splunk` (precedence checks, overlay builder), `agents-ai` (delta proposals), `engine` (job kind), `frontend` ("Fix this add-on"), `qa`.

### Deliverables
- Overlay add-on type `TA-parsemaxxing-overlay-<vendor>-<product>` (or the name Q23 requires, with the naming rule and gate extended to that one pattern).
- Inputs from a discovery finding or "Fix this add-on"; agents propose only the delta.
- Gate check that every overlay setting takes effect, from effective settings read back on the sandbox.
- Upgrade safety: re-run the masked regression set against a new vendor version and flag settings as needed, redundant or conflicting.

### Acceptance criteria
- A synthetic vendor-style add-on with a wrong `TIME_FORMAT` and a missing CIM alias is fixed by an overlay without touching it.
- The gate fails an overlay whose setting does not take effect.
- An upgrade of the vendor add-on that fixes one issue marks that overlay setting redundant.
- Overlays touch only props, transforms, eventtypes and tags (adversarial tests).

### OWNER ACTION
- Confirm the Q23 result and the overlay name before the build starts.

### Appsec review focus
- Naming rule extension, precedence assumptions, that the vendor add-on is never written.

### Suggested commits
- `feat: add overlay add-ons for existing sourcetypes`
- `feat: add overlay upgrade checks`

### Docs to update
- Root `CLAUDE.md` naming rule if Q23 changes it, `ta_builder/` and `guardrails/` READMEs, features.

### If late, cut
- Upgrade safety checks (manual re-test instead).

---

## Phase 22 — Drift pipeline (multi-environment)

**Goal:** old Phase 8, per environment: alerts detect a format change, code collects masked samples, the Drift Analyst confirms it, an update job runs, and the fix is proposed as a deployment awaiting approval (7.10).
**Owners:** `splunk` (monitoring app, collector), `agents-ai` (Drift Analyst), `engine` (webhook, dedup, states, deployment proposal).

### Deliverables
- Monitoring app deployed per environment through the deployment pipeline.
- Per-environment webhook token (vault) and source-IP allowlist; signals carry the environment id; dedup, grouping and cooldown per (environment, TA).
- Collector with masking; Drift Analyst with `fetch_more_samples`; `drift_signals`, `drift_jobs`.
- Update job → new version → deployment proposed to the affected environment only; "newer version available" elsewhere.

### Acceptance criteria
- Old Phase 8 criteria, per environment: a format switch at minute 2 leads to an update job and a proposed deployment awaiting approval, with no human action in between; a webhook call without the token or from another IP is refused; masking keeps formats.
- No automatic deployment to any environment, including the affected one (test).
- Signals from environment A never attach to a drift job of environment B (test).

### OWNER ACTION
- Configure the webhook alert action in a lab environment; make sure the engine is reachable from its search heads.

### Appsec review focus
- Webhook authentication, masking before the model call, read account scope.

### Suggested commits
- `feat: add per-environment drift alerts and collector`
- `feat: add Drift Analyst and drift jobs`

### Docs to update
- `drift/` README, `docs/setup.md` (webhook), features, threat model.

### If late, cut
- Grouping of signals within minutes (dedup only).

---

## Phase 23 — Mixed-feed routing (topology-aware)

**Goal:** old Phase 9 with topology: split a shared feed into vendor sourcetypes, with routing placed only on the parsing tier (7.11).
**Owners:** `agents-ai` (Router), `splunk` (routing exception, plan placement, negative tests), `qa`.

### Deliverables
- Routing stage, narrow `TRANSFORMS-` exception, multi-vendor generator feed (as in Phase 9).
- Exact `[host::]` and `[source::]` stanzas for routed data, enforced by the gate.
- Plan places the routing part on heavy forwarders only; negative test also runs in the impact analysis on a production sample.
- Rollback and revert re-run the negative test.

### Acceptance criteria
- Old Phase 9 criteria: 100% of target events routed, exactly 0 non-target events renamed, any other `DEST_KEY` on the generic stanza blocked, no routing transform left after rollback.
- Routing placed only on the parsing tier in the plan (test).
- A wildcard broader than the feed is blocked (adversarial).

### OWNER ACTION
- Approve a routing deployment in the lab with the high-risk confirmation.

### Appsec review focus
- That the exception is as narrow as designed, misrouting in shared environments, rollback completeness.

### Suggested commits
- `feat: add routing stage for shared feeds`
- `feat: place routing on the parsing tier`

### Docs to update
- `routing/` README, features, threat model.

### If late, cut
- The production-sample negative test in the impact analysis (sandbox only, flagged in the plan).

**Release:** tag `2.0.0-beta.1` after this phase.

---

## Phase 24 — Security verification, UX usability pass, release 2.0.0

**Goal:** every security baseline row is built or an accepted risk, the UI passes a usability review, and a clean install works quickly.
**Owners:** `appsec`, `qa`, `ux`, `docs`, `devops`.

### Deliverables
- Security baseline review row by row; OWASP ZAP baseline scan on the running stack.
- UX usability pass over every flow in `docs/ux/flows.md`.
- Clean-VM install test; all docs checked against the code.
- `2.0.0` release notes.

### Acceptance criteria
- Security baseline 100% rows "built" or an accepted residual risk signed by the owner.
- ZAP baseline scan clean on the running stack.
- Clean-VM install under 20 minutes.
- All docs truthful: nothing marked built that is not.

### OWNER ACTION
- Sign the accepted residual risks; complete the legal and trademark actions listed in Phase 11; tag `2.0.0`.

### Appsec review focus
- Everything; especially the residual risks and any row still planned.

### Suggested commits
- `security: close baseline findings`
- `docs: prepare 2.0.0 release`

### Docs to update
- All of them; `SECURITY.md` supported versions.

### If late, cut
- Nothing: the release waits.

**Release:** tag `2.0.0` at the end of this phase.

---

## Phase 25 — Onboarding governance design (no code)

**Goal:** decide how Parsemaxxing could own sourcetype naming and index routing (7.14). Design only.
**Owners:** the main session, `splunk`, `appsec`.

### Deliverables
- [design-onboarding.md](design-onboarding.md) completed: where sourcetype and index are set, what Parsemaxxing could own in order of risk, why index routing is the most dangerous, a proposed phase plan, open questions.

### Acceptance criteria
- The owner has decided which parts to build.
- No code.

### OWNER ACTION
- Answer the open questions in `design-onboarding.md` and decide.

### Appsec review focus
- Cross-customer data leaks from index routing; the gate exception it would need.

### Suggested commits
- `docs: design onboarding governance`

### Docs to update
- `docs/design-onboarding.md`, `docs/design.md` 7.14 status, this plan (new phases if the owner decides to build).

### If late, cut
- Nothing to cut; it waits for the owner.

---

## Risks

- **Lab findings may force design changes** (Q12 remote install, Q13 SHC push, Q14 DS mapping, Q23 overlay precedence, Q24 per-job event removal). That is why every lab question is answered in Phase 11, before code.
- **Overlay precedence (Q23)** may need a different app name; Phase 21b waits for it.
- **The relay** is the only write path that is not REST; its verb list and key handling get the deepest review in Phase 18.
- **Model costs** across several providers. The per-run and daily caps apply across all providers from Phase 16.
- **Legal review** of the licence notices and generated add-on statement must happen before 2.0.0 (Phase 24).
