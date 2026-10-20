---
name: red-account-turnaround
description: >
  This skill should be used when the user says "[account] just went red", "run the turnaround on
  [account]", "our champion at [account] left", "[account] is at risk", "do a churn root-cause on
  [account]", "why are we losing [account]", "build a save plan for [account]", "red account
  review", or when a book review flags PB-RET-01 on an account. It runs the enterprise at-risk
  turnaround: a churn root-cause analysis (mechanism, timeline, blast radius, interrupting
  intervention) chained into a renewal defense plan (scenarios, stakeholder asks, dated actions,
  one approval-gated outreach draft), with every claim tied to a field in the Customer 360.
metadata:
  version: "1.2.0"
  playbook_id: "PB-RET-01"
---

# Red account turnaround (PB-RET-01)

Follow `${CLAUDE_PLUGIN_ROOT}/skills/customer-360/references/playbook-protocol.md` with these specifics.

## When it applies

Confirm at least one trigger holds on the Customer 360 (otherwise say which playbook fits better and offer it):

- `health.band == "red"`, or a drop of ≥ 15 points in 30 days
- `relationship.champion.status == "departed"` with no replacement
- a P1 open more than 5 days
- renewal ≤ 120 days with health < 65
- `sentiment.ecri ≥ 60`

If `actions_last_30d` or `history/actions.jsonl` shows an open PB-RET-01 inside 14 days, emit a `signal_update` instead of a new action.

## Prompt chain

1. `${CLAUDE_PLUGIN_ROOT}/prompts/retention/churn_risk_rca.prompt`: produces the diagnosis. Build the dated timeline from the last 120 days before choosing a mechanism; name one interrupting intervention; include the disambiguating question when confidence < 0.75.
2. `${CLAUDE_PLUGIN_ROOT}/prompts/retention/renewal_defense_playbook.prompt` with `rca_json` = the RCA's `diagnosis` object: produces the plan. Evaluate all three scenarios; one kickoff/continuity draft only.
3. If any NPS verbatim or call is newer than the last run and lacks a signal, run `prompts/core/sentiment_analyzer.prompt` on it first and merge the result into the document.

Before the RCA, read `${CLAUDE_PLUGIN_ROOT}/playbooks/enterprise_at_risk_turnaround.md` §2 (severity tiers) and §7 (the save conversation) so the plan's internal escalation and first-touch owner match the tier: Critical → internal exec sponsor touches within 48h; High → CSM within 72h; Elevated → 5 business days.

## Artifacts

- `PB-RET-01.churn_risk_rca.action.json`: the RCA
- `PB-RET-01.renewal_defense_playbook.action.json`: the plan
- `PB-RET-01.renewal_defense_playbook.comm_1.md`: exec continuity or renewal kickoff draft (approval required)
- An internal escalation brief: render from the two actions into `PB-RET-01.escalation_brief.md` when the tier is Critical or High. One page for leadership, written per `${CLAUDE_PLUGIN_ROOT}/skills/customer-360/references/writing-standard.md`: the account in brief, what happened and why, what is at stake, what we need from whom by when, and the ask of leadership.

## Proposed writes (offered, never automatic)

- ~~crm: `cse_risk_tier = red_<driver>` on the account; task "Red account review: <account>" for the CSM and CS leader, due 2 days; `cse_scenario` on the renewal opportunity.
- ~~chat: P0 alert to the red-accounts channel named in the stack profile (summary, confidence, items awaiting approval).
- ~~calendar: a proposed hold for the exec continuity meeting inside the first-touch window.
- ~~documents: save the RCA + plan as one document for the war room.

## Closing the loop

Tell the user the exit criteria (band ≠ red for 30 days and renewal closed or > 180 days out; or churn confirmed) and that re-running this skill after the first customer conversation, with what was learned, refreshes the RCA against the open action rather than opening a second one.
