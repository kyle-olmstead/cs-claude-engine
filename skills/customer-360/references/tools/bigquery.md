# Google Cloud BigQuery

**Category:** `~~data warehouse` · **Claude connector:** Google Cloud BigQuery · **Status:** mapped from vendor documentation on 2026-10-20; not yet run against a live account. Confirm in `cs-setup`.

BigQuery serves the engine's two dbt marts. `mart_customer_health_daily` supplies the health history the trend needs (`health.score_30d_ago`, `health.score_90d_ago`, `health.band_30d_ago`, `health.raw_weighted_sum_30d_ago`), the mart's own score for the drift check (`health.mart_score`), and inputs to all six components: usage, support, sentiment, relationship and contract. `mart_retention_nrr_grr` supplies segment NRR and GRR for the benchmarks and for `retention-report`.

## What the connector exposes

Claude's directory lists five tools for this connector. Google's tool reference describes the same five.

- `list_dataset_ids`: lists the dataset ids in a project. Setup uses it to find the dataset dbt builds the marts into.
- `get_dataset_info`: dataset metadata. Setup uses it to read the dataset location.
- `list_table_ids`: lists the table ids in a dataset. Setup uses it to confirm both marts exist.
- `get_table_info`: table metadata, including the schema. Setup uses it to confirm the column names below and to see whether the health mart is partitioned on `as_of_date` (confirm in setup where the metadata shows partitioning).
- `execute_sql`: runs a query in the project and returns the results. Every number in this map comes from this tool. Build the call from the tool's own input schema in the session; this map does not name its fields.

Read-only behavior. Google's tool reference says `execute_sql` accepts only `SELECT` statements and refuses `INSERT`, `UPDATE`, `DELETE` and stored procedures, and that a query calling a remote function or Python UDF can still have side effects. Google's guide to the server says the opposite in one place: "The only MCP tool that isn't read-only is execute_sql". The same guide documents a sixth tool, `execute_sql_readonly` (unconfirmed for this connector: the directory does not list it), which allows only read operations. So:

- Treat `execute_sql` as able to write. The engine sends only the `SELECT` statements in this map. It never sends DDL or DML.
- If the session exposes `execute_sql_readonly`, use it in place of `execute_sql`.
- Give the identity Claude uses BigQuery Data Viewer on the marts dataset only. A write then fails on permissions whatever the tool allows.

Other facts that matter:

- Server URL `https://bigquery.googleapis.com/mcp`, sign-in with Google OAuth. The user needs MCP Tool User (`roles/mcp.toolUser`) and BigQuery Job User (`roles/bigquery.jobUser`) on the project, and BigQuery Data Viewer (`roles/bigquery.dataViewer`). BigQuery lets Data Viewer be granted on one dataset instead of the whole project.
- Query costs bill to the project named in the call. Every query the tool runs carries the label `goog-mcp-server: true`, so the customer can find the engine's jobs in job history.
- The marts hold one row per account per day and one row per segment per month. They carry no ticket list, invoice list, stakeholder list or per-feature events. `support.open_tickets`, `usage.core_features_used`, `usage.fading_features`, `relationship.stakeholders` and similar lists still come from their own connectors.
- The marts are built by the customer's data team with dbt, nightly. The engine only reads them.

## Matching records to the CRM account

The staging model sets the mart's `account_id` to the CRM record id (`crm_companies.id`), so matching is a direct key lookup.

1. **CRM record id.** Look up `account_id` equal to the CRM id, compared as exact text. HubSpot ids are numeric strings: send them quoted.
2. **Salesforce id length.** If the CRM is Salesforce and setup finds 15-character ids on one side and 18-character ids on the other, compare the first 15 characters, case-sensitive. Record the rule in the stack profile once (confirm in setup).
3. **No row.** The health mart keeps only accounts with ARR above 0 on that day, so a missing row can mean the account churned, has not started, or carries a different id. Never match on `account_name`. Use the name only to tell the user what the mart holds. Set `warehouse_account_unmatched` and let every block fall back to its other sources.

## Setup check

First, two free metadata calls: `list_table_ids` on the dataset the user names (both `mart_customer_health_daily` and `mart_retention_nrr_grr` must be listed), then `get_table_info` on the health mart (the columns in the field map must be present). Then one cheap read through `execute_sql`, with one CRM account id from the user's book:

```sql bigquery
SELECT
  h.latest_as_of_date,
  DATE_DIFF(CURRENT_DATE(), h.latest_as_of_date, DAY) AS days_behind,
  h.accounts_on_latest,
  h.sample_account_rows,
  r.latest_period_month
FROM (
  SELECT
    as_of_date AS latest_as_of_date,
    COUNT(*) AS accounts_on_latest,
    COUNTIF(account_id = '<one_crm_account_id_from_the_book>') AS sample_account_rows
  FROM `{project}.{dataset}.mart_customer_health_daily`
  WHERE as_of_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  GROUP BY as_of_date
  ORDER BY as_of_date DESC
  LIMIT 1
) AS h
CROSS JOIN (
  SELECT MAX(period_month) AS latest_period_month
  FROM `{project}.{dataset}.mart_retention_nrr_grr`
) AS r
```

Pass: one row comes back, `days_behind` is 2 or less, `accounts_on_latest` is above 0, `sample_account_rows` is 1, and `latest_period_month` is not null. Zero rows means nothing was built in the last 7 days. If the sample account has ARR 0, try another account before calling the ids mismatched.

Record one of these in the status column:

- `connected (mapped; marts current as of <latest_as_of_date>)`
- `connected (mapped; marts stale, latest as_of_date <latest_as_of_date>)`
- `connected (mapped; account ids do not match the CRM)`
- `connected (marts not found in <project>.<dataset>)`
- `connected (failing: <reason>)` when a call errors.

## Field map

Every row reads the latest row per account from the first query below. `d` is today minus that row's `as_of_date`, in days. If `d` is more than 2, set `warehouse_mart_stale`, leave `health.mart_score` and every current-state field to its other sources, and keep only the four history fields (`health.score_30d_ago`, `health.score_90d_ago`, `health.band_30d_ago`, `health.raw_weighted_sum_30d_ago`), saying in the explanation how many days old they are.

| Customer 360 field | Source in BigQuery | How to derive | If unavailable |
|---|---|---|---|
| `account.account_id` | `mart_customer_health_daily.account_id` | Join key only. The CRM supplies the value; the mart must hold the same text. | `warehouse_account_unmatched` |
| `account.name` | `mart_customer_health_daily.account_name` | Cross-check only. The CRM wins. | none |
| `account.segment` | `mart_customer_health_daily.segment` | Cross-check only. The CRM value through `segment_map` wins. Picks the retention and benchmark rows. | none |
| `account.csm_owner_id` | `mart_customer_health_daily.csm_owner_id` | Cross-check only. The CRM wins. | none |
| `contract.arr` | `mart_customer_health_daily.arr` | Use when the stack profile names the warehouse as the contract source or no `~~billing` is connected. Otherwise billing wins; report a gap over 5 percent as `arr_source_disagreement`. | `arr_history_missing` |
| `contract.seats_purchased` | `mart_customer_health_daily.seats_purchased` | Same precedence as `contract.arr`. | `seats_purchased_unknown` |
| `contract.days_to_renewal` | `mart_customer_health_daily.days_to_renewal` | Value minus `d`. If billing or the CRM gives `contract.term_end`, compute from that instead. | none |
| `contract.payment_days_past_due` | `mart_customer_health_daily.payment_days_past_due` | Value as of `as_of_date`. Do not add `d`: the mart cannot say whether the invoice was paid since. | `payment_status_unknown` |
| `contract.contraction_flag_90d` | `mart_customer_health_daily.contraction_flag_90d` | True when ARR or seats fell against the snapshot 90 days earlier. | `contraction_history_unknown` |
| `usage.mau_30d` | `mart_customer_health_daily.mau_30d` | Read as is when `usage_observed` is true. When it is false the mart leaves usage null: keep null, never 0. | `usage_unavailable` |
| `usage.active_users_30d` | `mart_customer_health_daily.active_users_30d` | Same rule as `usage.mau_30d`. | `usage_unavailable` |
| `usage.dau_mau_30d` | `mart_customer_health_daily.dau_mau_30d` | Read as is (the mart caps it at 1.0, and writes 0 when the product has history but nobody logged in for 30 days). Null only when the account has no product data at all. | `usage_unavailable` |
| `usage.feature_depth_30d` | `mart_customer_health_daily.feature_depth_30d` | Core features used in 30 days over the dbt var `health_core_feature_count` (default 4). | `usage_unavailable` |
| `usage.feature_breadth_30d` | `mart_customer_health_daily.feature_breadth_30d` | Features used in 30 days over all features the source has ever reported. | `usage_unavailable` |
| `usage.seat_utilization` | `mart_customer_health_daily.seat_utilization` | Active users over seats, not capped. Null when seats are 0. | `seats_purchased_unknown` |
| `usage.seat_utilization_90d_ago` | `mart_customer_health_daily.seat_utilization_90d_ago` | Active users in days 91 to 120 ago over current seats. | `utilization_history_missing` |
| `usage.utilization_drift_90d` | `mart_customer_health_daily.utilization_drift_90d` | Now minus 90 days ago. If null, set 0. | `utilization_history_missing` |
| `usage.days_since_last_login` | `mart_customer_health_daily.days_since_last_login` | Value plus `d` (days since the mart's `as_of_date`). The mart counts from the latest login ever, so a dormant account reads 45 or 60, not null. Null only when the account has no product data at all. | `usage_unavailable` |
| `support.tickets_per_100_seats_30d` | `mart_customer_health_daily.tickets_per_100_seats_30d` | Read as is. Null when `support_observed` is false or seats are 0. | `support_unavailable` |
| `support.tickets_30d` | `mart_customer_health_daily.tickets_per_100_seats_30d` and `mart_customer_health_daily.seats_purchased` | Rate times seats over 100, rounded to a whole number. Only when seats are above 0. | `support_unavailable` |
| `support.avg_csat_90d` | `mart_customer_health_daily.avg_csat_90d` | Mean ticket CSAT for tickets resolved in 90 days. The mart scores it as a 1 to 5 scale. | `support_unavailable` |
| `support.median_first_response_hours_90d` | `mart_customer_health_daily.median_first_response_hours_90d` | Hours, tickets created in 90 days. BigQuery builds it with an approximate median. | `support_unavailable` |
| `sentiment.latest_nps` | `mart_customer_health_daily.latest_nps` | Seniority-weighted account NPS from each contact's latest response in 180 days, on minus 100 to 100. | `nps_unavailable` |
| `sentiment.latest_nps_at` | `mart_customer_health_daily.latest_nps_at` | Date of the newest response. | `nps_unavailable` |
| `sentiment.nps_trend` | `mart_customer_health_daily.nps_trend` | `improving`, `stable`, `worsening` or null. | `nps_unavailable` |
| `sentiment.transcript_sentiment_30d` | `mart_customer_health_daily.transcript_sentiment_30d` | Mean transcript sentiment in 30 days, on minus 1 to 1. | `transcripts_unavailable` |
| `relationship.multithreading_depth` | `mart_customer_health_daily.multithreading_depth` | Contacts engaged in 90 days, counted only when they span 2 functions or 2 seniority levels, else 1. | none |
| `relationship.exec_sponsor_engaged_180d` | `mart_customer_health_daily.exec_sponsor_engaged_180d` | Any CRM activity with an exec sponsor contact in 180 days. | none |
| `relationship.days_since_last_csm_touch` | `mart_customer_health_daily.days_since_last_csm_touch` | Value plus `d`. Null when the CSM logged no outbound activity in 180 days. | `csm_touch_unknown` |
| `relationship.champion.status` | `mart_customer_health_daily.champion_status` | Same four values as the engine. | none |
| `relationship.champion.replacement_identified` | `mart_customer_health_daily.replacement_identified` | Boolean. | none |
| `health.mart_score` | `mart_customer_health_daily.health_score` | The mart's final score, for the drift check only. Never averaged with the engine's score. If a CS platform also supplies this field, the mart wins. | `warehouse_mart_stale` (null) |
| `health.score_30d_ago` | `mart_customer_health_daily.health_score_30d_ago` | The score on the row dated exactly 30 days before. Null when that day has no row. | `health_history_missing` |
| `health.score_90d_ago` | `mart_customer_health_daily.health_score_90d_ago` | The score on the row dated exactly 90 days before. | `health_history_missing` |
| `health.band_30d_ago` | `mart_customer_health_daily.health_band_30d_ago` | `green`, `yellow`, `red` or null. Never `insufficient_data`. | `health_history_missing` |
| `health.raw_weighted_sum_30d_ago` | `mart_customer_health_daily.raw_weighted_sum_30d_ago` | The scorer uses it for the trend in preference to `health.score_30d_ago`. | none (null) |
| `health.components[].contribution_30d_ago` | `mart_customer_health_daily.contrib_adoption` (and `contrib_engagement`, `contrib_support`, `contrib_sentiment`, `contrib_relationship`, `contrib_commercial`) on the row dated 30 days before | Optional second query below. Match each component `name` to the column suffix. Skip it on book runs. | none (omit) |

### Queries

Latest row per account, for the accounts being scored. One query for the whole book. Send the ids as quoted text.

```sql bigquery
SELECT
  account_id, account_name, segment, csm_owner_id, as_of_date, computed_at,
  arr, seats_purchased, days_to_renewal, payment_days_past_due, contraction_flag_90d,
  usage_observed, dau_mau_30d, mau_30d, active_users_30d,
  feature_depth_30d, feature_breadth_30d,
  seat_utilization, seat_utilization_90d_ago, utilization_drift_90d, days_since_last_login,
  engaged_contacts_90d, multithreading_depth, exec_sponsor_engaged_180d,
  days_since_last_csm_touch, champion_status, replacement_identified,
  support_observed, open_p1_p2, oldest_open_p1_age_days, tickets_per_100_seats_30d,
  avg_csat_90d, median_first_response_hours_90d,
  latest_nps, latest_nps_at, nps_trend, transcript_sentiment_30d,
  raw_weighted_sum, raw_weighted_sum_30d_ago, health_coverage,
  health_score, health_score_30d_ago, health_score_90d_ago,
  health_band, health_band_30d_ago
FROM `{project}.{dataset}.mart_customer_health_daily`
WHERE as_of_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND account_id IN ('<crm_account_id_1>', '<crm_account_id_2>')
QUALIFY ROW_NUMBER() OVER (PARTITION BY account_id ORDER BY as_of_date DESC) = 1
```

`engaged_contacts_90d`, `open_p1_p2`, `oldest_open_p1_age_days` and `health_coverage` have no Customer 360 path. Read them only to explain a drift between the engine's score and `health.mart_score`, for example when the desk's open P1 count disagrees with the mart's.

Component contributions 30 days earlier (optional). `<latest_as_of_date>` is the `as_of_date` the first query returned.

```sql bigquery
SELECT
  account_id, as_of_date,
  contrib_adoption, contrib_engagement, contrib_support,
  contrib_sentiment, contrib_relationship, contrib_commercial
FROM `{project}.{dataset}.mart_customer_health_daily`
WHERE as_of_date = DATE_SUB(DATE '<latest_as_of_date>', INTERVAL 30 DAY)
  AND account_id IN ('<crm_account_id_1>', '<crm_account_id_2>')
```

Latest complete retention row per segment and window. The mart also writes a month-to-date row for the current month (its `period_month` is this month's last day); the `period_month < CURRENT_DATE()` filter skips it.

```sql bigquery
SELECT
  period_month, period_start, window_type, segment,
  cohort_logos, start_arr, end_arr_cohort, end_arr_total,
  expansion_arr, ramp_expansion_arr, contraction_arr, churn_arr,
  churned_logos, expanded_logos, contracted_logos, new_logos, new_logo_arr,
  nrr, nrr_ex_ramp, grr, logo_churn_rate, dollar_churn_rate, net_dollar_churn,
  expansion_rate, contraction_rate, churn_concentration, churn_concentration_label,
  nrr_percentile_within_segment_history, computed_at
FROM `{project}.{dataset}.mart_retention_nrr_grr`
WHERE period_month < CURRENT_DATE()
  AND period_month >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 MONTH)
QUALIFY ROW_NUMBER() OVER (PARTITION BY segment, window_type ORDER BY period_month DESC) = 1
```

Green medians per segment, on the latest day.

```sql bigquery
SELECT
  segment,
  COUNT(*) AS green_accounts,
  APPROX_QUANTILES(health_score, 2)[OFFSET(1)] AS health_green_median,
  APPROX_QUANTILES(feature_depth_30d, 2)[OFFSET(1)] AS feature_depth_green_median
FROM `{project}.{dataset}.mart_customer_health_daily`
WHERE as_of_date = DATE '<latest_as_of_date>'
  AND health_band = 'green'
GROUP BY segment
```

### Segment benchmarks (no fixed Customer 360 path)

The schema's `benchmarks` object takes free keys, so it has no paths for the table above. The engine overrides these segment defaults (`DEFAULT_BENCHMARKS` in `src/catalogs.py`) from the two retention and green-median queries:

- `grr_ttm` from `mart_retention_nrr_grr.grr` and `nrr_ttm` from `mart_retention_nrr_grr.nrr`, on the row where `window_type` is `ttm` and `segment` is the account's segment.
- `health_green_median` and `feature_depth_green_median` from the green-median query. Keep the default when a segment has fewer than 10 green accounts.
- `retention-report` reads the full retention rows (decomposition columns included) and uses them as is.

## Vocabulary

| BigQuery mart value | Engine |
|---|---|
| `health_band`: `green`, `yellow`, `red`, `insufficient_data` | Comparison only. The engine computes its own `health.band`. |
| `health_band_30d_ago`: `green`, `yellow`, `red`, null | `health.band_30d_ago`, same values |
| `champion_status`: `active`, `at_risk`, `departed`, `none` | `relationship.champion.status`, same values |
| `nps_trend`: `improving`, `stable`, `worsening`, null | `sentiment.nps_trend`, same values |
| `segment`: `enterprise`, `mid_market`, `smb`, `digital` | `account.segment`, same values |
| `segment` in the retention mart: the four above plus `ALL` | `ALL` is the whole book; never an account segment |
| `window_type`: `monthly`, `ttm` | one-month or trailing-12-month cohort window |
| `churn_concentration_label`: `large_account_skew`, `small_account_skew`, `balanced`, `no_churn` | as is in `retention-report` |
| `usage_observed` or `support_observed` false | that block is unobserved: null fields, not zeros |
| `FLOAT64`, `INT64`, `BOOL`, `DATE`, `TIMESTAMP` | number, integer, boolean, ISO date, ISO timestamp |

## Limits and gotchas

- **Cost.** On-demand queries bill by bytes read, and `LIMIT` does not reduce the bytes read on an unclustered table. The queries here select named columns only. The dbt model does not set `partition_by`, so unless the data team partitions the health mart on `as_of_date`, the 7-day filter does not cut the bytes scanned: every query reads those columns across the mart's full history. That stays small for most customer bases but grows every day. Ask the data team to partition the mart on `as_of_date`.
- **No per-call byte cap.** Google's pages for this server do not document a maximum-bytes-billed input on `execute_sql` (confirm in setup from the tool's schema). The customer's own controls are a per-user custom quota (`QueryUsagePerUserPerDay`, on-demand pricing only, approximate) on the identity Claude uses, dataset-scoped Data Viewer, and the `goog-mcp-server: true` label to audit spend.
- **Row cap and timeout.** Results stop at 3,000 rows and queries are cancelled after three minutes. One latest-row query for a 40-account book returns 40 rows. Never query all accounts and all days.
- **Calls and quotas.** Each refresh is three direct queries (latest rows, retention, green medians) plus the optional history query. The server has no quota of its own; the BigQuery API quotas for `jobs.query` and table reads still apply.
- **Permissions.** The signed-in user's own grants decide what a query can reach. With MCP Tool User and Job User on the project and Data Viewer on the marts dataset only, Claude can read the marts and nothing else. Google documents an IAM deny policy that blocks read-write MCP tools such as `execute_sql`. Use it only if the session has `execute_sql_readonly`, or the engine loses its query tool.
- **Freshness.** The marts build nightly. The health mart's latest `as_of_date` is the latest ARR snapshot day, so it is usually yesterday. It recomputes the last 3 days on each run, so recent rows can change after the engine reads them. `CURRENT_DATE()` is UTC unless a time zone is passed.
- **Day counters age.** `days_to_renewal`, `days_since_last_login` and `days_since_last_csm_touch` are as of `as_of_date`, hence the `d` adjustment. That adjustment can move the engine's score a few tenths away from `health.mart_score`; say so when the drift check is close.
- **NPS trend basis.** The mart compares the weighted latest NPS with an unweighted NPS over days 91 to 270. Read `nps_trend` as is; do not recompute it here.
- **Champion status is current.** The mart joins today's champion status onto every row, including old ones.
- **Taxonomy names.** `docs/02_METRICS_TAXONOMY.md` mentions `nrr_monthly` and `nrr_ttm` columns. The built mart has `nrr` plus `window_type`. Use the columns listed here.
- **Location.** A query runs in the dataset's location. If a call fails on location, read the location from `get_dataset_info` and check whether the tool's schema takes one (confirm in setup).
- **Google Drive external tables** cannot be queried through this server. The marts are native tables.

## Sources

- Claude connector listing: https://claude.com/marketplace/connectors/bigquery
- BigQuery MCP tools overview: https://docs.cloud.google.com/bigquery/docs/reference/mcp/tools_overview
- BigQuery MCP reference: https://docs.cloud.google.com/bigquery/docs/reference/mcp
- Use the BigQuery MCP server (roles, `execute_sql_readonly`, limits): https://docs.cloud.google.com/bigquery/docs/use-bigquery-mcp
- Create custom query quotas: https://docs.cloud.google.com/bigquery/cost-controls
- Estimate and control costs (maximum bytes billed, `LIMIT`, dry run): https://docs.cloud.google.com/bigquery/docs/best-practices-costs
- Control access to resources with IAM (dataset-level roles): https://docs.cloud.google.com/bigquery/docs/control-access-to-resources-iam
