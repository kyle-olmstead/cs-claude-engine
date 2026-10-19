---
name: feature-depth-audit
description: >
  This skill should be used when the user says "feature audit on [account]", "what features is
  [account] not using", "adoption review for [account]", "[account]'s usage is slipping",
  "which features would move retention at [account]", "enablement plan for [account]",
  "adoption narrative for the EBR", or when a book review flags PB-ADP-02. It compares the
  account's feature adoption to green-median peers in its segment, ranks unused features by
  retention lift x fit, identifies fading features and why, maps each recommendation to the
  stakeholder who should adopt it and the enablement asset to use, and writes a three-sentence
  adoption narrative reusable in EBRs and expansion plays.
metadata:
  version: "1.1.0"
  playbook_id: "PB-ADP-02"
---

# Feature depth audit (PB-ADP-02)

Follow `${CLAUDE_PLUGIN_ROOT}/skills/customer-360/references/playbook-protocol.md` with these specifics.

## When it applies

Standalone: `health.band != "red"`, `contract.days_to_renewal > 120`, and either `usage.feature_depth_30d ≤ benchmarks.feature_depth_green_median − 0.15` or `usage.utilization_drift_90d ≤ −0.10`. As a sub-step: whenever `ebr-generator` or `expansion-whitespace` calls for it; then emit only the narrative, the ranked list, and `expansion_fit_notes`, no enablement communications.

If the account has no usage data (`data_quality_flags` contains `usage_unavailable`), stop and say the audit needs `~~product analytics` or `~~data warehouse`; offer `customer-360` once one is connected.

## Inputs beyond the Customer 360

`feature_catalog_json`: the feature catalog with `retention_lift`, `prerequisites`, `target_personas`, `enablement_assets`, `module`. Source order: a catalog the user maintains in `~~documents` (ask once, remember the path in the stack profile) → `~~product analytics` feature taxonomy with the engine's default lift values → the plugin default `DEFAULT_FEATURE_CATALOG` in `${CLAUDE_PLUGIN_ROOT}/src/orchestrator.py`. State which was used; with the default catalog, say that lift values are illustrative until replaced with the user's own renewal-controlled numbers (method in `docs/02_METRICS_TAXONOMY.md` §B4).

## Prompt

`${CLAUDE_PLUGIN_ROOT}/prompts/adoption/feature_depth_audit.prompt`. Compute `fit` with the formula in the prompt and show the factors; cap recommendations at three; separate fading features with a likely reason.

## Artifacts

- `PB-ADP-02.feature_depth_audit.action.json` with the `feature_audit` block
- `PB-ADP-02.feature_audit.md`: position vs peers, ranked recommendations with fit factors, fading features, the narrative, and expansion-fit notes
- `PB-ADP-02.feature_depth_audit.comm_<n>.md`: up to two enablement emails (approval required); in-app nudges go in the action as `digital_nudge` entries, not as communications

## Proposed writes

- ~~crm: task "Enablement session: <feature> with <contact>" for each CSM-led recommendation; `cse_last_playbook` note.
- ~~email: drafts of the enablement emails.
- ~~calendar: proposed enablement session with the target contact.

## Rules specific to this playbook

- Recommend only catalog features; never describe a capability that is not in the catalog.
- A feature in a module the customer does not own is an expansion note, not an adoption play.
- No enablement to a contact silent for 90+ days without a re-engagement action first.
- The narrative must be free of feature keys and internal jargon; it may be read to a CFO.
