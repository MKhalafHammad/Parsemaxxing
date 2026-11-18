# demo

Repeatable scenario scripts. Each one runs a known scenario end to end against the local stack (a fix loop, a guardrail block, parallel jobs, a parser update), so anyone can re-run it and see the same behaviour, and a phase can check that older scenarios still work.

## Conventions

- One script per scenario, numbered: `NN_short_name.sh`, for example `01_fix_loop.sh`.
- Each script:
  - uses only synthetic logs: the fixtures in `engine/parsemaxxing/generator/fixtures/`, or fresh ones from the generator;
  - reads its configuration from `.env` and, for the API scripts, `PARSEMAXXING_API` and `PARSEMAXXING_UI` (defaults: the local engine and UI);
  - never prints tokens or keys.
- Scripts write only to the `pmx_` test index and `__test_<job>` apps, like the rest of Parsemaxxing; the engine removes each run's test add-on when the run ends. Nothing is promoted unless you approve it.
- The top of each script states what it shows, its prerequisites (lab running, tokens set) and roughly how long it takes.

## Scenarios

| Script | Scenario | Phase | Last checked |
| --- | --- | --- | --- |
| `01_fix_loop.sh` | First agent fix loop: TZ = UTC is caught as a +32400 s offset, attempt 2 sets Asia/Tokyo and passes | 2 | Run in the lab, Oct 27 |
| `02_cim_green.sh [vpn\|fw\|ssh\|proxy]` | First green CIM check: all three stages, the holdout line and the three CIM numbers | 3 | All four fixtures green in the lab, Oct 28 |
| `03_guardrail_block.sh` | Prompt-injection log; a simulated compromised model's CIM proposal blocked by the gate, a subtler constant caught by the Validator, then the real model recovers | 4 | Run in the lab, Oct 28 (the real model ignored the injection; the attacker proposals are simulated and labelled) |
| `04_parallel_jobs.sh` | Four uploads at once, four workers in parallel; one pauses for profile review while the others continue, then resumes on confirm | 5 | Run in the lab, Oct 28: all four reached awaiting approval in ~5 min |
| `05_approval_report.sh` | The approval report: raw vs parsed with highlights, mapping, CIM scores and configs; a `<script>` log line shown as plain text; approve and download | 6 | Run in the lab, Oct 28 (job reached awaiting approval with a full report) |
| `06_parser_update.sh [patch\|diagnose]` | Parser update: firmware v2 samples (renamed field, ISO timestamps) against a promoted firewall TA. Diagnose finds the drift with no model call, only the failing stages are patched, a patch that breaks the old format is rejected with evidence, both formats pass, diff against production. `diagnose` after promotion: a new v2 batch ends at Diagnose with 0 tokens | 7 | Run in the lab: patch Oct 28 (job `866b4273`, 37k tokens), approved and promoted in place to 1.1.0 on Oct 30 (smoke 20/20); `diagnose` Oct 30 (job `1a0521ec`, 0 tokens); rolled back to 1.0.0 on Oct 30, so a new run starts from v1 (the update becomes 1.2.0) |
| `07_live_workspace.sh` | The agent-centred run workspace: "Needs you" on the board, profile review with change markers, then the Now banner, the clickable phase rail, each attempt's proposal, gate verdict, Splunk checks and diff from the previous attempt, and the activity grouped by phase and attempt | 7b | Script added Oct 30; screens checked with synthetic fixtures, not yet run in the lab |
| `08_log_only.sh [fw\|timezone]` | Just the log, no answer key: a fresh firewall log is built and proven on every event with no manifest, and the report lists the agents' decisions (timestamp reading, field meanings, value → CIM value with counts). `timezone`: a VPN log in local time pauses in profile review and asks for its zone | post-7 | `fw` run in the lab, Nov 2 (job `12e87e98`: mapping equal to the hidden truth, 48k tokens); `timezone` pause seen in the lab on job `99d2999e` |
