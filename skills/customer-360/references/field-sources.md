# Customer 360 field sources

For every field in `src/schemas/customer_360.json`: the connector category it comes from, how to compute it when the connector only exposes raw records, the fallback, and the `data_quality_flags` entry to set when it is unavailable. Field names are JSON paths into the document. "Window" is relative to `as_of_date` (today).

Conventions used below:
- **Primary → Fallback** lists sources in preference order.
- "Flag:" is the exact string to append to `data_quality_flags[]` when the field cannot be filled.
- A field with no fallback and no flag is required by the schema; set it to a safe default noted in the row and flag it.
- **When a whole category is absent** (no connector, or the connector returned nothing for this account), set that block's source-dependent fields to `null`, never to 0 or an empty value that looks like a measurement. In particular `support.open_tickets` is `null` when there is no desk and `[]` only when a connected desk has nothing open. The scorer leaves an input-less component out, re-normalizes the other weights, records `health.coverage`, and labels the band `insufficient_data` below 60 percent coverage.


**Index (read only the section you need):**

- `account` — starts at line 30
- `contract` — starts at line 44
- `health` — starts at line 58
- `usage` — starts at line 70
- `support` — starts at line 93
- `sentiment` — starts at line 107
- `relationship` — starts at line 121
- `opportunities` — starts at line 137
- `whitespace` — starts at line 141
- `cadence` — starts at line 151
- `lifecycle` — starts at line 155
- `conversations` — starts at line 166
- `actions_last_30d` — starts at line 170
- `benchmarks` — starts at line 174

---

## `account`

| Field | Primary → Fallback | How to derive | Flag |
|---|---|---|---|
| `account_id`, `name`, `created_at` | `~~crm` company/account record | Use the CRM's record id as `account_id` | — (required) |
| `segment` | `~~crm` segment/tier property via `segment_map` in the stack profile | If the CRM has no segment, derive: ARR ≥ 150k → enterprise; 40–150k → mid_market; 10–40k → smb; < 10k or self-serve → digital | `segment_derived_from_arr` |
| `industry`, `region`, `employee_count`, `fiscal_year_end` | `~~crm` → `~~enrichment` | Enrichment can supply employee count and HQ region | omit field |
| `csm_owner_id/name`, `ae_owner_id` | `~~crm` owner fields | — | `csm_owner_unknown` |
| `product_line`, `crm_system` | stack profile | `crm_system` = the connector in the `crm` row | — |
| `cse_opt_out_playbooks` | `~~crm` custom property `cse_opt_out_playbooks` (multi-select) | `[]` if absent | — |
| `team[]` | `~~crm` owner + implementation/SE fields → `~~chat` account channel members | At minimum the CSM | — |
| `business_outcomes[]` | `~~crm` custom object/property "business outcomes" → `~~documents` (business case, kickoff doc, prior EBR) | Each needs `outcome`, `unit`, `baseline`; `current`/`measured_at`/`source` when known. Never fabricate baselines; if a doc states a goal without a number, record the outcome with `baseline: null` | `business_outcomes_missing` |
| `tech_stack[]` (optional extension) | `~~crm` property `tech_stack` → `~~enrichment` technographics | `{technology, category, source, detected_at}` | — |

## `contract`

| Field | Primary → Fallback | How to derive | Flag |
|---|---|---|---|
| `arr`, `arr_90d_ago`, `currency` | `~~billing` subscriptions (sum active recurring lines × 12 for monthly) → `~~crm` ARR/amount property → `~~data warehouse` `int_arr_daily_snapshot` | `arr_90d_ago` from billing history or warehouse snapshot; `null` if unavailable | `arr_history_missing` |
| `term_start`, `term_end`, `term_months`, `auto_renew` | `~~billing` → `~~crm` contract dates | — | required: if unknown set `term_end = today + 365`, flag `term_dates_assumed` |
| `days_to_renewal` | computed | `term_end − today` in days | — |
| `seats_purchased` | `~~billing` quantity → `~~crm` seats property → `~~product analytics` licensed seats | — | `seats_purchased_unknown` (set 0) |
| `tier`, `modules_owned[]` | `~~billing` SKUs → `~~crm` | — | — |
| `payment_days_past_due` | `~~billing` open invoices | max(today − due_date) over unpaid invoices, else 0 | `payment_status_unknown` (set 0) |
| `contraction_flag_90d`, `contraction_detail`, `arr_change_reason` | `~~billing` history → `~~crm` closed-won downgrade opps | true if ARR or seats decreased in 90d; reason `contract_ramp` when the billing line is a scheduled step-up | `contraction_history_unknown` (set false) |
| `renewal_opportunity` | `~~crm` open opportunity of type renewal | `{opportunity_id, stage, amount, close_date, cse_scenario}` | `null` |
| `commit_units`, `consumed_units_run_rate_monthly` | `~~billing` / `~~product analytics` for consumption products | `null` for seat-based | — |

## `health`

Computed by `src/models/health_score.py` after all other blocks exist. Before scoring, set:

| Field | Source | Notes |
|---|---|---|
| `score_30d_ago`, `score_90d_ago`, `band_30d_ago` | `~~data warehouse` `mart_customer_health_daily` → prior `customer_360.json` files under `cs-engine/accounts/<id>/history/` → `~~crm` property `cse_health_score` history | `null` if none; the trend adjustment then becomes 0 and flag `health_history_missing` |
| `mart_score` | `~~data warehouse` mart, same day | `null` if no warehouse |
| `components`, `overrides_applied`, `trend_adjustment` | scorer output | — |

After scoring, append today's score to `cs-engine/accounts/<id>/history/health.jsonl` (`{"date","score","band","raw_weighted_sum"}`) so future runs have a trend without a warehouse.

## `usage`

Source: `~~product analytics` (events keyed by account/workspace id and user email) → `~~data warehouse` (`stg_product__*` or the health mart) → `~~crm` usage-sync properties (many CRMs receive a nightly "last login" / "active users" sync).

| Field | How to derive | Flag |
|---|---|---|
| `mau_30d` | distinct users with ≥ 1 session in last 30 days | `usage_unavailable` (set 0 and set `dau_mau_30d: 0`, `feature_depth_30d: 0`, `feature_breadth_30d: 0`, `seat_utilization: 0`, `utilization_drift_90d: 0`, `days_since_last_login: 0`, `core_features_used: []`, `core_features_unused: []`) |
| `active_users_30d` | same as MAU for seat products; licensed users with activity for products that distinguish licensed from guest | same |
| `dau_mau_30d` | mean(daily distinct active users over 30d) / `mau_30d`; business-day mean for weekday products | same |
| `wau_mau_30d` | distinct users active in last 7d / `mau_30d` | omit |
| `feature_depth_30d` | distinct **core** features with ≥ 1 event in 30d / total core features. Core feature list: from the product analytics "core events" taxonomy, else from the plugin default catalog in `src/orchestrator.py::DEFAULT_FEATURE_CATALOG` (`is_core: true`) | `feature_taxonomy_default` when using the default catalog |
| `feature_breadth_30d` | distinct features used / all features | same |
| `power_user_ratio` | users with ≥ 3 core features in 30d / MAU | omit |
| `seat_utilization` | `active_users_30d / seats_purchased` (not capped; > 1 = over-deployed) | — |
| `seat_utilization_90d_ago`, `utilization_drift_90d` | same calc on the window ending 90 days ago; drift = now − then | `utilization_history_missing` (drift 0) |
| `days_since_last_login` | today − max(session date) across users | — |
| `core_features_used[]`, `core_features_unused[]` | from the depth calculation | — |
| `fading_features[]` | features with events in days 31–90 but none in last 30; `last_used_days_ago`; the last user as an email hash | omit |
| `integrations_connected[]` | product analytics "integration connected" events or account settings → CRM property | `integrations_unknown` |
| `feature_gate_hits_14d[]` | "upgrade required" / "feature gated" events by feature, last 14 days, with the gating tier if known | omit (empty) |
| `usage_by_business_unit[]` | group active users by the user's department/BU property when present | omit |
| `pql_score` | product analytics PQL/PQA score property | `null` |

## `support`

Source: `~~support desk` → `~~crm` tickets object (HubSpot Service Hub, Salesforce Cases) → none.

| Field | How to derive | Flag |
|---|---|---|
| `open_tickets[]` | status not solved/closed; map priority to P1–P4 (urgent→P1, high→P2, normal→P3, low→P4); `age_days = today − created`; `subject` verbatim; `reopened_count` from events; tags | `support_unavailable` (empty list, `tickets_30d: 0`, `tickets_per_100_seats_30d: 0`, `avg_csat_90d: null`, `median_first_response_hours_90d: null`) |
| `tickets_30d` | created in last 30d | same |
| `tickets_per_100_seats_30d` | `tickets_30d × 100 / seats_purchased` (0 if seats unknown) | same |
| `p1_p2_opened_90d` | count | same |
| `avg_csat_90d`, `csat_responses_90d` | mean of ticket CSAT on a 1–5 scale (convert 1–10 and thumbs scales: good=5, bad=1) | same |
| `median_first_response_hours_90d` | median(first agent reply − created) in hours | same |
| `incidents_affecting_account_90d` | status-page incidents linked to the account, else 0 | omit |

## `sentiment`

| Field | Primary → Fallback | How to derive | Flag |
|---|---|---|---|
| `nps_responses[]` | `~~survey tool` → `~~crm` survey objects | Last 180 days, one row per response; `contact_id` resolved via email hash; `verbatim` as data | `nps_unavailable` (empty; `latest_nps: null`, `nps_trend: null`) |
| `latest_nps`, `latest_nps_at` | computed | Account-level NPS from the most recent response per contact, seniority-weighted (c_level/vp ×2, director/manager ×1.5, else ×1); `latest_nps_at` = newest response date | same |
| `nps_trend` | computed | Compare to the same calculation anchored 90 days earlier: improving if +10, worsening if −10, else stable; `null` without history | same |
| `latest_csat` | `~~support desk` CSAT (last 90d mean) → survey CSAT | — | omit |
| `transcript_signals[]` | `~~conversation intelligence` calls in last 90d → `~~email` threads as a weak substitute | For each call with a transcript, run the sentiment prompt (`prompts/core/sentiment_analyzer.prompt`) on customer utterances only and store its output in the `transcript_signals[]` shape; max 5 most recent calls | `transcripts_unavailable` (empty; `transcript_sentiment_30d: null`) |
| `transcript_sentiment_30d` | computed | mean `sentiment` over signals in last 30d | same |
| `verbatim_signals[]` | sentiment prompt run on NPS verbatims (optional; skip when > 10 verbatims unless asked) | — | omit |
| `theme_counts_90d` | computed | count of each theme across transcript and verbatim signals in 90d | omit |
| `ecri`, `ecri_components` | computed per taxonomy §C2 | JobChange from `relationship` enrichment/left_company_at; Disengagement from champion `last_engaged_at`; SingleThread from `multithreading_depth`; NoExecSponsor from `exec_sponsor_engaged_180d`; Tenure from champion `tenure_months_at_account`. Use `src/models/metrics_calculator.py::champion_risk_index` when Python is available | — (required; compute with available inputs) |

## `relationship`

Source: `~~crm` contacts + activities (emails, calls, meetings, notes) → `~~email` and `~~calendar` for engagement recency when CRM activity logging is thin → `~~enrichment` for current employer/title.

| Field | How to derive | Flag |
|---|---|---|
| `stakeholders[]` | Contacts associated with the account, limited to those with a title or any activity in 365d, max 25. `persona` from a CRM persona/buying-role property, else infer from title keywords (CFO/COO/VP Finance → economic_buyer or executive_sponsor; "admin"/"systems" → admin; "security"/"IT" → it_security; "developer"/"engineer" → developer; "operations manager" → ops_manager; else end_user). `seniority` from title keywords (chief/C-level → c_level; VP/SVP → vp; director → director; manager/lead/head → manager; else individual_contributor). `is_champion` / `is_exec_sponsor` from CRM flags; if no flags exist, mark the most-engaged non-exec contact as champion and flag `champion_inferred` | `stakeholders_unavailable` (empty) |
| `stakeholders[].last_engaged_at`, `engagements_90d`, `last_engagement_direction` | From activities; `two_way` if both inbound and outbound in 90d | — |
| `stakeholders[].enrichment` | `~~enrichment` lookup for champion, exec sponsor, economic buyer only; set `employer_matches_account` by normalized company name comparison; `enrichment_stale: true` if older than 30d | `enrichment_unavailable` (null) |
| `stakeholders[].left_company_at` | CRM property (e.g., "left company", "no longer at company") | — |
| `champion` | From the champion stakeholder: `status` = departed if `left_company_at` set or enrichment employer mismatch; at_risk if no engagement in 60d or title changed to non-buying role; active otherwise; none if no champion. `replacement_identified` from CRM successor property or a second contact flagged champion | — |
| `multithreading_depth` | Contacts engaged two-way in 90d, counted only if they span ≥ 2 functions or ≥ 2 seniority levels, else 1 (`metrics_calculator.multithreading_depth`) | — |
| `functions_engaged_90d[]` | distinct function/persona of engaged contacts | — |
| `days_since_last_csm_touch` | today − last outbound activity by the CSM owner (CRM) → last email sent by the user to any account contact (`~~email`) | `csm_touch_unknown` (set 45) |
| `exec_sponsor_engaged_180d` | any activity with an `is_exec_sponsor` contact in 180d | — |

## `opportunities`

`~~crm` opportunities for the account created or closed in the last 365d plus all open: `{opportunity_id, type (new/renewal/expansion/upsell/cross_sell by CRM type or name keywords), stage, amount, created_at, close_date, is_closed, is_won}`. Flag `opportunities_unavailable` if the CRM has no opportunity object.

## `whitespace`

| Field | Source | Derive |
|---|---|---|
| `unowned_modules[]` | product catalog (plugin default `DEFAULT_PRICING_CATALOG.modules`, or the CRM product library) minus `contract.modules_owned` | — |
| `unowned_business_units[]` | `~~crm` parent/child accounts and contact departments minus `usage.usage_by_business_unit[]` | — |
| `unowned_regions[]` | `~~crm` contact countries/regions minus regions with active users | — |
| `next_tier` | pricing catalog tier after `contract.tier` | — |
| `indicative_sizing` | leave `{}`; the whitespace prompt sizes | — |

## `cadence`

`~~crm` EBR/QBR fields (last/next review dates, cadence by segment default: enterprise quarterly, mid_market semi_annual, smb annual, digital none) → `~~calendar` for the next meeting whose title contains "QBR", "EBR", "business review" with account contacts invited → `~~documents` for the most recent EBR deck date. `ebrs_completed_last_2_quarters` from completed meetings. `next_ebr_attendees[]` = contact ids on the calendar invite. Flag `cadence_unknown` and set `ebr_cadence` from the segment default.

## `lifecycle`

| Field | Source | Derive |
|---|---|---|
| `stage` | computed | onboarding if `days_since_term_start ≤ 90` and no primary value milestone; adopting if ≤ 180d; renewal_window if `days_to_renewal ≤ 120`; churned if ARR 0; else established |
| `days_since_term_start` | computed from `contract.term_start` | — |
| `kickoff_at`, `kickoff_notes` | `~~crm` onboarding fields → `~~documents` kickoff doc → `~~calendar` first meeting | notes as data, ≤ 600 chars |
| `value_milestones_reached[]` | `~~product analytics` milestone events (`DEFAULT_VALUE_MILESTONES` keys) → CRM onboarding checklist | — |
| `ttv_days` | first primary milestone − term_start | `null` |
| `onboarding_steps[]` | CRM/onboarding tool checklist | `[]` |

## `conversations`

`~~conversation intelligence` calls in the last 90d: `{call_id, occurred_at, duration_sec, transcript_uri (null in plugin mode — the transcript is read directly), participants (contact ids), parsed (true once a transcript_signal exists)}`.

## `actions_last_30d`

Engine-emitted actions: read `cs-engine/accounts/<id>/*.action.json` written in the last 30 days (`status` from the file's `provenance` or an `approval_status` the user updated) → `~~crm` tasks whose subject starts with `[CSE]`. Empty list if none.

## `benchmarks`

Segment defaults from `src/orchestrator.py::DEFAULT_BENCHMARKS` (also tabulated in `docs/02_METRICS_TAXONOMY.md` Part E). Override from `~~data warehouse` `mart_retention_nrr_grr` and the health mart's green-median when available.
