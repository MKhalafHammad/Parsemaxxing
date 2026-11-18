# Data onboarding governance (design)

> **Status: planned, no code.** Skeleton written in Phase 11; the design is completed in Phase 25 ([build-plan.md](build-plan.md)). Nothing here is built, and nothing is built until the owner decides. Parent section: [design.md 7.14](design.md#714-data-onboarding-governance-design-only).

Examples use the synthetic customers `acme`, `globex` and `initech` and `example.com` hosts only.

## Scope

Sourcetype naming and index routing: how data gets its sourcetype and index before Parsemaxxing's parser add-ons apply to it. Parser add-ons (v2) are out of this document except where they meet routing.

## Where sourcetype and index are set in Splunk

To write in Phase 25, in original wording:

- At the input: `inputs.conf` on the universal forwarder, the heavy forwarder, a syslog server, or the HEC token.
- Overridden at the first full parsing tier by `props.conf` and `transforms.conf`: `DEST_KEY = MetaData:Sourcetype` for the sourcetype, `DEST_KEY = _MetaData:Index` for the index.
- Universal forwarders do not parse (except structured `INDEXED_EXTRACTIONS` and `EVENT_BREAKER`), so overrides live on heavy forwarders (D11: indexers are never a target).

Questions to answer:

- Which of these does each supported topology (7.1) use in practice, and where would Parsemaxxing read the current setting from?
- How does discovery (7.9) tell an input-level sourcetype from an overridden one?

## What Parsemaxxing could own, in order of risk

| # | Option | Who applies it | Open questions |
| --- | --- | --- | --- |
| 1 | A naming convention engine (`vendor:product[:type]`) and a report of badly named sourcetypes from discovery | Nobody (report only) | Which convention? How are existing names mapped? |
| 2 | The exact `inputs.conf` change, still applied by the input owner | The input owner | Same handoff format as deployments (7.2)? |
| 3 | Sourcetype routing add-ons (Phase 23) | Deployment pipeline | How do routing add-ons and naming rules interact? |
| 4 | Index routing per customer in MSP shared environments | Deployment pipeline | See the next section |
| 5 | Optionally, inputs apps delivered through the deployment server | Deployment pipeline | Does this conflict with D11 and the rule that Parsemaxxing never writes `inputs.conf`? |

## Why index routing is the most dangerous

In an MSP shared Splunk, a wrong index rule sends one customer's data into another customer's index. That is a data leak, not a parsing bug.

What it would need, to be designed:

- Its own add-on type, separate from parser add-ons.
- A narrow gate exception: `_MetaData:Index` only to indexes on that customer's allowlist (today the gate blocks `_MetaData:Index` everywhere).
- A negative test proving 0 events land outside the right customer's indexes.
- Mandatory four-eyes approval (D6 has it off by default; here it would be forced on).
- Licence-volume impact checks.

Questions to answer:

- How is the negative test run without real data from more than one customer in one place?
- What happens to events already indexed in the wrong index?
- Who in the MSP signs off: the platform admin, the customer, or both?

## Proposed phase plan

To write in Phase 25: which options to build, in which order, as new phases in [build-plan.md](build-plan.md), each with acceptance criteria and its adversarial tests.

## Open questions for the owner

- Which options (1 to 5) should be built at all?
- Is index routing in scope for v2.x, or only after a separate threat model?
- Which sourcetype naming convention is the default?
- Should option 2 output feed into the handoff runbook?

## Decisions

None yet. The owner records decisions here before any of this is built.
