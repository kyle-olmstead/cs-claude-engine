# Snowflake

**Category:** `~~data warehouse` · **Claude connector:** Snowflake · **Status:** mapped from vendor documentation on 2026-10-20; not yet run against a live account. Confirm in `cs-setup`.

Snowflake serves the engine's two dbt marts through a Cortex Agent. `mart_customer_health_daily` supplies the health history the trend needs (`health.score_30d_ago`, `health.score_90d_ago`, `health.band_30d_ago`, `health.raw_weighted_sum_30d_ago`), the mart's own score for the drift check (`health.mart_score`), and inputs to all six components: usage, support, sentiment, relationship and contract. `mart_retention_nrr_grr` supplies segment NRR and GRR for the benchmarks and for `retention-report`.

## What the connector exposes

Claude's directory lists two tool kinds for this connector: Cortex Agents and Cortex Search. The connector is Snowflake's managed MCP server, an object the customer creates in its own account (`CREATE MCP SERVER`). The tools a session sees are the ones in that server's specification, under the `name` the data team gave each one.

- **Cortex Agent tool** (spec `type: "CORTEX_AGENT_RUN"`; session tool name set by the data team, for example `cs_engine_marts_agent`). Takes a plain-language question and returns the agent's answer. Snowflake says the response "includes all intermediate steps by design": reasoning, tool calls and results. For a Cortex Analyst step that means the generated `sql` and a `result_set` in the shape of Snowflake's SQL API (`resultSetMetaData` plus `data`). Every number in this map comes from that `result_set`. Build the call from the tool's own input schema in the session.
- **Cortex Search tool** (spec `type: "CORTEX_SEARCH_SERVICE_QUERY"`): not used by this map.
- The directory listing shows no SQL tool, so Claude cannot send SQL. Snowflake documents a `SYSTEM_EXECUTE_SQL` tool type (read-only by default) that a data team may add to its own server; this map does not depend on it. If setup finds one, record it in the stack profile and ask before using it.
- A directly exposed Cortex Analyst tool (`CORTEX_ANALYST_MESSAGE`) only returns the SQL it wrote; it does not run it. Use the agent, which runs the SQL on its warehouse.
- Snowflake's MCP server supports semantic views only for Cortex Analyst, not semantic model YAML files. Snowflake's Cortex Analyst docs call semantic views "the recommended approach", and YAML files on stages are legacy. So the one-time setup below uses `CREATE SEMANTIC VIEW`.

One-time setup by the customer's data team. The engine never runs any of it, and never sends DDL or DML at run time.

1. Create two semantic views, one per mart. The marts share no key, and Snowflake's rules say an expression cannot use another table's columns without a relationship. Two views keep each Analyst tool on one grain.

```sql snowflake
CREATE OR REPLACE SEMANTIC VIEW {database}.{schema}.cs_engine_health_sv

  TABLES (
    health_daily AS {database}.{schema}.mart_customer_health_daily
      PRIMARY KEY (account_id, as_of_date)
      WITH SYNONYMS ('customer health', 'health mart', 'account health')
      COMMENT = 'One row per account per day, built nightly by the cs-claude-engine dbt project'
  )

  FACTS (
    health_daily.arr AS arr COMMENT = 'Contracted ARR on as_of_date',
    health_daily.seats_purchased AS seats_purchased,
    health_daily.days_to_renewal AS days_to_renewal COMMENT = 'Days from as_of_date to the contract term end',
    health_daily.payment_days_past_due AS payment_days_past_due,
    health_daily.dau_mau_30d AS dau_mau_30d,
    health_daily.mau_30d AS mau_30d,
    health_daily.active_users_30d AS active_users_30d,
    health_daily.feature_depth_30d AS feature_depth_30d,
    health_daily.feature_breadth_30d AS feature_breadth_30d,
    health_daily.seat_utilization AS seat_utilization,
    health_daily.seat_utilization_90d_ago AS seat_utilization_90d_ago,
    health_daily.utilization_drift_90d AS utilization_drift_90d,
    health_daily.days_since_last_login AS days_since_last_login,
    health_daily.engaged_contacts_90d AS engaged_contacts_90d,
    health_daily.multithreading_depth AS multithreading_depth,
    health_daily.days_since_last_csm_touch AS days_since_last_csm_touch,
    health_daily.open_p1_p2 AS open_p1_p2,
    health_daily.oldest_open_p1_age_days AS oldest_open_p1_age_days,
    health_daily.tickets_per_100_seats_30d AS tickets_per_100_seats_30d,
    health_daily.avg_csat_90d AS avg_csat_90d,
    health_daily.median_first_response_hours_90d AS median_first_response_hours_90d,
    health_daily.latest_nps AS latest_nps,
    health_daily.transcript_sentiment_30d AS transcript_sentiment_30d,
    health_daily.contrib_adoption AS contrib_adoption,
    health_daily.contrib_engagement AS contrib_engagement,
    health_daily.contrib_support AS contrib_support,
    health_daily.contrib_sentiment AS contrib_sentiment,
    health_daily.contrib_relationship AS contrib_relationship,
    health_daily.contrib_commercial AS contrib_commercial,
    health_daily.raw_weighted_sum AS raw_weighted_sum,
    health_daily.raw_weighted_sum_30d_ago AS raw_weighted_sum_30d_ago,
    health_daily.health_coverage AS health_coverage,
    health_daily.health_score AS health_score COMMENT = 'Final health score, 0 to 100',
    health_daily.health_score_30d_ago AS health_score_30d_ago,
    health_daily.health_score_90d_ago AS health_score_90d_ago
  )

  DIMENSIONS (
    health_daily.account_id AS account_id
      WITH SYNONYMS ('account', 'crm id', 'company id')
      COMMENT = 'CRM record id. Match exactly as text.',
    health_daily.account_name AS account_name,
    health_daily.segment AS segment COMMENT = 'enterprise, mid_market, smb or digital',
    health_daily.csm_owner_id AS csm_owner_id,
    health_daily.as_of_date AS as_of_date
      COMMENT = 'Snapshot day. The latest row for an account has its highest as_of_date.',
    health_daily.computed_at AS computed_at,
    health_daily.contraction_flag_90d AS contraction_flag_90d,
    health_daily.usage_observed AS usage_observed,
    health_daily.exec_sponsor_engaged_180d AS exec_sponsor_engaged_180d,
    health_daily.champion_status AS champion_status,
    health_daily.replacement_identified AS replacement_identified,
    health_daily.support_observed AS support_observed,
    health_daily.latest_nps_at AS latest_nps_at,
    health_daily.nps_trend AS nps_trend,
    health_daily.health_band AS health_band,
    health_daily.health_band_30d_ago AS health_band_30d_ago
  )

  METRICS (
    health_daily.account_count AS COUNT(DISTINCT account_id),
    health_daily.median_health_score AS MEDIAN(health_score),
    health_daily.median_feature_depth AS MEDIAN(feature_depth_30d)
  )

  COMMENT = 'cs-claude-engine health mart. Read-only source for the Customer 360.'

  AI_SQL_GENERATION 'Return one row per account unless the question asks for a total. For the latest row per account, keep rows from the last 7 days and keep the highest as_of_date for each account_id. Match account_id values exactly as text. Return the columns the question names, with the same names, without aggregation or rounding. Never substitute a similar account.';
```

```sql snowflake
CREATE OR REPLACE SEMANTIC VIEW {database}.{schema}.cs_engine_retention_sv

  TABLES (
    retention_monthly AS {database}.{schema}.mart_retention_nrr_grr
      PRIMARY KEY (period_month, window_type, segment)
      WITH SYNONYMS ('retention', 'NRR and GRR', 'net revenue retention', 'gross revenue retention')
      COMMENT = 'One row per month-end, window and segment, built nightly by the cs-claude-engine dbt project'
  )

  FACTS (
    retention_monthly.cohort_logos AS cohort_logos,
    retention_monthly.start_arr AS start_arr,
    retention_monthly.end_arr_cohort AS end_arr_cohort,
    retention_monthly.end_arr_total AS end_arr_total,
    retention_monthly.expansion_arr AS expansion_arr,
    retention_monthly.ramp_expansion_arr AS ramp_expansion_arr,
    retention_monthly.contraction_arr AS contraction_arr,
    retention_monthly.churn_arr AS churn_arr,
    retention_monthly.churned_logos AS churned_logos,
    retention_monthly.expanded_logos AS expanded_logos,
    retention_monthly.contracted_logos AS contracted_logos,
    retention_monthly.new_logos AS new_logos,
    retention_monthly.new_logo_arr AS new_logo_arr,
    retention_monthly.nrr AS nrr COMMENT = 'Net revenue retention as a decimal',
    retention_monthly.nrr_ex_ramp AS nrr_ex_ramp,
    retention_monthly.grr AS grr COMMENT = 'Gross revenue retention as a decimal, at most 1.0',
    retention_monthly.logo_churn_rate AS logo_churn_rate,
    retention_monthly.dollar_churn_rate AS dollar_churn_rate,
    retention_monthly.net_dollar_churn AS net_dollar_churn,
    retention_monthly.expansion_rate AS expansion_rate,
    retention_monthly.contraction_rate AS contraction_rate,
    retention_monthly.churn_concentration AS churn_concentration,
    retention_monthly.nrr_percentile_within_segment_history AS nrr_percentile_within_segment_history
  )

  DIMENSIONS (
    retention_monthly.period_month AS period_month
      COMMENT = 'Month-end that closes the period. The current month is a partial month-to-date row.',
    retention_monthly.period_start AS period_start,
    retention_monthly.window_type AS window_type COMMENT = 'monthly or ttm',
    retention_monthly.segment AS segment
      COMMENT = 'enterprise, mid_market, smb, digital, or ALL for the whole book',
    retention_monthly.churn_concentration_label AS churn_concentration_label,
    retention_monthly.computed_at AS computed_at
  )

  COMMENT = 'cs-claude-engine retention mart. Read-only source for benchmarks and retention reports.'

  AI_SQL_GENERATION 'nrr, grr and every rate are stored decimals. Never sum or average them across rows. For the latest complete period, keep period_month earlier than the current date and keep the highest period_month for each segment and window_type. Return the columns the question names, with the same names.';
```

2. Create one Cortex Agent with two Cortex Analyst tools, one per semantic view. In Snowsight this is the agent's Tools tab: Cortex Analyst, Add, pick the semantic view, pick the warehouse that runs the queries, set the query timeout and description. The same agent in SQL (the `execution_environment` keys come from Snowflake's Cortex Agents REST API reference; confirm in setup that `CREATE AGENT` accepts them, or set the warehouse in Snowsight):

```sql snowflake
CREATE OR REPLACE AGENT {database}.{schema}.cs_engine_marts_agent
  COMMENT = 'Read-only answers from the cs-claude-engine marts'
  FROM SPECIFICATION
  $$
  models:
    orchestration: auto
  instructions:
    orchestration: "Use HealthMart for accounts, health scores, usage, support, sentiment, relationship and contract fields. Use RetentionMart for NRR, GRR, churn and expansion by segment. Never answer from memory."
    response: "Show the result table in full. Use the exact column names the question asks for. Do not round, rename or drop rows."
  sample_questions:
    - question: "What is the latest as_of_date in the customer health mart, and how many accounts have a row on it?"
  tools:
    - tool_spec:
        type: "cortex_analyst_text_to_sql"
        name: "HealthMart"
        description: "One row per account per day: health score, components, usage, support, NPS, relationship and contract inputs."
    - tool_spec:
        type: "cortex_analyst_text_to_sql"
        name: "RetentionMart"
        description: "One row per month-end, window (monthly or ttm) and segment: NRR, GRR, churn, expansion and contraction."
  tool_resources:
    HealthMart:
      semantic_view: "{database}.{schema}.cs_engine_health_sv"
      execution_environment:
        type: "warehouse"
        warehouse: "{WAREHOUSE}"
        query_timeout: 60
    RetentionMart:
      semantic_view: "{database}.{schema}.cs_engine_retention_sv"
      execution_environment:
        type: "warehouse"
        warehouse: "{WAREHOUSE}"
        query_timeout: 60
  $$;
```

3. Expose the agent through the MCP server, and grant a reader role only what the agent needs. Snowflake: "Access to the MCP Server does not give access to the tools."

```sql snowflake
CREATE OR REPLACE MCP SERVER {database}.{schema}.cs_engine_mcp
  FROM SPECIFICATION $$
    tools:
      - title: "CS Engine marts agent"
        name: "cs_engine_marts_agent"
        type: "CORTEX_AGENT_RUN"
        identifier: "{database}.{schema}.cs_engine_marts_agent"
        description: "Read-only answers from the cs-claude-engine health and retention marts."
  $$;

CREATE ROLE IF NOT EXISTS cs_engine_reader;
GRANT DATABASE ROLE SNOWFLAKE.CORTEX_AGENT_USER TO ROLE cs_engine_reader;
GRANT USAGE ON WAREHOUSE {WAREHOUSE} TO ROLE cs_engine_reader;
GRANT USAGE ON DATABASE {database} TO ROLE cs_engine_reader;
GRANT USAGE ON SCHEMA {database}.{schema} TO ROLE cs_engine_reader;
GRANT USAGE ON MCP SERVER {database}.{schema}.cs_engine_mcp TO ROLE cs_engine_reader;
GRANT USAGE ON AGENT {database}.{schema}.cs_engine_marts_agent TO ROLE cs_engine_reader;
GRANT SELECT ON SEMANTIC VIEW {database}.{schema}.cs_engine_health_sv TO ROLE cs_engine_reader;
GRANT SELECT ON SEMANTIC VIEW {database}.{schema}.cs_engine_retention_sv TO ROLE cs_engine_reader;
GRANT SELECT ON TABLE {database}.{schema}.mart_customer_health_daily TO ROLE cs_engine_reader;
GRANT SELECT ON TABLE {database}.{schema}.mart_retention_nrr_grr TO ROLE cs_engine_reader;
GRANT ROLE cs_engine_reader TO USER {user};
```

4. Create the OAuth security integration from Snowflake's MCP guide: Snowflake OAuth, `OAUTH_CLIENT_TYPE = 'PUBLIC'` for Claude, redirect URI `https://claude.ai/api/mcp/auth_callback`, `OAUTH_USE_SECONDARY_ROLES = NONE`, and roles limited to `cs_engine_reader`. Then connect the Claude connector to `https://<account_url>/api/v2/databases/{database}/schemas/{schema}/mcp-servers/cs_engine_mcp`.

If a `CREATE SEMANTIC VIEW` statement fails on a metric, drop that metric and rerun: the engine's questions do not depend on the metrics.

## Matching records to the CRM account

The staging model sets the mart's `account_id` to the CRM record id (`crm_companies.id`), so matching is a direct key lookup inside each question.

1. **CRM record id.** Ask for `account_id` exactly equal to the CRM id, quoted as text. HubSpot ids are numeric strings.
2. **Salesforce id length.** If the CRM is Salesforce and setup finds 15-character ids on one side and 18-character ids on the other, compare the first 15 characters, case-sensitive. Record the rule in the stack profile once (confirm in setup).
3. **Check the filter.** Read the generated `sql` in the answer. Its filter must hold exactly the ids the engine sent. An answer that matched on `account_name` or a partial id is rejected: set `warehouse_answer_unverified`.
4. **No row.** The health mart keeps only accounts with ARR above 0 on that day, so a missing row can mean churned, not started, or a different id. Never ask the agent to find the account by name. Set `warehouse_account_unmatched` and let every block fall back to its other sources.

## Setup check

One agent call, with one CRM account id from the user's book:

> Use HealthMart and RetentionMart. Return one row with these columns: latest_as_of_date (the highest as_of_date in the customer health mart), accounts_on_latest (the number of distinct account_id values on that date), sample_account_rows (the number of rows on that date where account_id is exactly '<one_crm_account_id_from_the_book>'), latest_period_month (the highest period_month in the retention mart).

The agent may answer with one or two result sets. Pass: the generated SQL reads `mart_customer_health_daily` and `mart_retention_nrr_grr` (directly or through the two semantic views), today minus `latest_as_of_date` is 2 days or less, `accounts_on_latest` is above 0, `sample_account_rows` is 1, and `latest_period_month` is not null. If the sample account has ARR 0, try another before calling the ids mismatched.

Record one of these in the status column:

- `connected (mapped; agent <agent tool name> on cs_engine_health_sv and cs_engine_retention_sv, marts current as of <latest_as_of_date>)`
- `connected (mapped; marts stale, latest as_of_date <latest_as_of_date>)`
- `connected (mapped; account ids do not match the CRM)`
- `connected (no Cortex Agent over the marts; warehouse not used)` when the server exposes no agent built on the two semantic views.
- `connected (failing: <reason>)` when the call errors.

## Field map

Every row reads the answer to the account question below. Answers come back as agent text plus result rows. Use only the rows in `result_set`. Use the text only to explain. Before using any answer, check it:

- the generated `sql` reads the health mart (or `cs_engine_health_sv`) and filters on exactly the ids sent;
- every column the question named is present (Snowflake returns unquoted names in upper case, so compare without case);
- there is at most one row per `account_id`, and its `as_of_date` is within 7 days.

If a check fails, discard the whole answer, set `warehouse_answer_unverified`, and let the blocks fall back. `d` is today minus the row's `as_of_date`, in days. If `d` is more than 2, set `warehouse_mart_stale`, leave `health.mart_score` and every current-state field to its other sources, and keep only the four history fields (`health.score_30d_ago`, `health.score_90d_ago`, `health.band_30d_ago`, `health.raw_weighted_sum_30d_ago`), saying in the explanation how many days old they are.

| Customer 360 field | Source in Snowflake | How to derive | If unavailable |
|---|---|---|---|
| `account.account_id` | `mart_customer_health_daily.account_id` | Join key only. The CRM supplies the value; the answer must hold the same text. | `warehouse_account_unmatched` |
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

### Questions the engine asks the agent

Send ids as quoted text, at most 20 accounts per question to keep the response small. Each question names every filter in full; never rely on an earlier turn.

1. **Account block** (every row above):

   > Use HealthMart. For account_id exactly in ('<crm_account_id_1>', '<crm_account_id_2>'), return one row per account: the row with the highest as_of_date within the last 7 days. No aggregation, no rounding. Return these columns with these names: account_id, account_name, segment, csm_owner_id, as_of_date, computed_at, arr, seats_purchased, days_to_renewal, payment_days_past_due, contraction_flag_90d, usage_observed, dau_mau_30d, mau_30d, active_users_30d, feature_depth_30d, feature_breadth_30d, seat_utilization, seat_utilization_90d_ago, utilization_drift_90d, days_since_last_login, engaged_contacts_90d, multithreading_depth, exec_sponsor_engaged_180d, days_since_last_csm_touch, champion_status, replacement_identified, support_observed, open_p1_p2, oldest_open_p1_age_days, tickets_per_100_seats_30d, avg_csat_90d, median_first_response_hours_90d, latest_nps, latest_nps_at, nps_trend, transcript_sentiment_30d, raw_weighted_sum, raw_weighted_sum_30d_ago, health_coverage, health_score, health_score_30d_ago, health_score_90d_ago, health_band, health_band_30d_ago.

   `engaged_contacts_90d`, `open_p1_p2`, `oldest_open_p1_age_days` and `health_coverage` have no Customer 360 path. Read them only to explain a drift between the engine's score and `health.mart_score`.

2. **Component history** (optional, `health.components[].contribution_30d_ago`):

   > Use HealthMart. For account_id exactly in ('<crm_account_id_1>', '<crm_account_id_2>'), return the rows where as_of_date is exactly <latest_as_of_date minus 30 days, as YYYY-MM-DD>. Columns: account_id, as_of_date, contrib_adoption, contrib_engagement, contrib_support, contrib_sentiment, contrib_relationship, contrib_commercial.

3. **Retention** (benchmarks and `retention-report`):

   > Use RetentionMart. For each segment and each window_type, return the row with the highest period_month that is earlier than today and within the last 3 months. Columns: period_month, period_start, window_type, segment, cohort_logos, start_arr, end_arr_cohort, end_arr_total, expansion_arr, ramp_expansion_arr, contraction_arr, churn_arr, churned_logos, expanded_logos, contracted_logos, new_logos, new_logo_arr, nrr, nrr_ex_ramp, grr, logo_churn_rate, dollar_churn_rate, net_dollar_churn, expansion_rate, contraction_rate, churn_concentration, churn_concentration_label, nrr_percentile_within_segment_history, computed_at.

   The check: the SQL filters `period_month` to before the current date (the mart's current month is a partial month-to-date row), and there is at most one row per segment and window.

4. **Green medians** (benchmarks):

   > Use HealthMart. On as_of_date <latest_as_of_date, as YYYY-MM-DD>, for each segment, among rows where health_band is 'green', return segment, the number of rows as green_accounts, the median health_score as health_green_median, and the median feature_depth_30d as feature_depth_green_median.

### Segment benchmarks (no fixed Customer 360 path)

The schema's `benchmarks` object takes free keys, so it has no paths for the table above. The engine overrides these segment defaults (`DEFAULT_BENCHMARKS` in `src/catalogs.py`) from questions 3 and 4:

- `grr_ttm` from `mart_retention_nrr_grr.grr` and `nrr_ttm` from `mart_retention_nrr_grr.nrr`, on the row where `window_type` is `ttm` and `segment` is the account's segment.
- `health_green_median` and `feature_depth_green_median` from question 4. Keep the default when a segment has fewer than 10 green accounts.
- `retention-report` reads the full retention rows (decomposition columns included) and uses them as is.

## Vocabulary

| Snowflake mart value | Engine |
|---|---|
| `HEALTH_BAND`: `green`, `yellow`, `red`, `insufficient_data` | Comparison only. The engine computes its own `health.band`. |
| `HEALTH_BAND_30D_AGO`: `green`, `yellow`, `red`, null | `health.band_30d_ago`, same values |
| `CHAMPION_STATUS`: `active`, `at_risk`, `departed`, `none` | `relationship.champion.status`, same values |
| `NPS_TREND`: `improving`, `stable`, `worsening`, null | `sentiment.nps_trend`, same values |
| `SEGMENT`: `enterprise`, `mid_market`, `smb`, `digital` | `account.segment`, same values |
| `SEGMENT` in the retention mart: the four above plus `ALL` | `ALL` is the whole book; never an account segment |
| `WINDOW_TYPE`: `monthly`, `ttm` | one-month or trailing-12-month cohort window |
| `USAGE_OBSERVED` or `SUPPORT_OBSERVED` false | that block is unobserved: null fields, not zeros |
| Column names in upper case (for example `HEALTH_SCORE`) | the lower-case names in the field map |
| `result_set.data` values | cast by the type in `resultSetMetaData`; values may arrive as text (confirm in setup) |

## Limits and gotchas

- **Cost.** Each question bills three ways: agent orchestration by tokens, Cortex Analyst by tokens, and warehouse compute for the SQL it runs. That is far more per number than a direct query. Batch accounts (about 20 per question) and run each question once per book refresh. A book of 40 needs about 4 agent calls (two account batches, retention, green medians).
- **Latency.** One agent turn plans, writes SQL, runs it and writes an answer, so it is much slower than a direct query. The agent spec can cap a turn with `orchestration.budget.seconds`. The Analyst tool's `query_timeout` caps the SQL.
- **Payload size.** Snowflake warns agent responses can reach 200 KB or more because they carry every intermediate step. Name only the columns needed. Snowflake documents a 250 KB truncation for SQL execution and custom tools, and no row limit for the agent's `result_set`. Check that the row count equals the ids sent.
- **Answers are generated.** The same question can produce different SQL on different days. Check every answer as the field map says, every time. Never take a number from the agent's prose.
- **Approval prompts.** Snowflake marks `CORTEX_AGENT_RUN` tools by default as not read-only and destructive (`readOnlyHint: false`, `destructiveHint: true`). Snowflake calls these hints, not controls. Claude may ask the user to approve each call. The agent can only read: its only tools are Analyst tools over two semantic views, and `cs_engine_reader` holds `SELECT` only. Check whether the server spec lets the data team set the hints (confirm in setup).
- **Role.** With `OAUTH_USE_SECONDARY_ROLES = NONE`, the session uses the user's default role. The connecting user's default role must be `cs_engine_reader`, or hold the same grants.
- **Region.** Snowflake says model and feature availability varies by region. If the agent fails on model access, the data team checks model availability for the account's region.
- **Freshness.** The marts build nightly. The health mart's latest `as_of_date` is the latest ARR snapshot day, usually yesterday, and the last 3 days are recomputed on each run.
- **Day counters age.** `days_to_renewal`, `days_since_last_login` and `days_since_last_csm_touch` are as of `as_of_date`, hence the `d` adjustment. It can move the engine's score a few tenths away from `health.mart_score`.
- **Champion status is current.** The mart joins today's champion status onto every row.
- **Setup is the data team's.** The semantic views, agent, MCP server, role and integration are one-time objects. New mart columns do not appear in the semantic views on their own: the data team adds them by hand, and re-runs the setup check after any change to a mart's columns.

## Sources

- Claude connector listing: https://claude.com/marketplace/connectors/snowflake
- Snowflake-managed MCP server: https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents-mcp
- CREATE MCP SERVER: https://docs.snowflake.com/en/sql-reference/sql/create-mcp-server
- CREATE SEMANTIC VIEW: https://docs.snowflake.com/en/sql-reference/sql/create-semantic-view
- Semantic view validation rules: https://docs.snowflake.com/en/user-guide/views-semantic/validation-rules
- YAML specification for semantic views (legacy custom instructions note): https://docs.snowflake.com/en/user-guide/views-semantic/semantic-view-yaml-spec
- Cortex Analyst (semantic views recommended): https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-analyst
- Cortex Agents (cost, access): https://docs.snowflake.com/user-guide/snowflake-cortex/cortex-agents
- CREATE AGENT: https://docs.snowflake.com/en/sql-reference/sql/create-agent
- Cortex Agents REST API (`tool_resources`, `execution_environment`): https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents-rest-api
- Cortex Agents run (response events, `result_set`): https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents-run
- Configure and interact with agents (Snowsight Tools tab): https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents-manage
- Build agents (privileges on semantic views): https://docs.snowflake.com/en/user-guide/snowflake-cortex/snowflake-intelligence/build-agents
