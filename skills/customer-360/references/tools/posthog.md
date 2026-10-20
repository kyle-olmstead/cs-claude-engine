# PostHog

**Category:** `~~product analytics` · **Claude connector:** PostHog · **Status:** mapped from vendor documentation on 2026-10-20; not yet run against a live account. Confirm in `cs-setup`.

PostHog fills the `usage` block (active users, stickiness, feature depth, fading features, feature-gate hits) and the product value milestones in `lifecycle`, mostly through HogQL queries. It feeds the adoption component (DAU/MAU, feature depth, seat utilization), the last-login input to engagement, the low-utilization override, and the PB-RET-02, PB-ADP-01, PB-ADP-02, PB-EXP-01 and PB-EXP-02 triggers.

## What the connector exposes

Claude's directory lists 57 PostHog tools and shows 24. PostHog documents two generations of names: its "Run SQL" page lists `query-run`, and its current tools reference lists `execute-sql` for the same job. In `cs-setup`, use whichever name the session exposes.

- `query-run`: "Run a HogQL query and return results." It "Supports any valid HogQL syntax including joins, CTEs, subqueries, and window functions." Every usage number in this map is one HogQL query through this tool (or `execute-sql`, "Execute an SQL query.").
- `query-generate-hogql-from-question`: "Generate a HogQL query from a natural language question." It needs AI data processing approval. Optional; review its output before running and never use it unreviewed for a number.
- `insight-get` ("Get details for a specific insight by ID") and `insight-query` ("Run the query behind a saved insight and return fresh results"): use them when the customer already keeps a saved per-account insight.
- `insights-get-all` (unconfirmed). PostHog's current docs name `insights-list` ("List insights in the project, filtered by name or type").
- `event-definitions-list` ("List all event definitions in your project with volume and usage data") and `property-definitions` ("List all event and person properties in your project"): documented on PostHog's Run SQL page but not in the directory sample (unconfirmed in this connector). Used in setup to find the account key, feature events, gate event and milestone events.
- `persons-*` tools and the Customer analytics `accounts-list` / `accounts-retrieve` tools appear in PostHog's current reference but not in the directory sample (unconfirmed). This map does not rely on them.
- Write tools (`insight-create-from-query`, `insight-update`, `insight-delete`, dashboard, feature flag and experiment tools) are never called by this map.
- Calling MCP tools is free. AI-powered tools may be billed as PostHog AI spend and need AI data processing enabled for the organization. Login routes to US or EU.
- PostHog has no seats or contracts. `contract.seats_purchased` comes from `~~billing` or `~~crm`.

## Matching records to the CRM account

PostHog counts persons by default. Rolling persons up to the CRM account needs one of these, in preference order.

1. **Group analytics (paid add-on).** Group analytics "is a paid add-on," and once enabled "billing applies to all identified events" in the project. Events carry the group in `$groups` (set by `posthog.group(...)` on web, the `groups` parameter in other SDKs, or `$groupidentify` with `$group_set` for properties). PostHog's docs use `company` as the group type example; the real name is customer-defined, so confirm in setup. In HogQL, the `groups` table has `index` (zero-based), `key` and `properties`, and `key` relates to the matching events column such as `$group_0`. Find the account type's `index` in setup and use that column. Best case: the group key is the CRM id. Next best: a group property holds the CRM id or domain (customer-defined name).
2. **Person property, no add-on.** If the customer sets an account id as a person property (customer-defined; confirm in setup), group by `person.properties.<name>`. Set `usage_rollup_via_user_property`. `$set` "always reflects the last ingested value," so a person who changed accounts moves all their history.
3. **Email domain.** From a person email property (customer-defined; PostHog's examples use `email`), only when the CRM company has one unique domain. Set `usage_matched_by_domain`. Never match on free-mail domains or a domain shared by a parent and its subsidiaries.
4. **No match.** Do not pick the nearest name. Set `usage_account_unmatched` and `usage_unavailable`, leave the usage block null (the field-sources rule for an absent category), and read any CRM usage-sync properties that setup named.

Compare keys exactly. Use the one production project confirmed in setup.

## Setup check

Run one `query-run` call (replace `$group_0` with the account type's column):

```sql
SELECT $group_0 AS account_key, count(DISTINCT person_id) AS users_7d
FROM events
WHERE timestamp >= now() - INTERVAL 7 DAY
GROUP BY account_key
ORDER BY users_7d DESC
LIMIT 5
```

Pass: rows come back with non-empty keys, and at least one key matches a CRM account in the user's book. In the same step, confirm the core feature events, the gate event, the milestone events, and which events are not user activity.

Record one of these in the status column:

- `connected (mapped; accounts via group type <name>, index <n>)`
- `connected (mapped; no group analytics, accounts via person property <name>)`
- `connected (no account key; usage_unavailable)`
- `connected (failing: <reason>)`

## Field map

"Activity events" below means all events except identity calls (`$identify`, `$groupidentify`) and any other events the customer says are not user actions (candidates: `$feature_flag_called`; customer-defined list, confirm in setup). Every query filters on `timestamp` first and groups by the account column for the whole book.

| Customer 360 field | Source in PostHog | How to derive | If unavailable |
|---|---|---|---|
| `usage.mau_30d` | `events.person_id`, `events.timestamp`, `events.$group_0` (the account type's column), activity events | `count(DISTINCT person_id)` over the last 30 days, grouped by account. If anonymous traffic shares the project, keep only persons with `persons.is_identified` (join `persons.id` to `events.person_id`). | `usage_unavailable` (null) |
| `usage.active_users_30d` | Same query as `mau_30d` | Same as MAU. If a person property marks licensed users (customer-defined; confirm in setup), filter on it. | `usage_unavailable` (null) |
| `usage.dau_mau_30d` | `events.person_id` distinct per day of `events.timestamp`, activity events | Mean of the 30 daily distinct counts divided by `mau_30d`. Business-day mean for weekday products. If `mau_30d` is 0, set 0. | `usage_unavailable` (null) |
| `usage.wau_mau_30d` | `events.person_id`, `events.timestamp`, last 7 days | 7-day distinct persons divided by `mau_30d`. | none (omit) |
| `usage.days_since_last_login` | `max(events.timestamp)` of activity events per account | Today minus the latest activity date, searched over the last 365 days. If none, set the window length and flag it as a lower bound. | `last_login_beyond_window` |
| `usage.feature_depth_30d` | `events.event` in the core feature event list (customer-defined; confirm in setup) | Core features with at least 1 event in 30 days divided by total core features. Core list: the customer's list if given, else the engine's `DEFAULT_FEATURE_CATALOG` (`is_core: true`) mapped to their events. | `feature_taxonomy_default` |
| `usage.feature_breadth_30d` | `events.event` in all mapped feature events | Distinct mapped features used in 30 days divided by all mapped features. | `feature_taxonomy_default` |
| `usage.core_features_used` | Output of the depth query (`events.event`) | Core `feature_key` values with at least 1 event. | none |
| `usage.core_features_unused` | Output of the depth query (`events.event`) | Core `feature_key` values with 0 events. | none |
| `usage.power_user_ratio` | `events.person_id` and `events.event` for core events | Persons with 3 or more distinct core features in 30 days divided by MAU (one subquery per person). | none (omit) |
| `usage.seat_utilization` | `active_users_30d` from above; seats from `~~billing` or `~~crm` | `active_users_30d / contract.seats_purchased`, not capped. If seats are 0 or unknown, set null. | `seats_purchased_unknown` |
| `usage.seat_utilization_90d_ago` | Same MAU query with `timestamp` in the 30 days ending 90 days ago | Active persons in days 91 to 120 ago divided by seats then (current seats if billing has no history). | `utilization_history_missing` |
| `usage.utilization_drift_90d` | Computed from the two `events.person_id` counts above | `seat_utilization` minus `seat_utilization_90d_ago`. Set 0 if the account group started arriving on events less than 120 days ago. | `utilization_history_missing` |
| `usage.fading_features[].feature_key` | `events.event` counts per account, days 31 to 90 ago and last 30 days | Features with events in days 31 to 90 and none in the last 30. | none (omit) |
| `usage.fading_features[].last_used_days_ago` | `max(events.timestamp)` per feature event per account | Today minus the last use. | none (omit) |
| `usage.fading_features[].last_user_email_hash` | `events.person_id` of the latest event, then `persons.properties` email field (customer-defined) | Hash the email the engine's way. Null when no email property exists. | none (null) |
| `usage.feature_gate_hits_14d[].feature_key` | `events.event` = the upgrade-prompt or gated-feature event (customer-defined; confirm in setup) and `events.properties` field naming the feature (customer-defined) | Group the last 14 days by account and feature property. Map the value to the engine `feature_key`. | `feature_gate_events_unmapped` |
| `usage.feature_gate_hits_14d[].hits` | Same gate `events.event` | `count()` per feature in 14 days. | `feature_gate_events_unmapped` |
| `usage.feature_gate_hits_14d[].gated_to_tier` | `events.properties` field naming the required tier (customer-defined), if sent | Else look the feature up in the engine pricing catalog `gated_features`. Else null. | none (null) |
| `usage.integrations_connected` | "Integration connected" event and its integration-name property (customer-defined; confirm in setup), or `groups.properties` field listing integrations | Distinct integration names connected and not later disconnected, within retention. | `integrations_unknown` |
| `usage.usage_by_business_unit[].business_unit` | `persons.properties` field for department or business unit (customer-defined; confirm in setup) | Add it as a second group-by on the MAU query. | none (omit) |
| `usage.usage_by_business_unit[].active_users_30d` | Same two-group-by query on `events.person_id` | Distinct active persons per business unit for this account. | none (omit) |
| `usage.pql_score` | `groups.properties` field holding a PQL score (customer-defined), only if the customer computes one on 0 to 100 | Read as is. Never derive a score here. | none (null) |
| `lifecycle.value_milestones_reached[].milestone_key` | `events.event` = each milestone event (customer-defined; confirm in setup) mapped to the engine's `DEFAULT_VALUE_MILESTONES` keys | Reached when the account has at least 1 such event. `five_active_users`: first week where 5 persons each had 3 or more distinct `$session_id` values. | `value_milestones_unmapped` |
| `lifecycle.value_milestones_reached[].reached_at` | `min(events.timestamp)` per milestone event per account | Date of the first event inside retention. Earlier events keep the group they were captured with, so a milestone reached before group tracking began shows a later date: say so in the explanation. | `value_milestones_unmapped` |
| `contract.seats_purchased` | `groups.properties` field holding licensed seats (customer-defined) | Last resort after `~~billing` and `~~crm`. | `seats_purchased_unknown` |
| `contract.consumed_units_run_rate_monthly` | Metered event and its numeric `events.properties` field (customer-defined; confirm in setup) | `sum()` over the last 30 days, for consumption products only. Null for seat products. | none (null) |

## Vocabulary

| PostHog | Engine |
|---|---|
| Person (`persons.id`, `events.person_id`) | one user |
| `distinct_id` | an identifier that resolves to a person |
| Group type (name customer-defined), `groups.index` | the account key type |
| Group key (`groups.key`, `events.$group_0` for index 0) | `account.account_id` once matched |
| `$session_id` and the `sessions` table (`$start_timestamp`, `$end_timestamp`, `$session_duration`) | one session |
| `$pageview`, `$pageleave`, autocaptured events | activity events |
| `$identify`, `$groupidentify` | identity calls; not activity |
| `events.event` (customer-defined names) | `feature_key`, milestone or gate event, via the setup mapping |

| Engine `feature_key` or milestone | PostHog event |
|---|---|
| `dashboards`, `alerts`, `workflow_automation`, `api_access` (default core catalog) | customer-defined; confirm in setup |
| `first_production_workflow`, `integration_connected`, `first_report_shared` | customer-defined; confirm in setup |
| `five_active_users` | computed from `$session_id`, not an event |

## Limits and gotchas

- **Group analytics is a paid add-on.** Billing starts when it is enabled on the billing page and then covers all identified events. Up to 5 group types per project; deleted types do not count.
- **Groups are set at capture time.** "Earlier events keep the group they were captured with." There is no backfill, so if group tracking is newer than 120 days, set `utilization_history_missing` and drift 0.
- **Server-side events.** `posthog.group(...)` links later events in the browser session. Server-side SDKs must pass groups on every event, or that activity is not attributed. Server-side SDKs "do not send `$session_id` by default," so session-based numbers miss server-side activity.
- **Sessions.** A new session starts after 30 minutes of no activity or at the 24-hour maximum.
- **Query limits.** PostHog's query API allows 2,400 requests per hour, 240 per minute and 3 concurrent queries per project, with a 10-second execution limit (queued queries wait up to 30 seconds). Some legacy customers are on 120 queries per hour. Over budget returns HTTP 429 `api_queries_budget_exceeded`. Whether MCP calls share these limits is not documented (unconfirmed).
- **Rows.** Queries return 100 rows by default and up to 50,000 with an explicit `LIMIT`. Always set `LIMIT` above the book size. `OFFSET` pagination is not supported for programmatic requests.
- **Book of 40.** One grouped query per metric covers the book (about 10 to 12 queries per refresh). Filter on `timestamp` first to stay under 10 seconds. Read person properties from the `persons` table; PostHog flags `any(person.properties)` over `events` as a slow pattern.
- **Not an export path.** PostHog says the query endpoint is "not a supported export mechanism." Pull aggregates, not raw events.
- **Retention.** PostHog Cloud keeps events 1 year on the free tier and 7 years on paid plans; older events are left out of results. A free project still covers every window here, but `reached_at` cannot look back past 1 year.
- **Time.** `timestamp` is ISO 8601. Whether HogQL date functions use the project time zone is unconfirmed; compute day boundaries the same way for every account.

## Sources

- Claude connector listing: https://claude.com/marketplace/connectors/posthog
- Model Context Protocol (MCP): https://posthog.com/docs/model-context-protocol
- PostHog MCP tools reference: https://posthog.com/docs/model-context-protocol/tools.md
- Run SQL and manage views with MCP: https://posthog.com/docs/data-warehouse/run-sql-mcp
- Use product analytics over PostHog MCP: https://posthog.com/docs/product-analytics/surfaces/mcp
- Build insights with MCP: https://posthog.com/docs/product-analytics/build-insights-mcp
- Group analytics: https://posthog.com/docs/product-analytics/group-analytics
- PostHog system tables (events, persons, groups, sessions): https://posthog.com/docs/data-warehouse/sources/posthog
- SQL: https://posthog.com/docs/sql
- API queries (limits): https://posthog.com/docs/api/queries
- Sessions: https://posthog.com/docs/data/sessions
- Events: https://posthog.com/docs/data/events
- Person properties: https://posthog.com/docs/data/user-properties
- Trends: https://posthog.com/docs/product-analytics/trends/overview
- Events data retention: https://posthog.com/docs/data/events-retention
