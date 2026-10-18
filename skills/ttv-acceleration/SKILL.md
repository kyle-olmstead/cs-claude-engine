---
name: ttv-acceleration
description: >
  This skill should be used when the user says "[account] is stuck in onboarding", "[account]
  hasn't gone live", "time to value on [account]", "unblock [account]'s implementation",
  "onboarding is stalled at [account]", "why hasn't [account] reached first value", "TTV
  acceleration", or when a book review flags PB-ADP-01. It diagnoses the blocker for an onboarding
  account that has passed its segment's p75 time-to-value without a value milestone, assigns
  owners on both sides, sets a milestone target date, and drafts one approval-gated check-in.
metadata:
  version: "1.1.0"
  playbook_id: "PB-ADP-01"
---

# TTV acceleration (PB-ADP-01)

Follow `${CLAUDE_PLUGIN_ROOT}/skills/customer-360/references/playbook-protocol.md` with these specifics.

## When it applies

`lifecycle.stage == "onboarding"`, `lifecycle.value_milestones_reached == []`, and `lifecycle.days_since_term_start > benchmarks.ttv_p75_days`. If a milestone has been reached, say so and offer `feature-depth-audit` instead. If the account is simply early (under p50), say that too — the engine does not chase week-one accounts.

## Inputs beyond the Customer 360

- `value_milestone_definitions_json` — from `~~product analytics` milestone definitions when the connector exposes them, else the plugin default `DEFAULT_VALUE_MILESTONES` in `${CLAUDE_PLUGIN_ROOT}/src/orchestrator.py`. Tell the user which was used.
- Onboarding history: `lifecycle.onboarding_steps[]`, `lifecycle.kickoff_notes`, sessions from `~~calendar`, onboarding-tagged tickets from `~~support desk`, and `integration`/`onboarding` themes from transcript signals. Pull these into the document before running if they are empty.

## Prompt

`${CLAUDE_PLUGIN_ROOT}/prompts/adoption/ttv_acceleration.prompt`. Classify the blocker from the taxonomy in the prompt; the blocker is the earliest unmet prerequisite of the nearest milestone unless evidence shows motion stopped for another reason.

## Artifacts

- `PB-ADP-01.ttv_acceleration.action.json` with the `onboarding_plan` block
- `PB-ADP-01.ttv_acceleration.comm_1.md` — check-in to the customer-side owner (approval required)
- `PB-ADP-01.unblock_plan.md` — the plan as a one-pager: blocker, owners, three to five dated actions, milestone target date, first-win statement

## Proposed writes

- ~~crm: `onboarding_risk_tier` (watch / at_risk / stalled) on the account; a task to the implementation owner for each vendor-side action.
- ~~support desk: when the blocker is `technical_integration` or `vendor_delay`, a ticket *draft* tagged `onboarding-blocker` with the prerequisite named — created only on approval.
- ~~calendar: a proposed configuration/training session on the date the plan names.

## Rules specific to this playbook

- Do not propose a kickoff for an account that already had one.
- Do not assign an action to a customer contact who has been silent 45+ days without a re-engagement step first.
- Do not recommend paid services; you may note the blocker is of the kind professional services typically clears.
