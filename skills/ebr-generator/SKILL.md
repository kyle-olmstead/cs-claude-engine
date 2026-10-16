---
name: ebr-generator
description: >
  This skill should be used when the user says "prep the [account] EBR", "build the QBR for
  [account]", "executive business review for [account]", "generate the EBR deck script",
  "ROI table for [account]", "pre-read for the [account] business review", "what should I show
  [account]'s CFO", "value review for [account]", or when a book review flags PB-CAD-01. It turns
  product usage, stated business outcomes, and ROI inputs into a C-suite-ready review: a
  one-page narrative, a slide-by-slide script with talk tracks and a source path for every
  number, an ROI table with low/base/high cases and measured-vs-inferred flags, structured
  pre-work, decision asks, and an approval-gated pre-read email. Variants: standard, renewal,
  expansion.
metadata:
  version: "1.1.0"
  playbook_id: "PB-CAD-01"
---

# Executive business review generator (PB-CAD-01)

Follow `${CLAUDE_PLUGIN_ROOT}/skills/customer-360/references/playbook-protocol.md` with these specifics.

## When it applies

An EBR/QBR due within 30 days (`cadence.next_ebr_due_at`, or a matching meeting in `~~calendar`), or renewal ≤ 180 days with no EBR in two quarters, or on request. Choose the variant: `renewal` when `contract.days_to_renewal ≤ 180`; `expansion` when invoked from `expansion-whitespace` or the user asks for an expansion EBR; else `standard`.

## Inputs beyond the Customer 360

- `roi_inputs_json` — the loaded hourly rate and any outcome measurements, from `~~crm` business-outcome fields and `~~documents` (business case, prior EBR, finance export). **Never assume a loaded hourly rate or an attribution share**; if absent, the ROI table reports the outcome as unvalued with a proposed measurement. Ask the user once whether a rate exists before running; record the answer in the action's `data_quality_flags`.
- `retention_context_json` — the account's segment row from `~~data warehouse` `mart_retention_nrr_grr` when present; else the segment benchmarks only (and say the peer comparison is benchmark-based).
- `feature_audit_json` — run `feature-depth-audit` as a sub-step (narrative mode) and pass its `feature_audit` block.
- `expansion_brief_json` — for the expansion variant, the `expansion_brief` from `expansion-whitespace`; else `{}`.
- Prior EBR material from `~~documents` (last deck, notes) so the "where we started" slide uses the customer's own words.

## Prompts

1. `${CLAUDE_PLUGIN_ROOT}/prompts/adoption/feature_depth_audit.prompt` (narrative mode)
2. `${CLAUDE_PLUGIN_ROOT}/prompts/expansion/executive_ebr_generator.prompt` — 8–10 slides, every number sourced, one customer quote max, no pricing anywhere, decision asks with owners and dates.

## Artifacts

- `PB-CAD-01.executive_ebr_generator.action.json` with the `ebr` block
- `PB-CAD-01.ebr_narrative.md` — the one-pager
- `PB-CAD-01.ebr_script.md` — slide-by-slide: title, claim, talk track, ask the room, visual, sources, risk if challenged
- `PB-CAD-01.ebr_roi_table.md` — rows with formulas, low/base/high, measured flags, unmeasured outcomes with proposed measurement
- `PB-CAD-01.ebr_prework.json` — three unknowns, missing attendee, risk to pre-empt, duration
- `PB-CAD-01.comm_1.md` — pre-read email to the most senior attendee (approval required)

When the session offers a slides artifact type or `~~documents`, offer to build the deck from the script — the script's `visual` line per slide is the brief for each slide. Keep the script as the source of truth; the deck is a rendering.

## Proposed writes

- ~~crm: `cadence.last_ebr_prepared_at = today`; task "EBR: <account>" with the artifact location; one measurement task per unmeasured outcome, owner and date from the ROI table.
- ~~calendar: if no EBR is on the calendar, a proposed hold with the attendees from `ebr.audience` including the missing attendee.
- ~~email: draft of the pre-read.
- ~~documents: the narrative, script, and ROI table as one document.

## Rules specific to this playbook

- Every number on every slide has a `sources[]` path. No source, no number.
- Peer comparison uses only the retention context and benchmarks provided — quartile language, never invented percentages.
- The talk track is spoken language in the second person; the customer did the work, the product enabled it.
- Include the strongest negative theme when its urgency is medium or higher, paired with the status of the fix.
