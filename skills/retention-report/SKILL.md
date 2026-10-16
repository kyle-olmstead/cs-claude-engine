---
name: retention-report
description: >
  This skill should be used when the user says "what's our NRR", "GRR this quarter", "net
  revenue retention by segment", "logo vs dollar churn", "retention report", "churn
  concentration", "expansion pipeline velocity", "ARR per CSM", "retention cost", "LTV to CAC",
  "QBR completion rate", or asks any question about lagging retention or CS efficiency metrics.
  It computes the engine's retention and capacity metrics from the warehouse marts when
  connected, otherwise from CRM/billing records, using the exact formulas in the metrics
  taxonomy, and presents them with cohort definitions, caveats, and the decomposition
  (expansion, contraction, churn, new logos) so the numbers can be defended.
metadata:
  version: "1.1.0"
  playbook_id: "METRICS"
---

# Retention & efficiency report

Compute the lagging and capacity metrics from `${CLAUDE_PLUGIN_ROOT}/docs/02_METRICS_TAXONOMY.md` Parts A and D with the exact formulas there. Read the relevant section before computing so the cohort rules (start cohort = ARR > 0 at t0; new logos excluded from NRR/GRR; ramps tagged) are applied, and state them in the answer.

## Source order

1. `~~data warehouse` with `dbt/models/marts/mart_retention_nrr_grr.sql` built → query the mart for the period, window (`monthly` / `ttm`), and segment. This is authoritative; use it as-is.
2. `~~billing` subscription history → build two ARR snapshots (t0, t1) per account with segment, write them as JSON, and run:
   ```bash
   python3 - <<'EOF'
   # see src/models/metrics_calculator.py::cohort_retention_by_segment for the exact call
   EOF
   ```
   (Write a short script to the working folder that loads the snapshots into `ARRSnapshot` objects and prints `cohort_retention_by_segment(...)`; keep the script with the run's outputs.)
3. `~~crm` ARR property history or closed-won/closed-lost renewal opportunities → same as 2 with reduced confidence; say that CRM-derived ARR is not a billing-grade number.

## Metrics and functions

| Ask | Function (`src/models/metrics_calculator.py`) | Needs |
|---|---|---|
| NRR, GRR, logo churn, dollar churn, net dollar churn, churn concentration | `cohort_retention_by_segment(t0, t1, ...)` | ARR snapshots at t0 and t1 |
| Expansion pipeline velocity, coverage | `expansion_pipeline_velocity(opps, as_of, remaining_quota)` | `~~crm` opportunities of type expansion/upsell/cross_sell, open + closed in 180d |
| ARR per CSM, balance index, over-capacity flags | `arr_per_csm(accounts, segment_targets)` | accounts with owner, ARR, segment, health band |
| CRC, CRC per $ retained, CRC ratio | `customer_retention_cost(total_cs_cost, customers, grr, start_arr)` | CS cost from the user (ask once; never guess headcount cost) |
| LTV:CAC | `ltv_cac(arpa, gross_margin, grr_ttm, cac)` | gross margin and CAC from the user (ask once) |
| QBR/EBR completion velocity, ARR coverage | `qbr_completion_velocity(qbrs)` | due/completed dates from `~~crm` or `~~calendar`, ARR per account |

Run the functions with Python when available (write the input JSON and a five-line script into `cs-engine/runs/<today>/`); otherwise compute by hand and show the arithmetic.

## Output

1. Headline: the metric, the window, the segment, the number — one line each.
2. Decomposition table: start ARR, expansion, contraction, churn, end ARR, new-logo ARR (excluded), logos in cohort, churned logos.
3. Benchmarks from `docs/02_METRICS_TAXONOMY.md` Part E for the segment, with one sentence of interpretation (top quartile / median / below).
4. Caveats that apply: ramp-driven expansion included or excluded, FX, merged accounts, sample size for win rates (< 20 closed opps → low confidence), CRM-derived ARR.
5. Offer: save as a document in `~~documents`, or chart the trend inline when more than one period is available.

## Rules

- Never annualize a monthly NRR with `^12`.
- GRR is capped at 100% by construction; if the data produces more, the cohort rule was broken — recompute.
- Do not invent cost, margin, or CAC inputs; ask once and remember the answer in the stack profile for this user.
