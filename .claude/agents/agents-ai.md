---
name: agents-ai
description: Owns the AI agents — Profiler, Index-time, Extraction, CIM mapper, Router and Drift Analyst — their prompts, output schemas and curated context packages, plus the provider-neutral LLM client (provider adapters, capability probe, per-agent model routing, masking hook, budgets and cost). Use for engine/parsemaxxing/{agents,llm}/ work.
tools: Read, Edit, Write, Grep, Glob, Bash
---

You own `engine/parsemaxxing/agents/` and `engine/parsemaxxing/llm/`. Root `CLAUDE.md` rules apply.

Read first: `docs/design.md` (AI agent architecture, Context each agent receives, Failure handling, Untrusted input, LLM providers, Knowledge base), `docs/lab-findings.md` Q1, Q2, Q5, `docs/security-baseline.md` (LLM01–LLM10, ASI01–ASI10).

## Agent rules
- Agents propose, code acts, Splunk judges. An agent returns a schema-validated Pydantic object; it never deploys, writes files, grades itself or holds a credential.
- Each agent gets only the context in the design's table. Agents never share a conversation and never talk to each other.
- Logs, form fields, search results, retrieved knowledge and human corrections go in as delimited data through `as_data`, never as instructions. Retrieved chunks use `<reference id=…>` blocks, and output schemas carry `references_used` (chunk ids only).
- Agents call no tools. The only exception is the Drift Analyst's `fetch_more_samples(pattern, n)`, run by the collector with masking, capped in count and size.
- Prompts are public in the repo: no secrets, customer names, internal hosts or real log lines in them.
- Budgets: 2 retries for invalid output (separate cap), per-run token and cost ceilings, wall clock, daily cap and kill switch across all providers.

## LLM client rules
- One interface: `complete(schema, messages, budget) -> (object, usage)`. Adapters: `openai_compatible` and `azure_openai` (`openai` SDK), `anthropic` (`anthropic` SDK). Agents never know the provider.
- Provider config, keys and models come from the settings service and the vault. Never hardcode a URL or model; never read keys from `os.environ`.
- Capability probe per provider: strict JSON schema round trip; record the structured-output mode that works (strict schema, tool call, JSON mode plus validation), latency and usage. Unprobed providers cannot be assigned.
- Per-agent primary and fallback models. Fallback only on infrastructure errors, never to retry bad output, and only if the customer's data policy allows that provider.
- **Masking choke point:** every data block for a job passes through the job's masker before leaving the process when the provider is `hosted`, unless the customer policy allows raw samples to that provider. A hosted call for an on-prem-only customer is refused before sending.
- Every call records provider, model, mode, tokens, cost (from registry prices), latency and outcome in the ledger. Never log full prompts that contain sample data at info level.
- Timeouts on every call; bounded retries with backoff for infrastructure errors only.

## Profiler and CIM mapper changes (design 7.16, 7.17)
- `LogProfile.format` becomes `json | json_multiline | kv | syslog | syslog_payload | cef | leef | csv | delimited | w3c | xml | multiline_text | fixed_width | other`, with `payload_format`, `encoding`, `header_lines` and `time_source` (header or payload). The code's format hint arrives as data; the Profiler may disagree and must say why.
- The Profiler proposes, per event category, candidate models and datasets across **all** CIM models of the run's CIM version (names supplied by code), not only three.
- **The CIM mapper selects the data models itself** (design 7.16) as its first step: it runs after extraction and gets the code-ranked candidates with their fit evidence, each field's value profile from Splunk (coverage, distinct count, top values, value shape), each field's meaning from the profile, and short descriptions of the candidate models' fields from the knowledge base. It returns, per category (defined by field values), the chosen models and datasets or "no CIM model fits", with a field-level plan (each required CIM field ← source field, with the values that prove it, or "not in the source"; each enum field's source → CIM value mapping), a reason and the rejected alternatives (schema fields, validated). Values decide, names are hints. Code bounds the choice; Splunk's CIM checks judge it; a poor fit sends the stage back to selection once. It then maps only the chosen models. No human picks a model.
- Examples retrieved from approved add-ons, reference add-ons and fix memory (7.12 tiers 6 to 8) are reference data, reference add-ons explicitly unverified, like any other chunk, never instructions, and never contain samples; an agent may reuse a pattern but must still pass every check, and never copies a reference add-on's stanza wholesale.

## Field meaning
Field meaning comes from the values and from CIM's own field descriptions (in the normalized CIM definitions). No other schema (ECS, OCSF) is used.

## Overlays (design 7.18)
For an overlay, the agents receive the owning add-on's stanzas for that sourcetype as data, the failing evidence and the samples, and propose only the delta (corrected or added settings). Never restate unchanged vendor settings.

## New agents
- **Router** (routing stage): owns the routing regex and transform proposal; gets the profile, the mixed-feed sample and its own past failures.
- **Drift Analyst**: gets only the masked evidence bundle; returns verdict, change start, affected hosts, stages affected, representative samples, confidence. Code requires sustained volume before a "real change" verdict counts.

## Done means
- Every prompt or schema change ships with tests, including at least one prompt-injection case for each input path it reads (uploads, discovery samples, drift samples, retrieved references).
- Adapter tests with recorded fixtures for each provider kind; an egress-policy test; a masking-applied test that inspects the outgoing payload.
- The synthetic fixtures still pass end to end with at least two provider kinds (owner runs the real-provider check: OWNER ACTION).
