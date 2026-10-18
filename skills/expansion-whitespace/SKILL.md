---
name: expansion-whitespace
description: >
  This skill should be used when the user says "where can we expand [account]", "whitespace at
  [account]", "is [account] ready for an upsell", "[account] is over their seat limit", "which of
  my accounts are expansion-ready", "size the expansion at [account]", "sales handoff for
  [account]", or when a book review flags PB-EXP-01 or PB-EXP-02. It checks expansion readiness
  (any red flag defers the play), enumerates evidence-backed plays — seats, tier, modules,
  business units, regions, usage commit — sizes each as indicative annualized list, names the
  sponsor and the objection to expect, decides the motion by segment (self-serve nudge vs
  sales-assist handoff), and drafts one approval-gated sponsor communication.
metadata:
  version: "1.1.0"
  playbook_id: "PB-EXP-01 | PB-EXP-02"
---

# Expansion whitespace (PB-EXP-01 / PB-EXP-02)

Follow `${CLAUDE_PLUGIN_ROOT}/skills/customer-360/references/playbook-protocol.md` with these specifics.

## When it applies

- **PB-EXP-01** (smb / digital): `health.band != "red"` and any of utilization ≥ 0.85, feature-gate hits ≥ 3 in 14d, PQL ≥ 70, DAU/MAU ≥ 0.35.
- **PB-EXP-02** (enterprise / mid_market): `health.band == "green"`, utilization ≥ 0.80, renewal > 60 days, no open expansion opportunity, and whitespace present (unowned modules/BUs) or gate hits / over-deployment.

Readiness gate first: an open P1/P2, payment past due, contraction in 90d, champion departed, CSAT < 3.5, or a high-urgency negative sentiment signal in 30d → emit a `deferral` action naming the blocker and stop. Do not run expansion on an account with an open P0 retention action.

## Inputs beyond the Customer 360

- `pricing_catalog_json` — for **sizing only**: the user's price book from `~~crm` product library or `~~documents` (ask once; remember in the stack profile) → plugin default `DEFAULT_PRICING_CATALOG`. Say which was used; default prices are placeholders.
- `feature_audit_json` — run `feature-depth-audit` as a sub-step first when gate hits or unowned modules are in play, and pass its `feature_audit` block; else `{}`.

## Prompts

1. (conditional) `${CLAUDE_PLUGIN_ROOT}/prompts/adoption/feature_depth_audit.prompt`
2. `${CLAUDE_PLUGIN_ROOT}/prompts/expansion/whitespace_expansion_finder.prompt` — set `playbook_id` by segment; max four plays; sizing with the catalog formulas; `do_not_say` list for the AE.

For enterprise/mid-market, offer to continue into `ebr-generator` with `variant = "expansion"` so the play lands in an executive review rather than a cold ask.

## Artifacts

- `PB-EXP-0x.whitespace_expansion_finder.action.json` with the `expansion_brief` block
- `PB-EXP-0x.expansion_brief.md` — readiness, ranked plays with sizing basis and confidence, sponsor, objection and response, sales handoff notes with `do_not_say`
- `PB-EXP-0x.whitespace_expansion_finder.comm_1.md` — sponsor discovery email (approval required); for digital, the in-app nudge copy is in the action as a `digital_nudge`

## Proposed writes

- ~~crm: `expansion_candidate = true` on the account; an **opportunity suggestion** as a task or note ("Suggested opp: <name>, <band>, close within <window>") — the engine never creates opportunities or touches forecast stages.
- ~~chat: handoff post to the expansion queue channel with qualifying facts and `do_not_say`.
- ~~email: draft of comm_1.

## Rules specific to this playbook

- Never quote prices or terms to a customer; sizing is internal and marked indicative.
- Never propose a play without at least one `evidence_paths[]` entry.
- Never draft to procurement.
- Respect the two-asks-per-14-days limit and any open expansion action.
