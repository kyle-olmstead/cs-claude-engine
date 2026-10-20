# Databricks

**Category:** `~~data warehouse` · **Claude connector:** Databricks Genie · **Status:** mapped from vendor documentation on 2026-10-20; not yet run against a live account. Confirm in `cs-setup`.

Databricks serves the engine's two dbt marts through Genie. `mart_customer_health_daily` supplies the health history the trend needs (`health.score_30d_ago`, `health.score_90d_ago`, `health.band_30d_ago`, `health.raw_weighted_sum_30d_ago`), the mart's own score for the drift check (`health.mart_score`), and inputs to all six components: usage, support, sentiment, relationship and contract. `mart_retention_nrr_grr` supplies segment NRR and GRR for the benchmarks and for `retention-report`.

## What the connector exposes

Claude's directory lists five tools. They match Databricks' Genie One MCP server (`https://<workspace-hostname>/ai-gateway/mcp-services/system.ai.genie_one_mcp`, OAuth with the `ai-gateway` scope).

- `genie_ask`: asks Genie a plain-language data question and starts a response. Returns `conversation_id`, `response_id` and `status`. Passing a `conversation_id` continues that conversation.
- `view_ask`: the same question, opened as an interactive view. Databricks offers it "instead of `genie_ask` to MCP Apps clients, and preferred when available". Use whichever of the two the session offers. The rows still come from `genie_get_query_result`.
- `genie_poll_response`: the latest state of a response: progress steps, the final answer, deep links to the Databricks sources used, and query results that are truncated on purpose. Wait for one poll to finish before sending the next.
- `genie_get_query_result`: "the full SQL result, including column schema and rows, for a query Genie ran". Every number in this map comes from this tool. Build the call from the ids `genie_poll_response` returns and the tool's own input schema in the session.
- `genie_cancel_response`: cancels a turn still running.

What this means for the engine:

- **Routing.** This server answers through Genie One chat, which "first searches available Genie Agents for a match, then searches across dashboards, queries, and metric views." Databricks documents no parameter that pins a question to one Genie Agent. So every question names the agent the data team builds below, and every answer is checked against its sources and SQL. Genie Agents were formerly called Genie spaces.
- **Generated SQL.** Databricks' Conversation API returns the generated query statement with each answer, and agent editors can see it. The MCP page does not say whether `genie_poll_response` or `genie_get_query_result` carry the SQL text (confirm in setup). If the session shows no SQL, the engine checks the sources, columns and row counts only.
- **Warehouse.** A `warehouse_id` in the `_meta` parameters of `genie_ask` or `view_ask` runs the query on that SQL warehouse. Setup records the warehouse id.
- **Read-only.** Genie writes and runs `SELECT` queries. Unity Catalog permissions always apply. The engine never sends DDL or DML.
- **Other servers.** Databricks also documents a Genie Agent MCP server for one agent at `https://<workspace-hostname>/api/2.0/mcp/genie/{genie_space_id}` (read-only, no conversation history). Its tool names are not documented and it is not the directory connector, so this map does not use it. The old Beta endpoint `https://<workspace-hostname>/api/2.0/mcp/genie` is deprecated and sunsets on October 31, 2026.

One-time setup by the customer's data team. The engine never runs any of it.

1. **Create a Genie Agent** titled `CS Engine marts`, on a pro or serverless SQL warehouse. Description: "Read-only answers for the cs-claude-engine plugin from its two dbt marts."
2. **Data.** Add exactly two tables: `{catalog}.{schema}.mart_customer_health_daily` and `{catalog}.{schema}.mart_retention_nrr_grr`. Define no join between them. Write column comments in Unity Catalog (the descriptions in `dbt/models/marts/schema.yml` and the field map below) so Genie sees them.
3. **General instructions** (one text block):

```text
This agent answers read-only questions for the cs-claude-engine plugin.
Tables:
- mart_customer_health_daily: one row per account per day. Key: account_id and as_of_date.
  account_id is the CRM record id. Match it exactly as text.
- mart_retention_nrr_grr: one row per period_month, window_type (monthly or ttm) and segment.
  Segment ALL is the whole book.
Rules:
- Never join the two tables.
- The latest row for an account is its row with the highest as_of_date in the last 7 days.
- Return one row per account with exactly the column names the question asks for.
  Do not aggregate, round, rename or drop columns.
- nrr, grr and every rate are decimals. Never sum or average them across rows.
- The current month in mart_retention_nrr_grr is a partial month-to-date row.
  For the latest complete period, use period_month earlier than today.
- If an account id has no row, return nothing for it. Never substitute a similar name.
```

4. **Example SQL queries.** Add these five, each titled with the question it answers. `:name` marks a Genie parameter. The engine sends `:account_ids` as one comma-separated string with no spaces (confirm the parameter type in setup).

Latest row per account:

```sql databricks
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
FROM {catalog}.{schema}.mart_customer_health_daily
WHERE as_of_date >= date_sub(current_date(), 7)
  AND array_contains(split(:account_ids, ','), account_id)
QUALIFY row_number() OVER (PARTITION BY account_id ORDER BY as_of_date DESC) = 1
```

Component contributions 30 days before a given day:

```sql databricks
SELECT
  account_id, as_of_date,
  contrib_adoption, contrib_engagement, contrib_support,
  contrib_sentiment, contrib_relationship, contrib_commercial
FROM {catalog}.{schema}.mart_customer_health_daily
WHERE as_of_date = date_sub(to_date(:latest_as_of_date), 30)
  AND array_contains(split(:account_ids, ','), account_id)
```

Latest complete retention row per segment and window:

```sql databricks
SELECT
  period_month, period_start, window_type, segment,
  cohort_logos, start_arr, end_arr_cohort, end_arr_total,
  expansion_arr, ramp_expansion_arr, contraction_arr, churn_arr,
  churned_logos, expanded_logos, contracted_logos, new_logos, new_logo_arr,
  nrr, nrr_ex_ramp, grr, logo_churn_rate, dollar_churn_rate, net_dollar_churn,
  expansion_rate, contraction_rate, churn_concentration, churn_concentration_label,
  nrr_percentile_within_segment_history, computed_at
FROM {catalog}.{schema}.mart_retention_nrr_grr
WHERE period_month < current_date()
  AND period_month >= add_months(current_date(), -3)
QUALIFY row_number() OVER (PARTITION BY segment, window_type ORDER BY period_month DESC) = 1
```

Green medians per segment on a given day:

```sql databricks
SELECT
  segment,
  count(*) AS green_accounts,
  median(health_score) AS health_green_median,
  median(feature_depth_30d) AS feature_depth_green_median
FROM {catalog}.{schema}.mart_customer_health_daily
WHERE as_of_date = to_date(:as_of_date)
  AND health_band = 'green'
GROUP BY segment
```

Freshness check:

```sql databricks
SELECT
  h.latest_as_of_date,
  datediff(current_date(), h.latest_as_of_date) AS days_behind,
  h.accounts_on_latest,
  h.sample_account_rows,
  r.latest_period_month
FROM (
  SELECT
    as_of_date AS latest_as_of_date,
    count(*) AS accounts_on_latest,
    count_if(account_id = :sample_account_id) AS sample_account_rows
  FROM {catalog}.{schema}.mart_customer_health_daily
  WHERE as_of_date >= date_sub(current_date(), 7)
  GROUP BY as_of_date
  ORDER BY as_of_date DESC
  LIMIT 1
) AS h
CROSS JOIN (
  SELECT max(period_month) AS latest_period_month
  FROM {catalog}.{schema}.mart_retention_nrr_grr
) AS r
```

5. **Sample questions.** Use the five questions under the field map, so users see the agent's purpose.
6. **Permissions.** Share the agent with the users who connect Claude. They need `SELECT` on the two tables and CAN USE on the agent's SQL warehouse. The creator needs at least CAN EDIT on the agent.
7. **Routing help.** A workspace admin can add one line to the Genie One chat instructions file `/Workspace/.genie_workspace_instructions.md` (chat only, under 20,000 characters): "Questions that name the CS Engine marts Genie Agent go to that agent."

## Matching records to the CRM account

The staging model sets the mart's `account_id` to the CRM record id (`crm_companies.id`), so matching is a direct key lookup inside each question.

1. **CRM record id.** Ask for `account_id` exactly equal to the CRM id. HubSpot ids are numeric strings: send them as text.
2. **Salesforce id length.** If the CRM is Salesforce and setup finds 15-character ids on one side and 18-character ids on the other, compare the first 15 characters, case-sensitive. Record the rule in the stack profile once (confirm in setup).
3. **Check the answer.** Every returned `account_id` must be one the engine sent. If the SQL is visible, its filter must hold exactly those ids. An answer that matched on `account_name` is rejected: set `warehouse_answer_unverified`.
4. **No row.** The health mart keeps only accounts with ARR above 0 on that day, so a missing row can mean churned, not started, or a different id. Never ask Genie to find the account by name. Set `warehouse_account_unmatched` and let every block fall back to its other sources.

## Setup check

One question with `genie_ask` (or `view_ask`), then `genie_poll_response` until the status is `completed`, then `genie_get_query_result`:

> In the Genie Agent CS Engine marts, return one row with these columns: latest_as_of_date (the highest as_of_date in mart_customer_health_daily within the last 7 days), days_behind (days from that date to today), accounts_on_latest (rows on that date), sample_account_rows (rows on that date where account_id is exactly '<one_crm_account_id_from_the_book>'), latest_period_month (the highest period_month in mart_retention_nrr_grr).

Pass: the response's sources point to the CS Engine marts agent or the two mart tables, `days_behind` is 2 or less, `accounts_on_latest` is above 0, `sample_account_rows` is 1, and `latest_period_month` is not null. If the sample account has ARR 0, try another before calling the ids mismatched. Record in setup whether the SQL text was visible.

Record one of these in the status column:

- `connected (mapped; Genie Agent CS Engine marts, marts current as of <latest_as_of_date>)`
- `connected (mapped; marts stale, latest as_of_date <latest_as_of_date>)`
- `connected (mapped; Genie One answered from another source)` when the sources are not the CS Engine marts agent. The warehouse is not used until routing is fixed.
- `connected (mapped; account ids do not match the CRM)`
- `connected (no Genie Agent over the marts; warehouse not used)`
- `connected (failing: <reason>)` when a call errors or the poll ends `failed`.

## Field map

Every row reads the rows `genie_get_query_result` returns for the account question below. Never take a number from Genie's text answer or from the truncated rows in `genie_poll_response`. Before using any result, check it:

- the sources (and the SQL, when visible) are the CS Engine marts agent and `mart_customer_health_daily`;
- every column the question named is present, with the same name;
- there is at most one row per `account_id`, every id is one the engine sent, and `as_of_date` is within 7 days.

If a check fails, discard the whole result, set `warehouse_answer_unverified`, and let the blocks fall back. `d` is today minus the row's `as_of_date`, in days. If `d` is more than 2, set `warehouse_mart_stale`, leave `health.mart_score` and every current-state field to its other sources, and keep only the four history fields (`health.score_30d_ago`, `health.score_90d_ago`, `health.band_30d_ago`, `health.raw_weighted_sum_30d_ago`), saying in the explanation how many days old they are.

| Customer 360 field | Source in Databricks | How to derive | If unavailable |
|---|---|---|---|
| `account.account_id` | `mart_customer_health_daily.account_id` | Join key only. The CRM supplies the value; the result must hold the same text. | `warehouse_account_unmatched` |
| `account.name` | `mart_customer_health_daily.account_name` | Cross-check only. The CRM wins. | none |
| `account.segment` | `mart_customer_health_daily.segment` | Cross-check only. The CRM value through `segment_map` wins. Picks the retention and benchmark rows. | none |
| `account.csm_owner_id` | `mart_customer_health_daily.csm_owner_id` | Cross-check only. The CRM wins. | none |
| `contract.arr` | `mart_customer_health_daily.arr` | Use when the stack profile names the warehouse as the contract source or no `~~billing` is connected. Otherwise billing wins; report a gap over 5 percent as `arr_source_disagreement`. | `arr_history_missing` |
| `contract.seats_purchased` | `mart_customer_health_daily.seats_purchased` | Same precedence as `contract.arr`. | `seats_purchased_unknown` |
| `contract.days_to_renewal` | `mart_customer_health_daily.days_to_renewal` | Value minus `d`. If billing or the CRM gives `contract.term_end`, compute from that instead. | none |
| `contract.payment_days_past_due` | `mart_customer_health_daily.payment_days_past_due` | Value as of `as_of_date`. Do not add `d`. | `payment_status_unknown` |
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
| `support.avg_csat_90d` | `mart_customer_health_daily.avg_csat_90d` | Mean ticket CSAT for tickets resolved in 90 days, on a 1 to 5 scale. | `support_unavailable` |
| `support.median_first_response_hours_90d` | `mart_customer_health_daily.median_first_response_hours_90d` | Hours, tickets created in 90 days. | `support_unavailable` |
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
| `health.components[].contribution_30d_ago` | `mart_customer_health_daily.contrib_adoption` (and `contrib_engagement`, `contrib_support`, `contrib_sentiment`, `contrib_relationship`, `contrib_commercial`) on the row dated 30 days before | Optional history question below. Match each component `name` to the column suffix. Skip it on book runs. | none (omit) |

### Questions the engine asks Genie

Each question starts by naming the agent and states every filter in full. Reuse one `conversation_id` for a run so Genie stays with the agent, but never rely on an earlier turn's filters. Send at most 20 ids per question.

1. **Account block** (every row above):

   > In the Genie Agent CS Engine marts: for account_id exactly in ('<crm_account_id_1>', '<crm_account_id_2>'), return one row per account from mart_customer_health_daily, the row with the highest as_of_date within the last 7 days. No aggregation, no rounding. Return these columns with these names: account_id, account_name, segment, csm_owner_id, as_of_date, computed_at, arr, seats_purchased, days_to_renewal, payment_days_past_due, contraction_flag_90d, usage_observed, dau_mau_30d, mau_30d, active_users_30d, feature_depth_30d, feature_breadth_30d, seat_utilization, seat_utilization_90d_ago, utilization_drift_90d, days_since_last_login, engaged_contacts_90d, multithreading_depth, exec_sponsor_engaged_180d, days_since_last_csm_touch, champion_status, replacement_identified, support_observed, open_p1_p2, oldest_open_p1_age_days, tickets_per_100_seats_30d, avg_csat_90d, median_first_response_hours_90d, latest_nps, latest_nps_at, nps_trend, transcript_sentiment_30d, raw_weighted_sum, raw_weighted_sum_30d_ago, health_coverage, health_score, health_score_30d_ago, health_score_90d_ago, health_band, health_band_30d_ago.

   `engaged_contacts_90d`, `open_p1_p2`, `oldest_open_p1_age_days` and `health_coverage` have no Customer 360 path. Read them only to explain a drift between the engine's score and `health.mart_score`.

2. **Component history** (optional, `health.components[].contribution_30d_ago`):

   > In the Genie Agent CS Engine marts: for account_id exactly in ('<crm_account_id_1>', '<crm_account_id_2>'), return the rows of mart_customer_health_daily where as_of_date is exactly <latest_as_of_date minus 30 days, as YYYY-MM-DD>. Columns: account_id, as_of_date, contrib_adoption, contrib_engagement, contrib_support, contrib_sentiment, contrib_relationship, contrib_commercial.

3. **Retention** (benchmarks and `retention-report`):

   > In the Genie Agent CS Engine marts: from mart_retention_nrr_grr, for each segment and each window_type, return the row with the highest period_month that is earlier than today and within the last 3 months. Columns: period_month, period_start, window_type, segment, cohort_logos, start_arr, end_arr_cohort, end_arr_total, expansion_arr, ramp_expansion_arr, contraction_arr, churn_arr, churned_logos, expanded_logos, contracted_logos, new_logos, new_logo_arr, nrr, nrr_ex_ramp, grr, logo_churn_rate, dollar_churn_rate, net_dollar_churn, expansion_rate, contraction_rate, churn_concentration, churn_concentration_label, nrr_percentile_within_segment_history, computed_at.

4. **Green medians** (benchmarks):

   > In the Genie Agent CS Engine marts: in mart_customer_health_daily on as_of_date <latest_as_of_date, as YYYY-MM-DD>, for each segment, among rows where health_band is 'green', return segment, the number of rows as green_accounts, the median health_score as health_green_median, and the median feature_depth_30d as feature_depth_green_median.

5. **Freshness** (the setup check question, also asked at the start of each book run).

Databricks says that in chat mode, when Genie uses the exact text of a parameterized example query in a response, it gives a verified answer. That is why the example queries above take parameters. Note in the explanation whether an answer came back verified.

### Segment benchmarks (no fixed Customer 360 path)

The schema's `benchmarks` object takes free keys, so it has no paths for the table above. The engine overrides these segment defaults (`DEFAULT_BENCHMARKS` in `src/catalogs.py`) from questions 3 and 4:

- `grr_ttm` from `mart_retention_nrr_grr.grr` and `nrr_ttm` from `mart_retention_nrr_grr.nrr`, on the row where `window_type` is `ttm` and `segment` is the account's segment.
- `health_green_median` and `feature_depth_green_median` from question 4. Keep the default when a segment has fewer than 10 green accounts.
- `retention-report` reads the full retention rows (decomposition columns included) and uses them as is.

## Vocabulary

| Databricks mart value | Engine |
|---|---|
| `health_band`: `green`, `yellow`, `red`, `insufficient_data` | Comparison only. The engine computes its own `health.band`. |
| `health_band_30d_ago`: `green`, `yellow`, `red`, null | `health.band_30d_ago`, same values |
| `champion_status`: `active`, `at_risk`, `departed`, `none` | `relationship.champion.status`, same values |
| `nps_trend`: `improving`, `stable`, `worsening`, null | `sentiment.nps_trend`, same values |
| `segment`: `enterprise`, `mid_market`, `smb`, `digital` | `account.segment`, same values |
| `segment` in the retention mart: the four above plus `ALL` | `ALL` is the whole book; never an account segment |
| `window_type`: `monthly`, `ttm` | one-month or trailing-12-month cohort window |
| Genie status `in_progress`, `completed`, `incomplete`, `failed` | keep polling, read the result, treat as failed, treat as failed |
| Result values (the Genie API returns every non-null value as text, nulls as JSON null) | cast by each column's `type_text`; `"true"` and `"false"` to booleans; dates as `YYYY-MM-DD` (confirm the MCP result keeps this format in setup) |

## Limits and gotchas

- **Cost.** Queries run on the agent's pro or serverless SQL warehouse and bill as Databricks SQL compute. A warehouse that has stopped must start first, which adds time and cost to the first question of a run.
- **Latency.** Genie is asynchronous: ask, poll, then fetch. Databricks' Conversation API guidance is to poll every 1 to 5 seconds with backoff and give up after about 10 minutes. After that, call `genie_cancel_response` and fall back.
- **Throughput.** The Conversation API supports about five questions per minute per workspace, best effort. The MCP page publishes no limit. A book of 40 needs about 5 questions (freshness, two account batches, retention, green medians).
- **Row cap.** The Genie API returns at most 5,000 rows per query result. `genie_ask` and `genie_poll_response` truncate results on purpose, and very large results are truncated even in `genie_get_query_result`. Check that the row count equals the ids sent.
- **Routing is the weak point.** Genie One may answer from another Genie Agent, a dashboard or a metric view that looks similar. Check the sources on every answer. If routing keeps failing, the data team can expose the one agent through the Genie Agent MCP server as a separate custom connector; that path is outside this map.
- **Answers are generated.** The same question can produce different SQL on different days. Check every result as the field map says.
- **Agent limits.** Up to 50 tables, views or metric views per agent; 100 instructions (each example query and the general instructions block count as one); 200 knowledge store snippets.
- **Endpoint sunset.** A connector still pointed at `https://<workspace-hostname>/api/2.0/mcp/genie` stops working on October 31, 2026. Move it to the Genie One MCP URL.
- **Permissions.** On-behalf-of OAuth means Genie sees what the signed-in user can see in Unity Catalog. The user needs `SELECT` on both marts and CAN USE on the warehouse.
- **Freshness.** The marts build nightly. The health mart's latest `as_of_date` is the latest ARR snapshot day, usually yesterday, and the last 3 days are recomputed on each run.
- **Day counters age.** `days_to_renewal`, `days_since_last_login` and `days_since_last_csm_touch` are as of `as_of_date`, hence the `d` adjustment. It can move the engine's score a few tenths away from `health.mart_score`.
- **Champion status is current.** The mart joins today's champion status onto every row.

## Sources

- Claude connector listing: https://claude.com/marketplace/connectors/databricks
- Genie One MCP server: https://docs.databricks.com/aws/en/agents/mcp/genie-mcp
- Genie Agent MCP server (single agent): https://docs.databricks.com/aws/en/agents/mcp-tools/genie-agent
- Genie One: https://docs.databricks.com/aws/en/genie-one
- Genie One chat (routing, workspace instructions file): https://docs.databricks.com/genie-one/chat
- Create and manage a Genie Agent: https://docs.databricks.com/aws/en/genie-agents/set-up
- Tune Genie Agent quality (instructions, example SQL, parameters, limits): https://docs.databricks.com/aws/en/genie-agents/tune-quality
- Genie Conversation API (5,000 rows, five questions per minute, polling): https://learn.microsoft.com/azure/databricks/genie/conversation-api
- Get message attachment query result (`statement_response`, `data_array`): https://docs.databricks.com/api/genie/v1/genie-get-message-attachment-query-result.md
- QUALIFY clause: https://docs.databricks.com/aws/en/sql/language-manual/sql-ref-syntax-qry-select-qualify
