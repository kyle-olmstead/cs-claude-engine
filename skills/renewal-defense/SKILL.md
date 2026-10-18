---
name: renewal-defense
description: >
  This skill should be used when the user says "prep the [account] renewal", "renewal plan for
  [account]", "is [account] going to renew", "[account] renews in N days", "renewal defense",
  "right-size scenario for [account]", "what's our renewal outlook on [account]", or when a book
  review flags PB-RET-02. It builds the standard renewal defense plan for an account inside the
  120-day window that is yellow, under-utilized, or recently contracted but not red: the three
  scenarios with GRR-dollar impact, the stakeholder ask map, dated actions against the R-120/90/60/45/30/14
  anchors, value-story inputs, and one approval-gated kickoff draft.
metadata:
  version: "1.1.0"
  playbook_id: "PB-RET-02"
---

# Renewal defense (PB-RET-02)

Follow `${CLAUDE_PLUGIN_ROOT}/skills/customer-360/references/playbook-protocol.md` with these specifics.

## When it applies

`contract.days_to_renewal ≤ 120` and any of: `health.band == "yellow"`, `usage.seat_utilization < 0.50`, `contract.contraction_flag_90d == true`. If the account meets a PB-RET-01 trigger instead (red, champion departed, aged P1, ECRI ≥ 60), run `red-account-turnaround` — it includes this plan. If the renewal is more than 120 days out, say so and offer `customer-360` or `ebr-generator` (a renewal-variant EBR at R-180 is the better move).

## Prompt

`${CLAUDE_PLUGIN_ROOT}/prompts/retention/renewal_defense_playbook.prompt` with `rca_json = {}` (no RCA in the standard path). Set `playbook_id` to `PB-RET-02`. Compute `timeline_anchor_today` from `days_to_renewal`; if the R-120 or R-90 window has already passed, compress the plan and say so in the summary.

## Artifacts

- `PB-RET-02.renewal_defense_playbook.action.json`
- `PB-RET-02.renewal_defense_playbook.comm_1.md` — renewal kickoff draft to the economic buyer (or exec sponsor if no economic buyer is engaged); approval required.
- A one-page `PB-RET-02.renewal_plan.md` rendered from the action for the user's own renewal review: scenario table, stakeholder asks, timeline, value-story inputs and the measurements still needed.

## Proposed writes

- ~~crm: `cse_scenario` on the renewal opportunity (informational; never the stage, amount, close date or forecast category); task "Renewal kickoff meeting — <account>" due within 10 days; one task per unmeasured value-story input ("Measure <outcome> before R-90").
- ~~calendar: proposed hold for the value review inside the R-90 window.
- ~~email: a *draft* of comm_1 in the user's mailbox.

## Rules specific to this playbook

- Never propose pricing, discounts, free months, or term changes. "Proposal inputs" are facts, not numbers for the paper.
- Do not schedule more than one meeting per stakeholder in the first 14 days.
- For the `digital` segment the plan must be executable with automation plus one CSM touch.
