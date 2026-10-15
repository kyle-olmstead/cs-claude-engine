# 02 — Metrics Taxonomy

Every metric the engine computes or reasons over, with its definition, formula, data source, cohort rules, thresholds, and the failure modes that make the number lie. Where a metric is implemented in code, the implementing function and mart are named so the formula here is the formula there.

Conventions:

* `ARR` is contracted annual recurring revenue, not bookings and not recognized revenue. One-time services are excluded.
* `t0` is the start of the measurement period, `t1` the end. "Start cohort" means accounts with `ARR > 0` at `t0`.
* All rates are expressed as decimals in code and percentages in prose.
* "Segment" is the CRM `segment` field: `enterprise`, `mid_market`, `smb`, `digital`.

---

## Part A — Retention & Revenue (lagging)

### A1. Net Revenue Retention (NRR)

**Definition.** Revenue retained from the start cohort after expansion, contraction, and churn, excluding new logos.

```
NRR(t0,t1) = ( ARR_t0 + Expansion + Contraction_negative + Churn_negative ) / ARR_t0
           = Σ_{a ∈ cohort(t0)} ARR_a(t1)  /  Σ_{a ∈ cohort(t0)} ARR_a(t0)
```

The second form is the one implemented: for every account in the start cohort, take its ARR at `t1` (zero if churned) and divide the sums. Expansion, contraction, and churn fall out as decompositions:

```
Expansion    = Σ max(ARR_a(t1) − ARR_a(t0), 0)         for a ∈ cohort, ARR_a(t1) > 0
Contraction  = Σ max(ARR_a(t0) − ARR_a(t1), 0)         for a ∈ cohort, ARR_a(t1) > 0
Churn        = Σ ARR_a(t0)                             for a ∈ cohort, ARR_a(t1) = 0
```

**Windows.** Monthly (t0 = prior month-end, t1 = this month-end) for operational tracking; trailing-12-month (t0 = 12 month-ends ago) for board reporting. Never annualize a monthly NRR by `^12` — it compounds noise.

**Implementation.** `mart_retention_nrr_grr.sql` (columns `nrr_monthly`, `nrr_ttm`); `metrics_calculator.cohort_retention()`.

**Benchmarks.** Enterprise SaaS top-quartile TTM NRR ≥ 120%; median ≈ 105%; < 100% means the installed base is shrinking before new logos.

**Gotchas.**
* Multi-year ramps: an account contracted at $100k Y1 / $150k Y2 shows "expansion" at the ramp date with no CSM action. Tag ramp-driven ARR changes (`arr_change_reason = 'contract_ramp'`) and report NRR with and without them.
* Currency: snapshot ARR in reporting currency at a fixed quarterly FX rate, or FX movement masquerades as expansion/contraction.
* Mergers: when two customers merge, treat the surviving account's ARR as the sum at `t0` or the acquired account shows as churn.

### A2. Gross Revenue Retention (GRR)

**Definition.** Revenue retained from the start cohort *before* any expansion. The ceiling is 100%.

```
GRR(t0,t1) = ( ARR_t0 − Contraction − Churn ) / ARR_t0
           = Σ_{a ∈ cohort(t0)} min(ARR_a(t1), ARR_a(t0))  /  Σ_{a ∈ cohort(t0)} ARR_a(t0)
```

**Implementation.** Same mart and function as NRR.

**Benchmarks.** Enterprise ≥ 92%; mid-market ≥ 88%; SMB/digital ≥ 80%. GRR is the number the CS org is accountable for; NRR is shared with sales.

### A3. Logo churn vs. dollar churn

```
Logo churn rate    = |{a ∈ cohort(t0) : ARR_a(t1) = 0}|  /  |cohort(t0)|
Dollar churn rate  = Σ ARR_a(t0) for churned a             /  Σ ARR_a(t0) for cohort
Net dollar churn   = (Churn + Contraction − Expansion)     /  ARR_t0        (= 1 − NRR)
```

**Why both.** Logo churn concentrated in small accounts with low dollar churn is a packaging/ICP problem (sales sold to the wrong customers). Dollar churn concentrated in few logos is a key-account problem (CS coverage or product-fit at scale). The engine reports both and their ratio:

```
Churn concentration = Dollar churn rate / Logo churn rate
  > 1.5  → losses skew to large accounts → enterprise_at_risk playbook over-indexed
  < 0.7  → losses skew to small accounts → onboarding / ICP review
```

**Implementation.** `metrics_calculator.logo_churn_rate()`, `dollar_churn_rate()`, `net_dollar_churn()`; mart columns `logo_churn_rate`, `dollar_churn_rate`.

### A4. Expansion / upsell pipeline velocity

**Definition.** Expected expansion ARR generated per day by the open expansion pipeline.

```
Pipeline velocity ($/day) = ( N_opps × avg_deal_size × win_rate ) / avg_cycle_days
```

where `N_opps` counts open opportunities of `type ∈ {expansion, upsell, cross_sell}`, `win_rate` is the trailing-2-quarter closed-won rate for that type and segment, and `avg_cycle_days` is the trailing-2-quarter mean of `close_date − created_at` for closed-won.

**Read with.** Expansion pipeline *coverage* = open expansion pipeline / remaining expansion quota. The engine flags any CSM whose coverage < 2.0× with > 60 days left in quarter.

**Implementation.** `metrics_calculator.expansion_pipeline_velocity()`. Source: `stg_crm__opportunities`.

**Gotchas.** Velocity is only meaningful with ≥ 20 closed opps in the win-rate window; below that the engine falls back to the company-wide rate and marks the metric `low_confidence`.

---

## Part B — Adoption & Product Health (leading)

### B1. Customer Health Score

**Definition.** A 0–100 weighted composite of six component scores, each 0–100, with hard-gate overrides and a trend adjustment. The model is deliberately linear and additive so every point is attributable to a component — explainability is a requirement, not a nice-to-have.

```
HealthScore = clamp( Σ_i w_i · C_i  +  TrendAdj , 0, 100 )   subject to overrides
Σ w_i = 1
```

**Components and default weights** (`dbt_project.yml` `vars.health_weights`, mirrored in `health_score.DEFAULT_WEIGHTS`):

| Component | Weight | Inputs (all 30-day unless noted) | Normalization |
|---|---|---|---|
| Adoption | 0.25 | DAU/MAU, feature depth, seat utilization | DAU/MAU: linear 0.05→0, 0.40→100. Depth: ×100. Utilization: linear 0.30→0, 0.90→100, capped at 100 (over-utilization is an expansion signal, not a health signal). Average of three. |
| Engagement | 0.15 | days since last customer login (any user), # engaged contacts 90d, exec engaged 90d (bool) | Login recency: 0d→100, 14d→50, 30d+→0 (piecewise). Contacts: 1→20, 2→50, 4+→100. Exec: 100/0. Weighted 0.4/0.3/0.3. |
| Support | 0.15 | open P1/P2 count, tickets per 100 seats, avg CSAT 90d, median first-response hours | P1/P2: 0→100, 1→60, 2+→20. Tickets/100 seats: ≤2→100, 10+→0 linear. CSAT: (score−1)/4×100. First response: ≤4h→100, 48h+→0. Average. |
| Sentiment | 0.15 | latest NPS (−100..100 account-level or relationship NPS), NPS trend, transcript sentiment 30d (−1..1) | NPS: (nps+100)/2. Trend: improving→100, stable→50, worsening→0. Transcript: (s+1)/2×100. Weighted 0.5/0.1/0.4; missing inputs re-normalize weights. |
| Relationship | 0.15 | champion status, multithreading depth, days since last CSM touch | Champion: active→100, at_risk→50, none→30, departed→0. Depth: 1→20, 2→50, 3→75, 4+→100. CSM touch: ≤14d→100, 45d+→0. Weighted 0.5/0.3/0.2. |
| Commercial | 0.15 | days to renewal, payment days past due, contraction flag (any seat/ARR decrease in 90d) | Renewal: ≥180d→100, 90d→80, 30d→60, 0d→40 (proximity raises stakes, not risk per se). Past due: 0→100, 30→60, 60+→0. Contraction: −30 if true. |

**Trend adjustment.** `TrendAdj = clamp( (Score_raw − Score_raw_30d_ago) × 0.25, −8, +8 )`. A falling score is penalized ahead of the level it falls to; a recovering score gets credit.

**Hard-gate overrides** (applied after the weighted sum; the score is *capped*, never floored):

| Condition | Cap |
|---|---|
| `champion_status = departed` and `replacement_identified = false` | 60 |
| `payment_days_past_due > 60` | 50 |
| any open P1 older than 5 days | 65 |
| `seat_utilization < 0.20` for 60+ days on a contract > $50k ARR | 55 |

**Bands.** Green ≥ 75, Yellow 50–74, Red < 50. Band *transitions* are the alerting primitive, not the score itself.

**Implementation.** `health_score.compute_health_score()` and `mart_customer_health_daily.sql`. The two must agree within 0.5 points (see Architecture §3.3).

**Validation requirement.** Quarterly: red-band accounts 90 days pre-renewal must churn at ≥ 3× the green-band rate, else re-fit weights.

### B2. Time to Value (TTV)

**Definition.** Days from contract start to the first *value milestone* for the account's product line. Value milestones are defined per product by Product + CS leadership and stored in `stg_product__value_milestones` (`milestone_key`). Typical keys: `first_production_workflow`, `integration_connected`, `five_active_users`, `first_report_shared`.

```
TTV_a = min( reached_at for milestone ∈ primary_value_milestones(product) ) − term_start_a
```

Reported as median and p75 by segment and by onboarding cohort month. An account with no milestone after `p75_TTV(segment)` days fires `ttv_acceleration`.

**Implementation.** `metrics_calculator.time_to_value()`.

**Benchmarks.** Enterprise p50 ≤ 45 days; mid-market ≤ 21; digital ≤ 7.

### B3. DAU/MAU stickiness

```
DAU/MAU_30d = ( Σ_{d in last 30 days} DAU_d / 30 ) / MAU_30d
```

where `DAU_d` = distinct users with ≥ 1 session on day `d`, `MAU_30d` = distinct users with ≥ 1 session in the window. Weekday-only products should compute over business days (parameter `business_days_only`).

**Implementation.** `metrics_calculator.dau_mau_ratio()`; mart column `dau_mau_30d`.

**Benchmarks.** Daily-workflow tools ≥ 0.40; weekly-workflow ≥ 0.20. Below 0.10 in a paid account the users have found a workaround.

### B4. Feature depth and breadth

```
Feature depth_30d   = |{core features with ≥ 1 event by this account in 30d}| / |core features|
Feature breadth_30d = |{all features with ≥ 1 event}| / |all features|
Power-user ratio    = |{users using ≥ 3 core features}| / MAU
```

Depth drives health (B1). Breadth and power-user ratio drive the `feature_depth_audit` prompt, which compares the account to the *median of green accounts in the same segment* and names the specific unused features with the highest retention lift. Retention lift per feature is computed annually: `P(renew | used feature) − P(renew | not used)` over the prior year's renewals, controlling for segment.

**Implementation.** `metrics_calculator.feature_depth()`; mart columns `feature_depth_30d`, `feature_breadth_30d`.

### B5. Seat / license utilization and drift

```
Utilization_t     = active_seats_30d(t) / seats_purchased(t)
Utilization drift = Utilization_t − Utilization_{t−90d}
```

`active_seats_30d` = distinct licensed users with ≥ 1 session in 30 days. Usage-based products substitute `consumed_units / committed_units`.

**Thresholds.**

| Utilization | Drift | Signal | Playbook |
|---|---|---|---|
| ≥ 0.85 | any | expansion-ready | `low_touch_digital_expansion` / `whitespace_expansion_finder` |
| 0.50–0.85 | ≥ +0.10 | growing, watch for 0.85 | none (positive note in EBR) |
| 0.50–0.85 | ≤ −0.10 | adoption erosion | `feature_depth_audit` |
| < 0.50 | any | contraction risk at renewal | `renewal_defense_playbook` (seat right-size scenario) |
| < 0.20 on > $50k ARR | 60+ days | hard-gate cap 55 | `enterprise_at_risk_turnaround` |

**Implementation.** `metrics_calculator.seat_utilization()`, `utilization_drift()`.

---

## Part C — Sentiment & Executive Alignment

### C1. NPS and CSAT

```
NPS  = %Promoters(9–10) − %Detractors(0–6)        range −100..100
CSAT = |{responses with score ≥ 4 on 5-pt}| / |responses|   (or ≥ 8 on 10-pt)
```

Account-level NPS uses the *most recent response per contact* within 180 days, weighted by contact seniority (exec ×2, manager ×1.5, user ×1). Relationship NPS (quarterly survey) is preferred over transactional NPS (post-ticket) for health.

**Qualitative extraction.** Every verbatim passes through `sentiment_analyzer.prompt`, which emits: `sentiment (−1..1)`, `themes[]` from a controlled vocabulary (`product_gap`, `reliability`, `support_quality`, `pricing_value`, `onboarding`, `integration`, `ux`, `relationship`, `competitor_mention`, `expansion_intent`, `churn_intent`), `quoted_evidence` (≤ 25 words), `urgency`, and `recommended_owner`. Theme frequency over 90 days is the input to the RCA prompt.

### C2. Executive Champion Risk Index (ECRI)

**Definition.** 0–100 score where higher = more risk, computed per account from the champion's status and the depth of the relationship around them.

```
ECRI = 100 × ( 0.35·JobChange + 0.20·Disengagement + 0.20·SingleThread + 0.15·NoExecSponsor + 0.10·Tenure )
```

| Term | Definition | Value |
|---|---|---|
| JobChange | Clay/LinkedIn enrichment shows champion's current company ≠ CRM account, or CRM `left_company_at` set | 1 if departed; 0.6 if title change within same company to a non-buying role; 0 otherwise |
| Disengagement | days since champion's last inbound/outbound activity | 0 if ≤ 30d; linear to 1 at 120d |
| SingleThread | multithreading depth (C3) | 1 if depth = 1; 0.5 if 2; 0 if ≥ 3 |
| NoExecSponsor | no contact with `is_exec_sponsor` engaged in 180d | 1 / 0 |
| Tenure | champion tenure at account | 1 if < 6 months; 0.5 if 6–18; 0 if > 18 |

**Thresholds.** ECRI ≥ 60 → `enterprise_at_risk_turnaround` (champion track). ECRI 35–59 → multithreading task to CSM. Champion departure (JobChange = 1) always fires regardless of composite.

**Implementation.** `metrics_calculator.champion_risk_index()`; `clay_crm_enrichment.detect_champion_change()` supplies `JobChange`.

### C3. Multithreading depth

```
Depth = |{contacts with ≥ 1 two-way activity in 90d}|   counted across ≥ 2 distinct functions OR ≥ 2 seniority levels
```

A single department with four engaged users counts as depth 1 for risk purposes (the whole thread leaves together). Functions come from CRM `persona` (`economic_buyer`, `champion`, `admin`, `end_user`, `executive_sponsor`, `procurement`, `it_security`).

**Target by segment.** Enterprise ≥ 4 (incl. one exec); mid-market ≥ 3; SMB ≥ 2; digital ≥ 1 with a verified admin email.

**Implementation.** `metrics_calculator.multithreading_depth()`.

---

## Part D — Capacity & Efficiency (operational)

### D1. ARR per CSM and portfolio balance

```
ARR_per_CSM = Σ ARR over CSM's book
Balance index = σ(ARR_per_CSM across team) / mean(ARR_per_CSM)     target ≤ 0.20
```

**Targets by motion.** Enterprise $5–8M / 15–30 accounts; mid-market $2–4M / 40–80; SMB $3–6M / 150–300 (pooled); digital $10M+ / 1,000+ (automation-led). The engine flags any CSM > 115% of segment target *and* holding ≥ 2 red accounts — that is where coverage fails first.

**Rebalancing input.** The orchestrator emits a `rebalance_candidate` note (not an action) when a book exceeds target, listing the lowest-touch green accounts as transfer candidates. Reassignment remains a human decision.

**Implementation.** `metrics_calculator.arr_per_csm()`.

### D2. Customer Retention Cost (CRC)

```
CRC_period        = Σ fully-loaded CS cost (salaries, tooling, programs, allocated support)
CRC per customer  = CRC_period / |customers|
CRC per $ retained= CRC_period / ( GRR × ARR_t0 )       → cents spent per dollar retained
CRC ratio         = CRC_period / ARR_t0                 → target ≤ 0.10 enterprise, ≤ 0.06 digital
```

**Implementation.** `metrics_calculator.customer_retention_cost()`. Source: `int_csm_cost`.

### D3. LTV:CAC

```
Gross-margin-adjusted LTV = ( ARPA × gross_margin ) / annual_dollar_churn_rate
LTV:CAC = LTV / CAC
```

`ARPA` = average ARR per account in the segment; `annual_dollar_churn_rate` = 1 − GRR_ttm (use GRR, not NRR — expansion is not guaranteed). `CAC` = fully-loaded S&M cost / new logos, trailing 4 quarters. When `annual_dollar_churn_rate < 0.02` cap the LTV horizon at 10 years (`LTV ≤ ARPA × margin × 10`) to avoid absurd multiples.

**Benchmark.** ≥ 3.0 healthy; ≥ 5.0 under-investing in growth; < 1.5 unsustainable.

**Implementation.** `metrics_calculator.ltv_cac()`.

### D4. QBR / EBR completion velocity

```
QBR velocity        = |QBRs completed on time| / |QBRs due|        per quarter per CSM
QBR lag (days)      = median( completed_at − due_at ) for completed
QBR coverage (ARR)  = Σ ARR of accounts with a completed QBR / Σ ARR due
```

A QBR is "due" by segment cadence: enterprise quarterly, mid-market semi-annual, SMB annual, digital none (replaced by automated value summary). "On time" = within 15 days of due date. ARR-weighted coverage matters more than count — a CSM at 70% count but 95% ARR coverage is prioritizing correctly.

**Automation.** The `executive_ebr_generator` prompt fires 30 days before due; an EBR with a generated pre-read is 2.4× more likely to be completed on time in the reference deployment.

**Implementation.** `metrics_calculator.qbr_completion_velocity()`.

---

## Part E — Benchmark table (segment medians used by prompts)

Prompts receive `segment_benchmarks_json`; these defaults ship in `orchestrator.DEFAULT_BENCHMARKS` and should be overwritten from the warehouse quarterly.

| Metric | Enterprise | Mid-market | SMB | Digital |
|---|---|---|---|---|
| GRR (ttm) | 0.92 | 0.88 | 0.80 | 0.75 |
| NRR (ttm) | 1.18 | 1.10 | 1.02 | 1.00 |
| Health (green median) | 82 | 80 | 78 | 76 |
| DAU/MAU | 0.38 | 0.32 | 0.28 | 0.22 |
| Feature depth | 0.62 | 0.55 | 0.48 | 0.40 |
| Seat utilization | 0.78 | 0.74 | 0.70 | 0.65 |
| TTV p50 (days) | 45 | 21 | 10 | 7 |
| Multithread depth | 4 | 3 | 2 | 1 |
| ECRI (median) | 28 | 32 | 38 | 45 |

---

## Part F — Metric lineage summary

| Metric | SQL | Python | Prompt(s) that reason over it |
|---|---|---|---|
| NRR / GRR / churn | `mart_retention_nrr_grr` | `cohort_retention` | orchestrator context, `executive_ebr_generator` |
| Pipeline velocity | — (from opportunities) | `expansion_pipeline_velocity` | `whitespace_expansion_finder` |
| Health score | `mart_customer_health_daily` | `compute_health_score` | all |
| TTV | — (from milestones) | `time_to_value` | `ttv_acceleration` |
| DAU/MAU, depth, utilization | `mart_customer_health_daily` | `dau_mau_ratio`, `feature_depth`, `seat_utilization` | `feature_depth_audit`, `whitespace_expansion_finder` |
| NPS/CSAT + themes | `mart_customer_health_daily` (score) | — | `sentiment_analyzer`, `churn_risk_rca` |
| ECRI, multithreading | `mart_customer_health_daily` (inputs) | `champion_risk_index`, `multithreading_depth` | `churn_risk_rca`, `renewal_defense_playbook` |
| ARR/CSM, CRC, LTV:CAC, QBR velocity | — | respective functions | orchestrator capacity notes, `executive_ebr_generator` (ROI) |
