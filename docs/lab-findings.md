# Lab findings (Phase 1)

> Every open question from [design.md](design.md), plus those the build plan added. Each has how to test it, the result and the decision it causes. **Expectation** lines are unverified hypotheses written before testing; only **Result** lines count. Never paste tokens, passwords, real hostnames or IPs here.

## Summary

| Q | Question | Answered by | Status | Decision |
| --- | --- | --- | --- | --- |
| Q1 | Does the Meta Model API support `response_format` JSON schemas, or do we need a forced tool call? | `probe_llm` | Answered 2026-10-27 | `response_format` with a strict JSON schema |
| Q2 | What is "contributor mode"? | Meta docs | Answered 2026-10-27 | Standard mode; contributor variant only for synthetic-only dev runs, if ever |
| Q3 | Do index-time settings apply to the next ingest right after a reload? | `probe_install`, `probe_update` | Answered 2026-10-27 (new sourcetype), 2026-10-28 (changed settings, same sourcetype) | Applied right after install, no reload or restart needed, in both cases |
| Q4 | Which edge cases are in scope? | Decision | Decided 2026-10-27 | In: multiple event types, missing TZ, epoch. Stretch: multi-line. Out: CSV `INDEXED_EXTRACTIONS` |
| Q5 | Four agents, or merge Extraction and CIM mapper into three? | Decision | Decided 2026-10-27 | Four agents |
| Q6 | Deploy path: install a package, or write stanzas over REST? | `probe_install` + decision | Answered 2026-10-27 | A: package install via `apps/local`; `update=true` is a full replace |
| Q7 | How to run `btool check` without shell access to Splunk | Decision | Decided 2026-10-27 | Option 1: allowlist + typed values before deploy, fail on any splunkd warning after install |
| Q8 | Ingest path: does `receivers/simple` apply line breaking and timestamps? | `probe_splunk` + `probe_install` | Answered 2026-10-27 | `receivers/simple` |
| Q9 | Which capabilities does the deploy role need? | `probe_splunk` + `probe_install` | Answered 2026-10-27 | `admin_all_objects`, `edit_tcp`, `install_apps`, `list_all_objects`; one shared test index, no `indexes_edit` |
| Q10 | CIM add-on installed, `pmx_*` in the CIM index macros | Manual lab step + search-token check | Done 2026-10-27 | Lab prerequisite met |
| Q11 | Does an in-place update (`update=true`) keep an admin's `local/`, and can the review see overrides? | `probe_update` | Answered 2026-10-28 | Yes: promote updates in place; flag overrides from the effective settings, with system defaults in code |

## Lab setup (OWNER ACTION, once)

1. **Start Splunk:** the lab VM, or `make up` for the Docker stack. Log in to Splunk Web as `admin`.
2. **Create the test index:** in Settings → Indexes, create `pmx_probe`.
3. **Create three roles** (Settings → Roles):
   - **`parsemaxxing_search`**
     - Inherits nothing. Inherited index access cannot be removed in a child role, so inheriting `user` could widen what it can search.
     - Capability: `search`.
     - Indexes searched by default and allowed: only `pmx_*` and `_internal`.
     - Remove access to every other index.
   - **`parsemaxxing_deploy`**
     - Inherits nothing.
     - Start with the capabilities in Q9's expectation and trim them after the probe.
     - Allowed indexes: `pmx_*`. This limits only what the role can search. Splunk does not limit which index a role can **write** to; see Q9.
   - **`parsemaxxing_drift`**
     - Inherits nothing.
     - Capability: `search` (read-only).
     - Search filter set later (Phase 8).
4. **Create three users** (Settings → Users), one per role, each with a long random password you don't keep. Tokens are how they authenticate. Remove the pre-selected `user` role, so each user has only its own role.
5. **Create the tokens:** Settings → Tokens → enable token authentication, then create one token per user. Paste them into `.env` as `SPLUNK_SEARCH_TOKEN`, `SPLUNK_DEPLOY_TOKEN` and `SPLUNK_DRIFT_TOKEN`.
6. **Point `.env` at Splunk:** set `SPLUNK_HOST` and `SPLUNK_PORT` to the lab's REST address.

## Running the probes (OWNER ACTION)

```bash
scripts/probe.sh llm              # loads .env into the probe's process only
scripts/probe.sh splunk
```

Against the Docker stack, port 8089 is not published to your machine (by design). Run the Splunk probe inside the Compose network instead:

```bash
docker run --rm --network parsemaxxing_default \
  -e SPLUNK_HOST=splunk -e SPLUNK_PORT -e SPLUNK_SEARCH_TOKEN -e SPLUNK_DEPLOY_TOKEN \
  -e PYTHONPATH=/engine -v "$PWD/engine:/engine:ro" python:3.12-slim \
  sh -c "pip install -q splunk-sdk==2.1.1 && python -m parsemaxxing.tools.probes.probe_splunk"
```

This passes only the two tokens the probe needs (exported by the `set -a` line above), never the whole `.env` with the admin and database passwords. It also mounts the source read-only.

Both probes print only usernames, roles, capability names, counts and pass/fail lines; they never print tokens or prompts. Paste their output under **Result** below. **Remove any hostname or IP first**: error messages can name the lab VM.

## Q1. Structured output from the Meta Model API

- **Why it matters:** every agent returns a schema-validated object. The LLM client (Phase 2) needs to know which mechanism to use.
- **How:** run `probe_llm`. It sends one tiny request with `response_format: json_schema` and, if that fails, one with a forced tool call. It prints which mode works and the token count.
- **Expectation:** at least one mode works. If neither does, Phase 2 falls back to JSON in plain text, validated by Pydantic, with the "bad output" retry cap of 2.
- **Result (2026-10-27):**
  - **First run, with `max_tokens=50`:** `response_format` returned output that failed validation, and the forced tool call was refused with HTTP 400. The probe then printed only error class names, so the cause wasn't visible.
  - **Second run:** the probe now allows 512 output tokens, prints safe failure details, and also tries `tool_choice="required"` and `json_object`. Output:
    ```
    response_format: PASS (tokens in=27 out=316)
    structured output mode: response_format
    ```
  - **Cause of the first failure:** a one-word answer used 316 output tokens, so the model reasons before answering and the 50-token cap cut the JSON off.
  - The forced-tool 400 was not re-tested, because the probe stops at the first mode that passes.
- **Decision:**
  - **Mode:** every agent uses `response_format` with `json_schema` and `strict: true`, and its Pydantic model's schema. Pydantic still validates every reply, and the "bad output" retry cap of 2 still applies.
  - **Output cap:** the LLM client never sets a small `max_tokens`. Each agent's cap leaves several hundred tokens for reasoning on top of the expected output. Hitting the cap (`finish_reason=length`) counts as bad output, not a stage failure.
  - **Budget:** reasoning tokens are billed as output. Per-run token ceilings and cost estimates use measured `completion_tokens`, not the size of the JSON.
  - **Fallback:** forced tool calls are not pursued unless `response_format` regresses.

## Q2. "Contributor mode"

- **Why it matters:** design.md says to default to standard mode until this is confirmed.
- **How:** read the Meta Model API docs or the hackathon guide (OWNER, since it needs your account).
- **Result (2026-10-27, from Meta's docs, read by the owner):**
  - In contributor mode, Meta may use the content sent and received (prompts, files, context and model responses) to train future Meta models. In exchange, usage is discounted.
  - On the Meta Model API it is not a setting: you call a model's **contributor-mode variant** instead of the standard model. The variant's name is on the docs page "How do I use Contributor mode on Meta Model API?", not yet read.
  - It is unavailable to accounts with Zero Data Retention.
  - The terms forbid sending sensitive, confidential or personal information to these discounted services. Use cases with personal information must use standard services.
- **Decision:**
  - **Parsemaxxing uses standard mode.** Its input is customers' logs, which are confidential by nature, and the design's on-prem mode exists so logs never leave the network.
  - The default `LLM_MODEL` names the standard model.
  - A contributor-mode variant may be set through `LLM_MODEL` **only for runs on synthetic fixtures**, for example to stretch the hackathon credits. Never with real logs.
  - Never in on-prem mode, and never as the default.
  - The README states this when it documents `LLM_MODEL`.

## Q3. Index-time settings after a reload

- **Why it matters:** the inner loop deploys, reloads (no restart) and ingests at once. If index-time settings (`LINE_BREAKER`, `TIME_FORMAT`, `TZ`) only apply after a restart, the loop design changes.
- **How** (manual, about 10 minutes, after Q6 picks a deploy path):
  1. Deploy a test app with `[pmx_probe_lb]` containing `SHOULD_LINEMERGE = false` and `LINE_BREAKER = (;)`.
  2. Reload: `| rest /services/configs/conf-props/_reload` or the debug/refresh endpoint.
  3. Ingest `a;b;c` with `sourcetype=pmx_probe_lb` into `pmx_probe`.
  4. Count. **3 events** means the reload applied index-time settings; **1 event** means it didn't.
  5. Repeat with a `TIME_FORMAT`/`TZ` change and compare `_time`.
- **Expectation:** on a standalone instance a props reload is picked up by new inputs. Needs proof on this Splunk version (10.6.1 in Docker).
- **How it was tested:** `scripts/probe.sh install` (`probe_install`), not the manual steps above. Run against the owner's standalone lab Splunk, not the Docker image.
  1. It installs a test add-on whose sourcetype has `LINE_BREAKER = (;)`, `TIME_PREFIX = ts=`, `TIME_FORMAT = %Y-%m-%d %H:%M:%S` and `TZ = Pacific/Chatham`. The +13:45 zone means a correct `_time` cannot come from the server's own zone.
  2. It posts `a;b;c`, each event with a timestamp, through `receivers/simple` straight after the install, without reloading.
  3. It checks that there are 3 events and that `_time` exactly equals the expected epochs.
  4. Only if that fails does it reload `conf-props` and retry.
- **Result (2026-10-27):**
  ```
  ingest right after install, no reload: 3 events (expect 3: LINE_BREAKER applied), _time matches TIME_FORMAT+TZ
  ```
  Index-time settings from a newly installed add-on apply to the very next ingest. Neither a reload nor a restart was needed, so the reload fallback never ran.
- **Not yet tested:** changing the settings of a sourcetype that already exists, by reinstalling with `update=true` under the same sourcetype name. The probe's v2 used a new sourcetype name.
- **Decision:**
  - The inner loop is install, then ingest, with no restart.
  - Each attempt uses its own sourcetype name, so every attempt is the tested "new sourcetype" case. The attempt number goes into the `__test_<job>` suffix, for example `<st>__test_<job>_a<n>`.
  - Phase 2 keeps one reload call (`configs/conf-props/_reload`) as a safety net, used only if the event count is wrong, and logs when it was needed.

## Q4. Edge cases in scope

The candidates from design.md:
- multiple event types per file;
- multi-line events;
- a missing timezone;
- epoch timestamps;
- CSV headers (`INDEXED_EXTRACTIONS`).

- **Recommendation:**
  - **In scope:** multiple event types per file, missing timezone and epoch timestamps. They are cheap with the generator and demo well; "missing TZ" is the classic +3 h error.
  - **Stretch:** multi-line events.
  - **Defer:** CSV with `INDEXED_EXTRACTIONS`, because it is index-time structured parsing with different rules. Keep CSV via search-time `REPORT-`/`DELIMS` instead.
- **Decision (OWNER, 2026-10-27):** the recommendation above.
  - **In scope:** multiple event types per file, missing timezone and epoch timestamps (seconds and milliseconds).
    - Each gets a generator fixture with a truth manifest.
    - Each gets Validator checks: per-event-type field coverage, and `_time` compared with the manifest's epochs.
    - A missing timezone is flagged by the Profiler for the human to confirm at profile review.
  - **Stretch:** multi-line events, only if Phase 3 finishes early.
  - **Out:** CSV with `INDEXED_EXTRACTIONS`. CSV is still supported through search-time `REPORT-`/`DELIMS`.
  - The README lists the out-of-scope and stretch cases as "planned".

## Q5. Four agents or three

- **Recommendation:** keep four, as the design has them. Separate context and ownership are what make failure routing and "agents never grade themselves" clear. Merging saves one prompt but blurs which agent owns a failing check. Revisit only if Phase 3 runs late.
- **Decision (OWNER, 2026-10-27):** **keep four agents**: Profiler, Index-time, Extraction and CIM mapper.
  - **Accuracy:** each agent's context stays focused, so the CIM mapper never sees regex attempts and Extraction never sees the CIM spec. A failing check routes to exactly one owner.
  - **Safety:** the agent that maps to CIM cannot rewrite extractions to game a CIM check.
  - **Fallback:** merging Extraction and CIM mapper stays the documented fallback only if Phase 3 runs late.

## Q6. Deploy path

The design says to "write the new TA version to `/opt/splunk/etc/apps/TA-*/default/` via REST". There are two ways to do that:

| | A. Package install (`apps/local`, `update=true`) | B. Config endpoints (`configs/conf-props`, `conf-transforms`, … with an app namespace) |
| --- | --- | --- |
| Needs | The `.tgz` readable on the Splunk host: a shared Docker volume, or `scp` to the VM | Only REST |
| Writes | Exactly the tested package (`default/`, `metadata/`, `lookups/`) | Stanzas, usually into the app's `local/`, not `default/` |
| Fits hash-bound approval (T3.5) | Yes, since the installed bytes are the approved `.tgz` | Weaker, since the installed state is rebuilt from calls |
| Fits design ("`local/` never written") | Yes | **No**: conflicts with the parser-update rule that `local/` belongs to admins |

- **Recommendation:** **A, package install.** In Docker, mount a dedicated volume read-only into `splunk` (for example `/opt/parsemaxxing/packages`) and read-write into `engine`. Only `.tgz` files go there. On the VM, use the same path with a copy step.
- **How to verify:**
  1. Install a trivial `TA-parsemaxxing-acme-probe__test_probe.tgz` with `parsemaxxing_deploy`'s token, then confirm it appears in `apps/local`.
  2. Try the same with the search token, which must be refused.
  3. Reinstall with `update=true` from a package whose `default/props.conf` has a different set of stanzas, then confirm the installed app holds exactly the new package's stanzas: a full replace, not a merge.
- **Result (2026-10-27):** `scripts/probe.sh install`, which builds the packages in `PARSEMAXXING_PACKAGES_DIR` (owned by the engine user, mode 755, readable by `splunk`):
  ```
  install with search token: refused HTTP 403 (good)
  install v1 with deploy token: ok
  v1 stanza present after install: True
  reinstall v2 with update=true: ok
  after v2: v1 stanza present=False, v2 stanza present=True (full replace)
  cleanup: test add-on uninstalled
  install probe: PASS
  ```
  - The search token cannot install apps.
  - The deploy token installs from a path on the Splunk host.
  - `update=true` **replaces** the add-on's config instead of merging it, so a stanza dropped from a later package really disappears. This confirms the "always build the complete package" rule below.
  - The deploy token can also uninstall the test add-on.
- **Decision (OWNER, 2026-10-27):** **A, package install.**
  - Each attempt installs the complete add-on as a `.tgz` through `apps/local` with `update=true`, using the deploy token.
  - All agent-proposed stanzas are written by the escaping conf writer into `default/*.conf` inside the package. Nothing is written over the `configs/conf-*` endpoints, so `local/` is never touched.
  - The TA builder regenerates the full package on every attempt, with the stanzas from every stage so far, never a delta. `update=true` replaces `default/` as a whole, so a partial package would drop earlier stages' stanzas.
  - Packages reach Splunk through a dedicated shared folder, `/opt/parsemaxxing/packages`, mounted read-write in `engine` and read-only in `splunk`, holding only `.tgz` files. On the VM, a copy step puts them at the same path.
  - Follow-ups:
    - Phase 2 adds the shared volume to `docker-compose.yml` for the Docker lab.
    - On a Splunk running directly on the host, `PARSEMAXXING_PACKAGES_DIR` is a plain directory: `/opt/parsemaxxing/packages`, owned by the engine user, mode 755. Not `/tmp`, where any user could plant a package.

## Q7. `btool check` without shell access

`btool` runs on the Splunk host. The tempting fix is to mount the Docker socket into the engine so it can `docker exec`, but that hands the engine root on the host (threat T7.5), so **it is ruled out**.

- **Options:**
  1. **Local check in the engine:** the escaping writer guarantees syntax. The gate checks keys and values against an allowlist of known settings with valid types. Then the deploy reload's messages are read back through REST (`/services/messages`, splunkd warnings on `_internal`).
  2. **A minimal sidecar in the Splunk container**, exposing only "run `btool check` for app X". It is more moving parts and a new attack surface.
- **Recommendation:** option 1, but only if it **fails closed**: any splunkd warning or error about the test app after reload fails the attempt. The writer plus allowlist cover what `btool check` catches for the keys we allow (unknown keys, bad stanzas), and Splunk's own warnings after reload catch the rest.
- **If chosen:** the same PR must update design.md (the "`btool check` before deploy" Must row) and threat T2.11's control text.
- **Decision (OWNER, 2026-10-27):** **option 1.**
  - **Before deploy:** the escaping writer makes malformed stanzas impossible. The gate checks every key against an allowlist with typed values and bounds, so unknown, misspelled or out-of-scope keys are rejected before Splunk sees them.
  - **After install and ingest:** a fixed Validator search over `_internal` (`log_level IN (WARN, ERROR)`, `component` from the parsing pipeline, mentioning the attempt's sourcetype or app, during the ingest window) plus `/services/messages`. Any hit fails the attempt; so does an error or timeout of the check itself (fail closed). The message is passed to the owning agent as evidence.
  - **Limit (appsec review):** splunkd does not warn at runtime about unknown or misspelled props keys; only btool does. So the allowlist is the **only** syntax control, and must reject every key not on it. The post-install check catches parsing problems such as timestamp and line-breaking warnings.
  - **Transform collisions:** the transform-name collision check, which the design also did with btool, becomes a REST read of existing transform names (`configs/conf-transforms`) before deploy.
  - **Ruled out:** a sidecar and the Docker socket. Neither adds a shell path to the engine.
  - **Why:**
    - it covers what btool catches for the allowed keys, more strictly, since it blocks before deploy;
    - it adds no attack surface;
    - it works the same on the lab and in the judges' Docker setup;
    - the allowlist is a Must guardrail anyway.
  - **Revisit:** add a sidecar only if Phase 2–3 runs find a config error that Splunk accepts silently and the allowlist misses.
  - **Phasing:** the allowlist starts in Phase 2 with the index-time keys, and grows in Phases 3 and 4.

## Q8. Ingest path

- **Why it matters:** `data/inputs/oneshot` reads a file **on the Splunk host**, which needs the same shared volume as Q6A. `receivers/simple` takes the data in the POST body.
- **How:** `probe_splunk` posts three lines in one request and reports whether they became 1 or 3 events. Then repeat Q3's test on this path, to confirm `LINE_BREAKER` and `TIME_FORMAT` from the test sourcetype apply.
- **Expectation:** `receivers/simple` goes through the full parsing pipeline, so line breaking and timestamps apply. If the result shows 1 event, use oneshot from the Q6 shared volume instead.
- **Result (2026-10-27):** `probe_splunk`, with the deploy token posting to `pmx_probe` and the search token counting:
  ```
  receivers/simple: posted 3 lines, indexed 3 events (line breaking applied)
  ```
  This proves the default line breaking runs on this path. It does not yet prove that a **custom** test sourcetype's `LINE_BREAKER`, `TIME_FORMAT` and `TZ` apply right after a reload. That is Q3's test on this same path, after the first add-on install (Q6).
- **Result, custom sourcetype (2026-10-27):** Q3's `probe_install` run used this same path. A test sourcetype's own `LINE_BREAKER`, `TIME_FORMAT` and `TZ` were applied: 3 events with exact `_time` values. See Q3.
- **Decision:** ingest uses `receivers/simple`, with the samples in the POST body, so ingest needs no shared volume. `data/inputs/oneshot` is not used.

## Q9. Deploy role capabilities

- **How:** `probe_splunk` prints the notable capabilities each token has. Start the deploy role with the expectation below, run Q6's install test and ingest, then remove capabilities one at a time until something fails.
- **Expectation:** the role needs:
  - `install_apps`, or `admin_all_objects` on some versions, to install and update apps;
  - `edit_local_apps`, if B were chosen;
  - `rest_apps_management`;
  - ingest rights into `pmx_*` (index access, plus `edit_tcp` for `receivers/simple`).

  The search token must have none of these.
- **Warning:** with `install_apps` and `edit_tcp`, the deploy token is effectively an admin token.
  - It can install an app that contains scripts, which runs code on the Splunk host.
  - It can write into any index (for example `receivers/simple?index=main`). Role index settings do not restrict writes.
  - Therefore:
    - the `pmx_` check in code is the only guard on the ingest target (T5.1);
    - the deploy token lives only in the orchestrator process. It must never reach an agent, a prompt, the web process or the ledger.
- **Result (2026-10-27, partial):** `probe_splunk` output:
  ```
  search token: user=parsemaxxing_search roles=['parsemaxxing_search'] notable_caps=[]
  deploy token: user=parsemaxxing_deploy roles=['parsemaxxing_deploy'] notable_caps=['admin_all_objects', 'edit_tcp', 'install_apps', 'rest_apps_management']
  search pmx_probe: count=0 (should run without error)
  search other indexes: count=0 (expect 0: only pmx_* and _internal visible)
  ```
  - **Search token:** it has its own role only and none of the listed capabilities. Searching outside `pmx_*` and `_internal` returns 0 events. The role was created with no inheritance, not inheriting `user` as the lab setup above first said, and new users were created without the default `user` role.
  - **Ingest:** without `edit_tcp` the deploy token's `receivers/simple` post was refused with **HTTP 403**. With `edit_tcp`, 3 lines were indexed. **`edit_tcp` is required.**
  - **App install (2026-10-27):** install, update and uninstall work with `admin_all_objects`, `edit_tcp`, `install_apps` and `rest_apps_management`, as shown in Q6's result.
  - **Trim, step 1: `admin_all_objects` is required.** With it removed, `install_apps` alone was not enough. Installing from a path on the host was refused:
    ```
    install v1 with deploy token: refused HTTP 403
    ```
  - **Indexes:** with `indexes_edit` granted, the deploy token could create a `pmx_` index, and the search token was refused (403). Even with `admin_all_objects`, though, the deploy token **could not delete** one (403). An engine that creates one index per attempt, as the design first said, would leave hundreds of indexes behind. Two empty probe indexes were left this way. A later index listing no longer showed them, so nothing was left to remove.
  - **Trim, step 2:** with `rest_apps_management` and `indexes_edit` both removed, the full install probe still passed against the shared `pmx_test` index:
    ```
    deploy token: user=parsemaxxing_deploy roles=['parsemaxxing_deploy'] notable_caps=['admin_all_objects', 'edit_tcp', 'install_apps']
    test index: pmx_test (exists: True)
    install with search token: refused HTTP 403 (good)
    install v1 with deploy token: ok
    ingest right after install, no reload: 3 events (expect 3: LINE_BREAKER applied), _time matches TIME_FORMAT+TZ
    after v2: v1 stanza present=False, v2 stanza present=True (full replace)
    install probe: PASS
    ```
  - The probe now reports a rejected token's shape (length, part count, user, expiry) without printing it. A pasted-twice deploy token was found this way.
- **Decision (2026-10-27, OWNER):**
  - **One shared test index:** `PARSEMAXXING_TEST_INDEX`, for example `pmx_test`.
    - An admin creates it once. The engine never creates or deletes indexes, so `indexes_edit` is **removed** from the deploy role.
    - Each job and attempt is identified by its sourcetype, `<st>__test_<job>_a<attempt>`.
    - Every Validator search filters on that exact sourcetype. Phase 4 adds an adversarial test that fails if any Validator search lacks the filter.
    - Code still rejects any ingest target that isn't a `pmx_` index.
  - **Size, not age, limits the index.** Set a size cap (`maxTotalDataSizeMB`), not an age-based retention (`frozenTimePeriodInSecs`). Sample events carry historical timestamps, so an age-based limit could freeze them before the Validator reads them.
  - **`list_all_objects` (found 2026-11-04, on a clean install):** the configuration endpoints need it: `configs/conf-*/_reload` for deploy, and `configs/conf-props` and `conf-transforms` reads for search. Splunk's `[default]` role settings turn it on, and the lab roles made in Splunk Web worked without naming it, but the deploy role made over REST was refused (403). `scripts/splunk_bootstrap.py` names it on both roles. Agents gain nothing from it: the search guard refuses `| rest`.
  - **Final deploy role:** `admin_all_objects`, `edit_tcp`, `install_apps`, `list_all_objects`, with allowed indexes `pmx_*`. It is near-admin, as the warning above expected, and accepted for the lab because:
    - the token lives only in the orchestrator process;
    - code checks every app name (`TA-parsemaxxing-…__test_…`) and every ingest target (`pmx_`) before any call;
    - the threat model lists it as a residual risk.

## Q10. CIM add-on and index macros

- **How:**
  1. Install the Splunk Common Information Model add-on from Splunkbase.
  2. In its setup, or under Settings → Advanced search → Search macros, add `pmx_*` to `cim_Authentication_indexes`, `cim_Network_Traffic_indexes` and `cim_Web_indexes`.
  3. Verify with `| tstats summariesonly=false count from datamodel=Authentication where index=pmx_probe`, which should run without error (count 0 is fine).
- **Result (2026-10-27):** the owner installed the CIM add-on and edited the macros. Checked with the **search token**:
  ```
  cim_Authentication_indexes: definition='(index=pw*)'
  cim_Network_Traffic_indexes: definition='(index=pw*)'
  cim_Web_indexes: definition='(index=pw*)'
  datamodel Authentication on pmx_test: ran ok, count=0
  datamodel Network_Traffic on pmx_test: ran ok, count=0
  datamodel Web on pmx_test: ran ok, count=0
  ```
  - The search role can read the macros and run all three data models.
  - The macros say `pw*`, not `pmx_*`, so they would also match a non-test index whose name starts with `pw`. That is harmless for Parsemaxxing, because the search role can only see `pmx_*` anyway, but `pmx_*` is the exact form.
  - Phase 10's bootstrap script writes `(index=pmx_*)`.
- **Decision:** none needed; this is a lab prerequisite. Phase 10's bootstrap script automates it for judges.

## Q11. In-place updates and `local/` (Phase 7)

- **Why:** a parser update replaces a promoted TA in place. The design says `local/` (admin overrides) is kept and never written, and that the review flags overrides the patch collides with. Neither had been tested.
- **How:** `scripts/probe.sh update`.
  1. Install a throwaway test add-on v1.0.0 and check its timestamps.
  2. Write an admin-style override into its `local/` over REST (`TZ` and one extraction). This probe is the only place Parsemaxxing writes `local/`.
  3. Reinstall a v1.1.0 with `update=true`: a new `TIME_FORMAT` for the same sourcetype and one new extraction.
  4. Read the effective settings in the app's context, then ingest new-format lines with no reload.
- **Result (2026-10-28):**
  ```
  install v1: ok
  v1 timestamps correct: True
  after admin edit: EXTRACT-local present=True, TZ=Pacific/Chatham
  reinstall v2 with update=true: ok
  installed version: 1.1.0 (expect 1.1.0)
  local/ kept after update: True (EXTRACT-local present=True, TZ=Pacific/Chatham: local still overrides default's UTC)
  v2 default applied: TIME_FORMAT='%d/%m/%Y %H:%M:%S', EXTRACT-b present=True
  changed TIME_FORMAT on the existing sourcetype applied, no reload: True
  update probe: PASS
  ```
  - `update=true` replaces `default/` and keeps `local/`; a `local/` value still wins over the new default. This is exactly the case the review must flag: an old `TZ` in `local/` would hide the fix.
  - A changed index-time setting on an existing sourcetype applies to the next ingest with no reload (closes the open half of Q3).
  - `configs/conf-props/default` returns 404 in every namespace, so the `[default]` stanza cannot be read as a baseline over REST.
- **Decision:**
  - Updates are promoted in place with `update=true`, only over a TA the registry lists, at the version the registry expects.
  - Overrides are found by comparing the effective settings (app context) with what the production TA's own `default/` sets. For a key the TA does not set, the comparison is against Splunk's documented `props.conf` defaults, kept in code.

# Lab findings v2 (Phase 11)

> Questions Q12 to Q24 from the v2 plan (design sections 7.1, 7.2, 7.16 to 7.19). Q15 is merged into Q14. Every lab question runs on the oldest and the newest supported version (10.2 and 10.6, D10); a result that differs between them is recorded per version. Same rules as above: **Expectation** lines are unverified hypotheses written before testing, only **Evidence** and **Result** lines count, and no token, hostname, IP or client name is pasted here (the v2 probes print hosts and clients as `h-<hash>` labels, but read the output once before pasting).

## Summary (v2)

| Q | Question | Blocks | Answered by | Status | Decision |
| --- | --- | --- | --- | --- | --- |
| Q12 | Can `apps/local` install a package that is not on the host's disk; narrowest deploy capabilities? | Phase 18 standalone and HF adapters | `probe_remote_install` | Open: awaiting owner lab run | |
| Q13 | SHC: `apps/deploy` with a token, `deployer_push_mode`, reading a member's effective props | Phase 18 SHC adapter, relay `apply-shc` | `probe_delivery shc-calls`, `shc-push`; `probe_readback` | Open: awaiting owner lab run | |
| Q14 | DS for HFs: map and reload over REST or relay; tell UF from HF clients; HF-DS restart need | Phase 18 DS adapter, relay `ds-map` | `probe_topology`, `probe_delivery ds-map`, `probe_remote_install` | Open: awaiting owner lab run | |
| Q15 | (Merged into Q14) | | | Merged | |
| Q16 | Smallest `parsemaxxing_read` role; `_internal` restricted to parser components | Phases 12 (role script), 17 (discovery), drift | `probe_read_role` | Open: awaiting owner lab run | |
| Q17 | What can be read back per tier to prove effective settings | Phase 18 `verify` | `probe_readback` | Open: awaiting owner lab run | |
| Q18 | SSH client library for the relay: `asyncssh` or `paramiko` | Phase 18 relay client | Desk research | Proposed, owner to confirm | `asyncssh` |
| Q19 | Embedding model and chart library, licences allow commercial use | Knowledge base, analytics UI | Desk research | Proposed, owner to confirm | `bge-small-en-v1.5` (ONNX); Recharts |
| Q20 | W3C/IIS and CSV: `DELIMS`/`FIELDS` vs `INDEXED_EXTRACTIONS`; header lines out of CIM | Formats phase, gate keys | `probe_formats` | Open: awaiting owner lab run | |
| Q21 | `datamodel/model` vs the package JSON; exact CIM version with the read account | CIM library local-changes check | `probe_cim` | Open: awaiting owner lab run | |
| Q22 | CIM 6.3.0 and newest on 10.2 and 10.6; normalizer reads 6.x and 8.x the same way | CIM library, `environments/versions.py` | `probe_cim` + normalizer tests | Open: awaiting owner lab run | |
| Q23 | Overlay precedence per tier, and how to read the winner back | Overlays (7.18) | `probe_overlay`, `probe_readback` | Open: awaiting owner lab run | |
| Q24 | Remove one job's events from the `pmx_` index without `delete` | Retention purge (7.19) | `probe_retention` | Open: awaiting owner lab run | |

## Owner decisions already settled (v2)

Recorded here so the lab work does not reopen them (master prompt sections 4, 5 and 11):

- **Approvals:** any admin can approve any deployment, including one they requested; the four-eyes setting exists per environment and is off by default (D6).
- **Discovery is manual only:** an admin starts it; nothing scans on a schedule.
- **Viewers see raw samples**, and every view is audited.
- **Sources:** `attack_data` and `security_content` are not used; ECS and OCSF are not used (CIM's own field descriptions give field meaning); reference add-ons and fix memory are in (7.12 tiers 7 and 8).
- **Supported Splunk Enterprise:** 10.2 and later (D10). CIM minimum: `Splunk_SA_CIM` 6.3.0 or later on 10.2 to 10.6, 8.5.0 or later on 10.7 and later (Q22 confirms it in the lab, it does not reopen it).
- **Parsing on heavy forwarders, never indexers** (D11); no cluster manager or indexer adapter.
- **Name and prefixes:** Parsemaxxing, internal prefix `pmx`, add-on prefix `TA-parsemaxxing-`; add-ons built before the rename keep `TA-parsewright-` and are never renamed in place.
- **Licence:** PolyForm Shield 1.0.0 for v2; v1.0.0 and earlier stay MIT. Generated add-ons carry no Parsemaxxing licence.
- **Real log retention:** deleted 30 days after job end by default, 0 to 30 days per client, never more; masked regression sets are kept with each version (7.19).

## Lab setup v2 (OWNER ACTION, once per version)

Build the lab twice, once on 10.2.x and once on 10.6.x (the Proxmox lab can host both):

1. **Nodes:** a standalone sandbox; a search head cluster of 3 members with a deployer; two heavy forwarders, one of them also the deployment server for one universal forwarder (the HF-DS); a separate deployment server that manages the HFs (the other HF is its client); indexers, clustered or not (read-only for Parsemaxxing).
2. **Indexes:** the shared `pmx_test` index on the sandbox and on the indexers (so HF tests can be searched), plus one customer-style index such as `cus_acme_web` with a few synthetic events, and a second one such as `cus_globex_web` that the read role must not see.
3. **Packages folder:** on the sandbox, `PARSEMAXXING_PACKAGES_DIR` as in Q6 (owned by the probe user, mode 755, readable by `splunk`). The write probes that install from a host path use it.
4. **Roles and tokens:** a candidate `parsemaxxing_read` role (capability `search`, indexes `cus_acme_*` and `_internal`, no inheritance) and a `parsemaxxing_deploy` role per node, starting from Q9's final role and trimmed by Q12. One token each.
5. **Certificates:** give each node a certificate from a lab CA and keep the CA bundle for `--ca-file`. Use `--insecure-skip-tls-verify` only for a node that still has Splunk's default certificate, and record that in the evidence.

## Running the v2 probes (OWNER ACTION)

The probes read tokens only from the environment, never from arguments (other users can read command lines). Type them without echo, so they stay out of the shell history:

```bash
read -rs PMX_LAB_READ_TOKEN && export PMX_LAB_READ_TOKEN
read -rs PMX_LAB_DEPLOY_TOKEN && export PMX_LAB_DEPLOY_TOKEN
export PMX_LAB_CA_FILE=/path/to/lab-ca.pem      # or --ca-file per run
.venv/bin/python -m parsemaxxing.tools.probes.probe_topology --host <node>
```

- Every probe verifies TLS by default, has a per-call timeout (`--timeout`, default 30 s) and caps search rows at 200.
- Read-only probes: `probe_topology`, `probe_read_role`, `probe_readback`, `probe_cim`, `probe_retention` (without `--roll`), `probe_delivery shc-calls`. They use only `PMX_LAB_READ_TOKEN`.
- Write probes refuse to run without `--lab-write` (a statement that the node is a lab node, never production), install only throwaway apps whose names end in `__test_probe`, ingest only into a `pmx_` index, and uninstall what they installed. They are `probe_remote_install`, `probe_delivery shc-push|ds-map|ds-unmap`, `probe_overlay`, `probe_formats` and `probe_retention --roll`.
- No probe runs in CI. The unit tests (`engine/tests/tools/test_lab_probes.py`) cover the pure helpers only.
- Paste the output under the right version's **Evidence**. Hosts, members and clients print as `h-<hash>`; error messages are scrubbed of IPs, host names and token-like strings, but read them once before pasting.

## Q12. Remote standalone install

- **Question:** can `apps/local` install a package that is not on the Splunk host's disk (from a URL, or an upload), or must the relay stage it first? Which capabilities does it need, and can that be narrower than `admin_all_objects` (R8)?
- **Why it matters:** blocks the Phase 18 adapters for a standalone search head, a non-clustered search head and a heavy forwarder installed directly (including the HF-DS). v1 installs from a shared folder on the same host (Q6), which a remote production node does not have. If REST cannot fetch, every direct install needs the relay.
- **Lab setup:** the standalone sandbox and one HF; this machine reachable from them on one TCP port; the deploy role from Q9.
- **Probe steps:** `probe_remote_install --host <node> --lab-write --serve-bind <this machine's lab address> --serve-port 8765`
  1. Builds a props-only add-on `TA-parsemaxxing-acme-remote__test_probe` and serves only that file over HTTP for the probe's duration.
  2. `POST /services/apps/local` with `name=<url>`, `filename=true`, `update=true`; then `POST /services/apps/appinstall` with the same URL.
  3. After each: was the file fetched (served count), does `GET /services/apps/local/<app>` show it and its version, and does `GET /services/messages` hold a restart message.
  4. On a node with the deployment server role (the HF-DS): `deployment/server/clients` count before and after (see Q14).
  5. Repeat with the deploy role trimmed one capability at a time (`admin_all_objects`, `install_apps`, `edit_local_apps`, `rest_apps_management`) and record the smallest set that still installs.
  6. Manual: try an upload through Splunk Web's app install page with the deploy user, to see whether any upload path exists for a token (Splunk Web uses a session, so it is not a REST option).
- **What decides what:** URL install works with a token → the adapter installs over REST from a short-lived, single-file, hash-named URL served by Parsemaxxing (only to that node, TLS if Splunk requires it), and the relay is not needed for direct installs. Only `http` refused but `https` accepted → serve over TLS. Nothing fetches → direct installs go through the relay (`stage`, then a local `apps/local` install from the staged path). The capability set found becomes the generated `parsemaxxing_deploy` role; if `admin_all_objects` stays required, it stays a recorded residual risk.
- **Expectation:** `apps/local` accepts a URL with `filename=true` on some versions; it may require HTTPS or a Splunkbase-style source.
- **Probe script:** `probe_remote_install`.
- **Status:** open — awaiting owner lab run.
- **Evidence 10.2:**
- **Evidence 10.6:**
- **Decision:**

## Q13. Search head cluster deployer push

- **Question:** does the `apps/deploy` endpoint on the deployer work on 10.2 and 10.6 with a token? How does `deployer_push_mode` behave for an add-on with no `local/`? How is a member's effective props read for the `local/` override check?
- **Why it matters:** blocks the Phase 18 SHC adapter. Design 7.2 says the deployer push goes through the relay (`apply-shc`, CLI `splunk apply shcluster-bundle`) unless the lab proves the endpoint on the target version. The impact analysis reads `local/` overrides from a member.
- **Lab setup:** the 3-member SHC and deployer; a probe app placed by hand in the deployer's `etc/shcluster/apps/` (no `local/`); `PMX_LAB_DEPLOY_TOKEN` for a deploy user on the deployer.
- **Probe steps:**
  1. Run the CLI push once by hand on the deployer: `splunk apply shcluster-bundle -target https://<member>:8089` (log in with `splunk login`, never `-auth`).
  2. `probe_delivery --host <deployer> shc-calls` (read token): lists the `splunkd_access` calls the CLI made (`*/apps/deploy*`, `*/shcluster/*`), with method and status, so the probe repeats exactly what the CLI does.
  3. `probe_delivery --host <deployer> --lab-write shc-push --member https://<member>:8089`: `POST /services/apps/deploy` with `target`, `action=all`, `advertising=true` and a token; then `GET /services/shcluster/status`. Adjust the parameters to what step 2 showed.
  4. `deployer_push_mode`: set it in the probe app's `app.conf` `[shclustering]` stanza to `full`, `merge_to_default` (the default), `local_only` and `default_only` in turn, push, and on a member run `probe_readback --host <member> --app <app> --sourcetype <st>` plus, by hand, `splunk btool props list <st> --debug` to see which directory each setting landed in.
  5. Override check: on one member add a `local/` value by hand (Splunk Web on that member), then run `probe_readback` on that member and compare the app-context and global answers and the `eai:acl` app.
  6. Relay CLI path (by hand, recorded for the command library): `splunk login` on stdin, `apply shcluster-bundle`, `splunk logout`; also try the local REST call `https://127.0.0.1:8089/services/apps/deploy` with the token on the deployer (design 7.2 Splunk login order (a) vs (b)).
- **What decides what:** endpoint works with a token on both versions → it may be used, behind a version check that names the versions recorded here; otherwise the relay runs the CLI. Local REST with the token works on the deployer → relay order (a), else (b) `splunk login` on stdin. The `deployer_push_mode` result fixes what `app.conf` the TA builder writes for SHC targets (expected: nothing, since the package has no `local/`). The member read-back that shows `local/` overrides becomes the impact-analysis read.
- **Expectation:** `apps/deploy` exists but is undocumented; with `merge_to_default` and no `local/` the member receives `default/` unchanged; `configs/conf-props` on a member returns merged values with no default/local origin, so the override check compares the member's effective values with the package's `default/`, as Q11 does on a standalone.
- **Probe script:** `probe_delivery` (`shc-calls`, `shc-push`), `probe_readback`.
- **Status:** open — awaiting owner lab run.
- **Evidence 10.2:**
- **Evidence 10.6:**
- **Decision:**

## Q14. Deployment server for heavy forwarders (Q15 merged here)

- **Question:** can an app be mapped to a server class of HFs and the DS reloaded over REST, or only through the relay? How does the planner read each server class's clients so it refuses a class with universal forwarder clients? Does an HF that is also the UF deployment server (HF-DS) need a restart or reload after an app install?
- **Why it matters:** blocks the Phase 18 DS adapter and the relay's `ds-map` and `ds-reload` verbs, and the tier rule's safety check (never a server class with UF clients, design 7.2).
- **Lab setup:** the DS for HFs with one HF as its client; the HF-DS serving one UF; a probe app placed by hand in the DS's `etc/deployment-apps/` (the relay's `stage` step does this in managed mode).
- **Probe steps:**
  1. `probe_topology --host <DS for HFs>` and `--host <HF-DS>`: `GET deployment/server/clients`, `deployment/server/serverclasses`, `deployment/server/applications`. It prints which client fields exist that could tell a UF from an HF (`package`, `build`, `utsname`, `splunkVersion` and others) with their product values, client names hashed. Record which field says "universal forwarder" on each version.
  2. `probe_delivery --host <DS for HFs> --lab-write ds-map --client <HF client name> --app <probe app>`: refuses unless that one client is proven not to be a UF, then `POST deployment/server/serverclasses` (`name=pmx_probe_hf__test_probe`, `whitelist.0=<client>`), `POST deployment/server/applications/<app>` (`serverclass=…`), `POST deployment/server/config/_reload`.
  3. On the HF: `probe_readback --host <HF> --app <probe app> --sourcetype <st>` once the client has phoned home; record the time it took and whether the app needed a restart (`restartSplunkd` in the server class app settings, and `GET messages`).
  4. `probe_delivery ... ds-unmap` to remove the probe server class. Then repeat by hand with the CLI (`splunk reload deploy-server -class pmx_probe_hf__test_probe`) for the command library.
  5. HF-DS: `probe_remote_install --host <HF-DS> --lab-write ...` (Q12) installs into the HF-DS's own apps; it reports restart messages and whether the UF client count changed; then check by hand that the UF did not receive the app (`splunk list deploy-clients` and the UF's `etc/apps`).
- **What decides what:** REST map and reload work with a token → the DS adapter uses REST; otherwise the relay's `ds-map`/`ds-reload`. The UF-identifying client field becomes the planner's check; if no field identifies a UF reliably, the planner refuses any server class whose clients it cannot classify and the admin confirms each HF client by hand. The HF-DS result decides whether the plan flags a restart for it.
- **Expectation:** the server class and application endpoints accept writes with `edit_deployment_server` (or `admin_all_objects`); client entries carry a field naming the package type on newer versions; an HF-DS needs no restart for a props-only app.
- **Probe script:** `probe_topology`, `probe_delivery` (`ds-map`, `ds-unmap`), `probe_remote_install`, `probe_readback`.
- **Status:** open — awaiting owner lab run.
- **Evidence 10.2:**
- **Evidence 10.6:**
- **Decision:**

## Q15. (Merged into Q14)

The deployment server for HFs is covered by Q14.

## Q16. Read account

- **Question:** what is the smallest role that can run discovery searches, read `_internal` parser warnings for given sourcetypes and read `configs/conf-props`? Can a search filter restrict `_internal` to the parser components?
- **Why it matters:** blocks the generated role script (`parsemaxxing_read`) in Phase 12, discovery (Phase 17), drift collection and post-deploy verification.
- **Lab setup:** the candidate `parsemaxxing_read` role (capability `search`, indexes `cus_acme_*` and `_internal`, no inheritance), a token for it, a sourcetype with events in `cus_acme_web`, and `cus_globex_web` outside its allowlist.
- **Probe steps:** `probe_read_role --host <sh> --index cus_acme_web --other-index cus_globex_web --sourcetype <st>`
  1. `authentication/current-context`: capability list; fails if any write capability is held (`admin_all_objects`, `install_apps`, `edit_tcp`, `indexes_edit`, `can_delete`, `edit_deployment_server` and others).
  2. The discovery reads, each with status and row count: `tstats` volume by host, samples with `len(_raw)`, `_indextime - _time`, `fieldsummary`, parser warnings (`index=_internal sourcetype=splunkd log_level=WARN component IN (LineBreakingProcessor DateParserVerbose AggregatorMiningProcessor) "<st>"`).
  3. Negative: `| tstats count where index=cus_globex_web` must be 0.
  4. REST reads: `configs/conf-props`, `apps/local`, `datamodel/model`, `data/indexes`; and whether `| rest` works from SPL for this role.
  5. Search filter: add a role search filter for `_internal` (for example `index=_internal component IN (…) OR index!=_internal`; Splunk applies role filters to every search, so check it does not hide customer data), rerun, and compare the "other components" count.
  6. Remove capabilities one at a time and record the first failure of each read.
- **What decides what:** the smallest capability set where every read in step 2 and 4 passes and step 3 stays 0 becomes the generated `parsemaxxing_read` role. If the filter can restrict `_internal` without hiding customer data, the script includes it; if not, the role keeps `_internal` and the tenant base-search helper is the only restriction (recorded as residual risk). `list_all_objects` is recorded explicitly (Q9 found it needed for `configs/conf-*` reads on a clean install).
- **Expectation:** `search` plus `list_all_objects` (and `rest_properties_get` for REST reads) is enough; a role search filter applies to all indexes, so restricting only `_internal` needs a filter written as `(index!=_internal) OR (component IN (…))`.
- **Probe script:** `probe_read_role`.
- **Status:** open — awaiting owner lab run.
- **Evidence 10.2:**
- **Evidence 10.6:**
- **Decision:**

## Q17. Post-deploy verification

- **Question:** what can be read back per tier over REST to prove the effective settings after a deployment?
- **Why it matters:** blocks every adapter's `verify` step in Phase 18 (installed version and hash, effective settings on a search head and on the parsing tier).
- **Lab setup:** a probe add-on installed on the standalone, pushed to the SHC (Q13) and to an HF directly and through the DS (Q14); the read token on each node.
- **Probe steps:** `probe_readback --host <node> --app <app> --sourcetype <st> [--transform <name>]` on the standalone, one SHC member, the deployer, each HF and the HF-DS. It reads `apps/local/<app>` (version and any hash-like field), `configs/conf-props/<st>` in the app's context, the `search` app's context and globally, `properties/props/<st>`, the transform in app and global context, and lists every app defining the stanza with its `eai:acl` app.
- **What decides what:** per tier, the reads that return the package's values become the `verify` reads. Where nothing can be read back (an HF without a REST read account, or a deployer that does not apply the app), `verify` relies on the smoke search on new events and says so. If no hash is exposed, verification compares version plus effective settings, and the package hash stays proven only at delivery (relay `stage` or REST install).
- **Expectation:** version is readable everywhere, no install hash is exposed; members and HFs return merged effective settings in app context; the deployer shows nothing for `etc/shcluster/apps`.
- **Probe script:** `probe_readback`.
- **Status:** open — awaiting owner lab run.
- **Evidence 10.2:**
- **Evidence 10.6:**
- **Decision:**

## Q18. SSH library for the relay client (desk research)

- **Question:** `asyncssh` or `paramiko` for the engine side of the relay connection?
- **Why it matters:** Phase 18 relay client: Ed25519 keys from the vault, a pinned host key, the forced-command verbs with a package or a Splunk token on stdin, and output streamed line by line to the live console over server-sent events. A new library needs a line in the design's tech stack table (D8).
- **Comparison:**

  | | `asyncssh` | `paramiko` |
  | --- | --- | --- |
  | Model | Native `asyncio`, fits the FastAPI engine and line-by-line streaming without threads | Blocking; needs a thread per session under `asyncio` |
  | Maintenance | Active, regular releases, one long-standing maintainer | Active, regular releases, long history and wide use |
  | Host key pinning | `known_hosts` accepts an in-memory list or a callable, so the pinned fingerprint can be enforced from the vault with no file | `MissingHostKeyPolicy` subclass with `RejectPolicy`; works, easy to misconfigure as `AutoAddPolicy` |
  | Keys | Ed25519 import from memory, no file needed | Ed25519 supported; import from memory works |
  | Licence | EPL-2.0 (GPL-2.0-or-later as secondary): weak copyleft at file level; using it unmodified in a commercial product is allowed | LGPL-2.1: allows commercial use as an unmodified, separately installed library |
  | CVE history (client relevant) | CVE-2023-46445, CVE-2023-46446 (rogue session and extension attacks, fixed in 2.14.1), CVE-2023-48795 (Terrapin, mitigated in 2.14.2); an older server-side authentication bypass does not affect a client | CVE-2023-48795 (Terrapin, fixed in 3.4.0), CVE-2022-24302 (race when writing private key files), older server-side authentication bypasses (CVE-2018-1000805, CVE-2018-7750) that do not affect a client |

- **Recommendation: `asyncssh`.** It streams relay output natively in the engine's event loop, pins host keys from memory without a `known_hosts` file, and loads the key from the vault without writing it to disk. Its CVE record is short and fixed promptly; Terrapin hit both libraries. Pin a minimum version above the Terrapin fix, enable only strict key exchange, and let `pip-audit` gate upgrades as for every dependency. The EPL-2.0 licence allows commercial use; Parsemaxxing uses it unmodified, so no source obligations arise.
- **To check at decision time:** this comparison reflects public advisories up to its writing; rerun `pip-audit` and the OSV database for both before confirming.
- **Status:** proposed, owner to confirm.
- **Decision:**

## Q19. Embedding model and chart library (desk research)

- **Question:** which embedding model for the offline knowledge base (local ONNX, D4) and which chart library for the analytics UI, both with licences that allow commercial use?
- **Why it matters:** the knowledge base (7.12) ships the embedding model with Parsemaxxing, so its licence ships too; the analytics pages (7.8) need charts in the Next.js and shadcn/ui stack. The owner plans to commercialise, so non-commercial licences are out.
- **Embedding model options:**

  | Model | Licence | Size, dimensions | Notes |
  | --- | --- | --- | --- |
  | `BAAI/bge-small-en-v1.5` | MIT | about 33 M parameters, 384 | Strong retrieval quality for its size, ONNX exports available, CPU-friendly |
  | `sentence-transformers/all-MiniLM-L6-v2` | Apache-2.0 | about 22 M, 384 | Smaller and faster, weaker on retrieval benchmarks |
  | `nomic-embed-text-v1.5` | Apache-2.0 | about 137 M, 768 | Better quality, long context, slower on CPU, needs task prefixes |
  | Models under CC BY-NC (for example some newer multilingual embedding models) | Non-commercial | | Excluded |

- **Recommendation: `bge-small-en-v1.5`**, run with ONNX Runtime (MIT), pinned by file hash, with its licence file shipped next to the weights. It runs on servers without a GPU, keeps pgvector rows small (384 dimensions) and its licence allows commercial use and redistribution. Fallback: `all-MiniLM-L6-v2` if CPU time is the constraint. The corpus is English (`.spec` files, CIM descriptions), so a multilingual model brings nothing.
- **Chart library options:** Recharts (MIT; shadcn/ui's chart components are built on it), Apache ECharts (Apache-2.0), Highcharts (commercial licence required: excluded).
- **Recommendation: Recharts**, through shadcn/ui's chart components, so charts follow the existing theme and accessibility patterns and no second styling system is added. ECharts only if a chart type Recharts lacks becomes necessary.
- **Status:** proposed, owner to confirm. Both need a line in the design's tech stack table (D8).
- **Decision:**

## Q20. W3C/IIS and other header-defined formats

- **Question:** for W3C/IIS and CSV, search-time `DELIMS`/`FIELDS` (header lines are still indexed as events) or `INDEXED_EXTRACTIONS` (handles headers, but must live on the forwarder or first parsing tier and stores fields as indexed fields)? How are header lines kept out of CIM data models without `nullQueue`?
- **Why it matters:** blocks the formats work (7.17) for W3C, CSV and delimited formats: the gate keys `INDEXED_EXTRACTIONS`, `TIMESTAMP_FIELDS` and `HEADER_FIELD_LINE_NUMBER` are allowed only if this decides for them, and then the plan must place them on the parsing tier. Q4 kept `INDEXED_EXTRACTIONS` out of v1.
- **Lab setup:** the standalone sandbox, `pmx_test`, the packages folder; the read and deploy tokens.
- **Probe steps:** `probe_formats --host <sandbox> --lab-write --index pmx_test [--oneshot]`
  1. Installs one add-on with four sourcetypes: W3C with `REPORT-` to `DELIMS = " "` and `FIELDS`, W3C with `INDEXED_EXTRACTIONS = w3c`, CSV with `DELIMS = ","`, CSV with `INDEXED_EXTRACTIONS = csv` and `TIMESTAMP_FIELDS`. Each has an eventtype that excludes the header lines by term.
  2. Sends a synthetic file of each (four `#` directive lines plus three events for W3C; a header row plus three rows for CSV) through `receivers/simple`, and with `--oneshot` also through `data/inputs/oneshot` from the packages folder, since structured extraction is expected to run only where a file is read.
  3. Per sourcetype and path: event count (expect 3), header lines indexed as events, events with `cs_uri_stem`, indexed hits (`| tstats count where … cs_uri_stem=*`) and events kept by the header-excluding eventtype.
  4. Manual, if `INDEXED_EXTRACTIONS` wins: put the same sourcetype on the HF that reads a monitored file and confirm the fields arrive indexed on the indexers with the search head seeing them.
- **What decides what:** if `INDEXED_EXTRACTIONS` applies only on file inputs, the sandbox test must ingest with oneshot for those formats and the plan must put the stanza on the HF (or UF) that reads the file; if the eventtype filter keeps header lines out of `tag=` searches, CIM mapping uses it and `nullQueue` stays unused. Otherwise search-time `DELIMS`/`FIELDS` with the eventtype filter is the default and header lines are counted and excluded by the Validator.
- **Expectation:** `receivers/simple` does not apply `INDEXED_EXTRACTIONS`; oneshot does; the eventtype filter excludes header lines from data model searches.
- **Probe script:** `probe_formats`.
- **Status:** open — awaiting owner lab run.
- **Evidence 10.2:**
- **Evidence 10.6:**
- **Decision:**

## Q21. `datamodel/model` vs the package JSON

- **Question:** what does `datamodel/model` return on 10.2 and 10.6 (fields, `expected_values`, constraints, child datasets) compared with the same version's package JSON, so the local-changes check compares like with like? Does `apps/local/Splunk_SA_CIM` give the exact x.y.z version to the read account?
- **Why it matters:** blocks the CIM library's same-version rule and local-changes check (7.16), and the deployment plan's CIM re-check.
- **Lab setup:** the CIM add-on installed on the sandbox and the SHC; the same version's package downloaded by the owner and extracted outside the repo (only `default/data/models/*.json`; never committed); the read token.
- **Probe steps:** `probe_cim --host <sh> --package-dir <extracted>/default/data/models`
  1. `GET apps/local/Splunk_SA_CIM`: version, and whether it has three parts.
  2. `GET servicesNS/nobody/Splunk_SA_CIM/datamodel/model`: number of models and the content keys (which key holds the JSON: `eai:data`, `description` or other).
  3. Per model, a normalized summary (per dataset: parent, constraint searches, fields with type, `recommended` and `expected_values`, calculated output fields) and its hash, for REST and for the package file; same hash or the datasets present on one side only.
  4. Edit one model by hand on a member (add a field), rerun, and confirm only that model's hash changes.
- **What decides what:** same hashes on an unmodified install → the local-changes check compares normalized summaries by hash. Differences on an unmodified install (for example REST drops `comment` or `expected_values`) → the normalizer records which parts REST cannot give and the check compares only those parts, with a test written for each difference. If the read account cannot read the version, the generated role gets the missing capability or the admin enters the version.
- **Expectation:** REST returns the same JSON as the package in `eai:data`, so hashes match; `expected_values` survive.
- **Probe script:** `probe_cim`.
- **Status:** open — awaiting owner lab run.
- **Evidence 10.2:**
- **Evidence 10.6:**
- **Decision:**

## Q22. CIM compatibility on 10.2 and 10.6

- **Question:** confirm the owner-provided table (D10: 10.2 to 10.6 support `Splunk_SA_CIM` 6.3.0 and later; 10.7 and later need 8.5.0 and later) by installing the oldest allowed CIM (6.3.0) and the newest on 10.2 and 10.6, and check that the CIM normalizer reads 6.x and 8.x definitions the same way.
- **Why it matters:** fixes the compatibility table in `environments/versions.py` and `docs/setup.md`, and the normalizer's tests (7.16). The table is settled; the lab records evidence and any format difference.
- **Lab setup:** the sandbox on 10.2 and on 10.6; CIM 6.3.0 and the newest CIM, installed one at a time; both packages extracted outside the repo.
- **Probe steps:**
  1. For each (Splunk, CIM) pair: install the CIM add-on, check `GET messages` and the Splunk Web app page for errors, then `probe_cim --host <sandbox> --package-dir <that version's models>`; it prints the minimum for that Splunk version and whether the installed CIM meets it.
  2. Run `| tstats summariesonly=false count from datamodel=Authentication` and `Network_Traffic` on `pmx_test` with the search token.
  3. Compare the 6.3.0 and newest summaries per model: datasets, field keys, where `expected_values` and `recommended` live.
- **What decides what:** every difference in layout between 6.x and 8.x becomes a normalizer test with a definition file written for the test (never Splunk's file); a CIM version that fails to install on a supported Splunk version narrows the table and goes back to the owner.
- **Expectation:** both install cleanly; the JSON layout is the same, with more models and fields in 8.x.
- **Probe script:** `probe_cim` (plus manual installs).
- **Status:** open — awaiting owner lab run.
- **Evidence 10.2:**
- **Evidence 10.6:**
- **Decision:**

## Q23. Overlay precedence

- **Question:** on 10.2 and 10.6, which app name and placement make an overlay's `props`/`transforms` settings win over another app's for the same sourcetype stanza: at index time on a heavy forwarder, and at search time on a standalone search head and a search head cluster member? How is the effective value read back per tier to prove it?
- **Why it matters:** blocks overlays (7.18). If the standard name `TA-parsemaxxing-overlay-<vendor>-<product>` does not win, the name follows this result and the naming rule and the gate's name check are extended to that one pattern, with adversarial tests.
- **Background (Splunk's documented precedence, to be confirmed):** in the global context (index time), system `local/` wins, then every app's `local/`, then every app's `default/`, then system `default/`; between apps, directory names in ASCII order decide (uppercase before lowercase, the earlier name wins). Search time uses the app/user context, where the current app wins over other apps. So an overlay named `TA-parsemaxxing-…` would lose to a vendor app named `Splunk_TA_…` or `TA-acme…` in `default/` versus `default/`.
- **Lab setup:** the standalone sandbox; one HF plus a search head that sees `pmx_test` on the indexers; one SHC member; the packages folder on the node under test.
- **Probe steps:** `probe_overlay --host <node> --lab-write --index pmx_test [--search-host <sh>] [--vendor-name …] [--overlay-name …]`
  1. For each simulated vendor app (default `Splunk_TA_acmeprobe__test_probe`, which sorts before `TA-`, and `zz_acmeprobe__test_probe`, which sorts after), each overlay name (default `TA-parsemaxxing-overlay-acme-probe__test_probe`) and each placement of the overlay's settings (`default/` or `local/`): install both, ingest one event, and record the index-time winner (`TZ`: `UTC` for the vendor, `Pacific/Chatham` for the overlay, read from `_time`), the search-time winner (`EVAL-pmx_winner`) and the global REST value.
  2. Try other overlay names that sort first (for example a name starting with an uppercase letter or a digit) with `--overlay-name`, if the standard name loses in `default/`.
  3. On a SHC member: push both apps through the deployer (Q13) and run `probe_readback` and the same search there.
  4. By hand, on each node: `splunk btool props list pmx_probe_ovl__test_probe --debug` to see the winning file.
  5. Package `local/` placement: also check what `update=true` does to an overlay package's own `local/` on reinstall (Q11 showed it keeps an admin's `local/`; a package-supplied `local/` may then never update).
- **What decides what:** the name and placement that win on every tier for both vendor names, on both versions, become the overlay rule. `local/` placement conflicts with the rule that `local/` belongs to admins (Q6, Q11) and probably breaks updates, so it is chosen only if no `default/` name works and the owner accepts it. The read-back that shows the winner per tier becomes the gate's "setting takes effect" check.
- **Expectation:** in `default/`, the standard overlay name loses to `Splunk_TA_…` and wins over `zz_…`; an overlay in `local/` wins over any vendor `default/` at index time.
- **Probe script:** `probe_overlay`, `probe_readback`.
- **Status:** open — awaiting owner lab run.
- **Evidence 10.2:**
- **Evidence 10.6:**
- **Decision:**

## Q24. Removing one job's events without `delete`

- **Question:** what is the cleanest way to remove one job's events from the sandbox's `pmx_` test index on 10.2 and 10.6 without giving Parsemaxxing's search account the `delete` capability: short index retention, a per-job index rolled and frozen, or `splunk clean eventdata` on a dedicated job index in a maintenance window? What is the effect on concurrent jobs?
- **Why it matters:** blocks the retention purge (7.19): real events in the sandbox index count as real logs and must be gone within 30 days of job end.
- **Known conflict to resolve:** 7.19 asks for `frozenTimePeriodInSecs` of at most 30 days, but Q9 chose a size cap instead of age-based retention because sample events carry historical timestamps: Splunk freezes a bucket by its newest event's `_time`, not by when it was indexed, so old samples could freeze before the Validator reads them. The probe measures how many events that would affect.
- **Lab setup:** the sandbox, `pmx_test` with events from at least two probe sourcetypes (two "jobs"), the read token; the deploy token for `--roll`.
- **Probe steps:** `probe_retention --host <sandbox> --index pmx_test [--lab-write --roll --wait 120]`
  1. `GET data/indexes/pmx_test`: `frozenTimePeriodInSecs`, `maxTotalDataSizeMB`, `maxHotSpanSecs`, `maxHotBuckets`, `maxDataSize`, event count, size, `coldToFrozenDir`; verdict against 30 days.
  2. `| dbinspect index=pmx_test | stats count by state`.
  3. Per sourcetype: count, `_time` range, the gap between first `_time` and first `_indextime`, and how many events are older than the retention period.
  4. `--roll`: `POST data/indexes/pmx_test/roll-hot-buckets`, wait, reread step 3, and report every sourcetype whose count changed (the effect on other jobs).
  5. Manual: on a dedicated `pmx_job_<id>` index, stop Splunk in a maintenance window and run `splunk clean eventdata -index pmx_job_<id> -f`; record downtime and whether other indexes were touched. Note that creating per-job indexes conflicts with Q9 (the engine never creates or deletes indexes).
- **What decides what:** if rolled buckets with old `_time` freeze at once, age-based retention cannot be the purge mechanism for historical samples; the options become (a) a size cap plus ingesting samples with `_time` rewritten to ingest time only for retention purposes (which breaks timestamp checks, so likely no), (b) a small set of pre-created rotating `pmx_` indexes (for example one per week) cleaned in a maintenance window, or (c) accepting retention by `_indextime` through `maxHotSpanSecs` and bucket rolling. The chosen option must not affect a running job's events.
- **Expectation:** rolled buckets whose newest event is older than `frozenTimePeriodInSecs` freeze at the next retention check, taking other jobs' old-timestamp events with them.
- **Probe script:** `probe_retention`.
- **Status:** open — awaiting owner lab run.
- **Evidence 10.2:**
- **Evidence 10.6:**
- **Decision:**
