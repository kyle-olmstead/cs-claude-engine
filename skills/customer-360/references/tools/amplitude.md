# Amplitude

**Category:** `~~product analytics` · **Claude connector:** Amplitude · **Status:** mapped from vendor documentation on 2026-10-20; not yet run against a live account. Confirm in `cs-setup`.

Amplitude fills the `usage` block (active users, stickiness, feature depth, fading features, feature-gate hits) and the product value milestones in `lifecycle`. It feeds the adoption component (DAU/MAU, feature depth, seat utilization), the last-login input to engagement, the low-utilization override, and the PB-RET-02, PB-ADP-01, PB-ADP-02, PB-EXP-01 and PB-EXP-02 triggers.

## What the connector exposes

Claude's directory lists 14 Amplitude tools. Amplitude's own MCP page, checked the same day, documents a newer set of names. Where the two differ, the directory name is marked (unconfirmed) and Amplitude's documented counterpart is given. In `cs-setup`, use whichever name the session actually exposes.

- `get_context` (unconfirmed). Documented counterpart `get_amplitude_context`: returns the user, organization and accessible projects. Used to pick the project id.
- `query_dataset` (unconfirmed). Documented counterpart `query_amplitude_data`: runs ad hoc segmentation, funnels and retention, and queries existing charts. Every usage number in this map comes from this tool. The exact query shape it accepts is not documented; build it in the session from the tool's own schema.
- `get_charts`, `query_charts` (unconfirmed). Documented counterpart `get_amplitude_charts`: chart definitions and data by id. Use them when the customer already keeps a saved "active users by account" chart.
- `get_events`, `get_event_properties`, `get_user_properties` (unconfirmed). Documented counterpart `get_amp_taxonomy`: reads the tracking plan (events and properties). Used in setup to find the account key, the feature events, the gate event and the milestone events.
- `search`: documented. Finds charts, dashboards, notebooks, experiments, events, properties and cohorts.
- `get_dashboard`, `get_notebook`, `get_experiments`, `query_experiment`, `query_metric`, `get_flags`: not used by this map. `query_metric` does not appear in Amplitude's current docs.
- `get_group_types` is documented by Amplitude ("Lists group types") but is not in the directory listing. If the session lacks it, ask for the account group type name during setup.
- The connector has no seats, contracts or billing. `contract.seats_purchased` comes from `~~billing` or `~~crm`.
- Access needs the RBAC action "Use MCP (read)". The server sees only the projects the signed-in user can see. US and EU data centers use different connector URLs.
- Never call a write tool (`manage_amp_events`, `manage_amp_properties`, `create_*` and similar) from this map.

## Matching records to the CRM account

Amplitude counts users by default. Rolling users up to the CRM account needs one of these, in preference order.

1. **Accounts group (paid add-on).** The `groups` event field, `group_properties`, and the Group Identify API (`group_type`, `group_value`, `group_properties`) need the Accounts add-on. The HTTP API page says `groups` is "available to Growth or Enterprise customers who've purchased the Accounts add-on." Best case: the group value is the CRM company or account id. Next best: a group property holds the CRM id (Amplitude's Salesforce integration can set group properties). The group type name and property name are customer-defined; confirm in setup.
2. **User property, no add-on.** If the customer's instrumentation stores an account id in `user_properties` (customer-defined name; confirm in setup), group queries by that user property. Set `usage_rollup_via_user_property`.
3. **Email domain.** Only when `user_id` holds an email (customer-defined; confirm in setup) and the CRM company has one unique domain. Set `usage_matched_by_domain`. Never match on free-mail domains or on a domain shared by a parent and its subsidiaries.
4. **No match.** Do not pick the nearest name. Set `usage_account_unmatched` and `usage_unavailable`, leave the usage block null (the field-sources rule for an absent category), and read any CRM usage-sync properties that setup named.

Group values are strings and must be unique. Compare them exactly. Use the one production project confirmed in setup. Never add users across projects: the same person would count twice.

## Setup check

After `get_context` returns the project, run one `query_dataset` call: Event Segmentation, `Any Active Event`, metric `uniques`, last 7 days, grouped by the account key, limit 5.

Pass: rows come back keyed by account values, and at least one value matches a CRM account in the user's book. In the same confirmation step, ask for the core feature events, the gate event and the milestone events.

Record one of these in the status column:

- `connected (mapped; accounts via Accounts group <group type>)`
- `connected (mapped; no Accounts add-on, accounts via user property <name>)`
- `connected (no account key; usage_unavailable)`
- `connected (failing: <reason>)` when the call errors.

## Field map

| Customer 360 field | Source in Amplitude | How to derive | If unavailable |
|---|---|---|---|
| `usage.mau_30d` | Event Segmentation: `Any Active Event`, metric `uniques`, user type `active`, grouped by the account group type or the account key in `user_properties` | One query for the whole book over the last 30 days as a single range. Read this account's row. It must be a distinct count over the range, never a sum of daily `uniques`. | `usage_unavailable` (null) |
| `usage.active_users_30d` | Same query as `mau_30d` | Same as MAU. If the customer marks licensed users with a user property (customer-defined; confirm in setup), filter on it. | `usage_unavailable` (null) |
| `usage.dau_mau_30d` | `Any Active Event`, metric `uniques`, interval `i` = 1 (daily), grouped by account | Mean of the 30 daily values divided by `mau_30d`. Use the business-day mean for weekday products. If `mau_30d` is 0, set 0. | `usage_unavailable` (null) |
| `usage.wau_mau_30d` | `Any Active Event`, metric `uniques`, last 7 days as one range | 7-day distinct users divided by `mau_30d`. | none (omit) |
| `usage.days_since_last_login` | `Any Active Event`, metric `uniques`, interval `i` = 1, last 90 days | Today minus the last day with a value above 0. If no day in 90, widen once to 365 days. If still none, set the window length and flag it as a lower bound. | `last_login_beyond_window` |
| `usage.feature_depth_30d` | `event_type` of each core feature event (customer-defined; confirm in setup), metric `totals`, grouped by account | Core features with at least 1 event in 30 days divided by total core features. Core list: the customer's list if given, else the engine's `DEFAULT_FEATURE_CATALOG` (`is_core: true`) mapped to their events. | `feature_taxonomy_default` |
| `usage.feature_breadth_30d` | `event_type` of every mapped feature event, metric `totals`, grouped by account | Distinct mapped features used in 30 days divided by all mapped features. | `feature_taxonomy_default` |
| `usage.core_features_used` | Output of the depth query (`event_type` totals) | Core `feature_key` values with at least 1 event. | none |
| `usage.core_features_unused` | Output of the depth query (`event_type` totals) | Core `feature_key` values with 0 events. | none |
| `usage.power_user_ratio` | Per-user counts of core `event_type` values | Users with 3 or more distinct core features in 30 days divided by MAU. Needs a per-user breakdown; skip it if the query cannot return one. | none (omit) |
| `usage.seat_utilization` | `active_users_30d` from above; seats from `~~billing` or `~~crm` | `active_users_30d / contract.seats_purchased`, not capped. If seats are 0 or unknown, set null. | `seats_purchased_unknown` |
| `usage.seat_utilization_90d_ago` | Same MAU query (`Any Active Event`, `uniques`) on the 30-day window ending 90 days ago | Active users in days 91 to 120 ago divided by seats then (current seats if billing has no history). | `utilization_history_missing` |
| `usage.utilization_drift_90d` | Computed from the two `uniques` results above | `seat_utilization` minus `seat_utilization_90d_ago`. Set 0 if the account key was first set less than 120 days ago. | `utilization_history_missing` |
| `usage.fading_features[].feature_key` | Feature `event_type` totals, grouped by account, days 31 to 90 ago and last 30 days | Features with events in days 31 to 90 and none in the last 30. | none (omit) |
| `usage.fading_features[].last_used_days_ago` | Same `event_type`, interval `i` = 1, last 90 days | Today minus the last day with a value above 0. | none (omit) |
| `usage.fading_features[].last_user_email_hash` | `user_id` of the last user (only if setup confirms it is an email) | Hash the email the engine's way. Leave null when `user_id` is not an email. | none (null) |
| `usage.feature_gate_hits_14d[].feature_key` | `event_type` of the upgrade-prompt or gated-feature event (customer-defined; confirm in setup) and its event property naming the feature (customer-defined) | Group the last 14 days of gate events by account and by the feature property. Map the value to the engine `feature_key`. | `feature_gate_events_unmapped` |
| `usage.feature_gate_hits_14d[].hits` | Same gate `event_type`, metric `totals` | Event count per feature in 14 days. | `feature_gate_events_unmapped` |
| `usage.feature_gate_hits_14d[].gated_to_tier` | Property on the gate `event_type` naming the required tier (customer-defined), if sent | Else look the feature up in the engine pricing catalog `gated_features`. Else null. | none (null) |
| `usage.integrations_connected` | "Integration connected" `event_type` and its integration-name property (customer-defined; confirm in setup), or a group property listing integrations | Distinct integration names connected and not later disconnected, within retention. | `integrations_unknown` |
| `usage.usage_by_business_unit[].business_unit` | `user_properties` field for department or business unit (customer-defined; confirm in setup) | Second group-by on the MAU query (segmentation allows up to two group-bys). | none (omit) |
| `usage.usage_by_business_unit[].active_users_30d` | Same MAU query (`Any Active Event`, `uniques`) with the second group-by | Distinct active users per business unit for this account. | none (omit) |
| `usage.pql_score` | `group_properties` field holding a PQL score (customer-defined), only if the customer computes one on 0 to 100 | Read as is. Never derive a score here. | none (null) |
| `lifecycle.value_milestones_reached[].milestone_key` | `event_type` of each milestone event (customer-defined; confirm in setup) mapped to the engine's `DEFAULT_VALUE_MILESTONES` keys | A milestone is reached when the account has at least 1 such event. `five_active_users`: first week with 5 users who each had 3 or more sessions, from `session_id`, only if session events are queryable in this project. | `value_milestones_unmapped` |
| `lifecycle.value_milestones_reached[].reached_at` | Same `event_type`, interval `i` = 1 | Date of the first event for this account inside retention. If the account key was set after the milestone, the true date is earlier: say so in the explanation. | `value_milestones_unmapped` |
| `contract.seats_purchased` | `group_properties` field holding licensed seats (customer-defined) | Last resort after `~~billing` and `~~crm`. | `seats_purchased_unknown` |
| `contract.consumed_units_run_rate_monthly` | `event_type` of the metered event and its numeric event property (customer-defined; confirm in setup) | Sum of the property over the last 30 days, for consumption products only. Null for seat products. | none (null) |

## Vocabulary

| Amplitude | Engine |
|---|---|
| Amplitude ID ("identifies a particular user across multiple User IDs or Device IDs") | one user |
| `Any Active Event` ("Any event you track in Amplitude that you haven't marked as inactive") | the activity that makes a user active |
| Inactive event | not activity; excluded from active users |
| Group type (Accounts add-on), name customer-defined | the account key |
| Group value | `account.account_id` once matched |
| `session_id` (session start time in ms since epoch) | one session |
| `[Amplitude] Start Session`, `[Amplitude] End Session` | session boundaries, when tracked as events |
| `event_type` (customer-defined) | `feature_key`, milestone or gate event, via the setup mapping |

| Engine `feature_key` or milestone | Amplitude `event_type` |
|---|---|
| `dashboards`, `alerts`, `workflow_automation`, `api_access` (default core catalog) | customer-defined; confirm in setup |
| `first_production_workflow`, `integration_connected`, `first_report_shared` | customer-defined; confirm in setup |
| `five_active_users` | computed from `session_id`, not an event |

## Limits and gotchas

- **Accounts is a paid add-on.** It needs a Growth or Enterprise plan plus the add-on. Up to 5 group types per project, 10 group values per event, 1000 account-level properties per project.
- **Groups are not retroactive.** Group changes and group properties "apply only to new data moving forward." If the add-on or the account key is newer than 120 days, the 90-days-ago window and fading features are undercounted. Set `utilization_history_missing` and drift 0.
- **User-level groups stick.** "Once set, the group association persists for the user forever." A user who moved to another customer can keep counting for the old account until the group is overwritten.
- **Active depends on the inactive list.** "Users who only trigger inactive events don't count as active users." Ask in setup which events are marked inactive.
- **Sessions.** Web sessions time out after 30 minutes, mobile after 5 minutes of background. Start and End Session are derived from `session_id` by default and are stored as events only if session event tracking is turned on (they then count toward event volume).
- **Distinct counts.** Never sum daily `uniques` into a 30-day number. Never add users across projects.
- **Query limits.** Amplitude does not publish MCP rate limits. The Dashboard REST API limits are the closest published numbers: 5 concurrent requests, query cost up to 1000 per 5 minutes and 108,000 per hour, HTTP 429 on excess. Cost is days x conditions x query type, and each group-by counts as 4 segments. Group-by returns 100 values by default, up to 1000. Event Segmentation takes up to two events per query.
- **Book of 40.** Run each metric once for the whole book, grouped by account (about 10 to 15 queries per refresh), and slice per account. Per-account queries would cost about 40 times more.
- **Large results.** Amplitude warns that "AI platforms may truncate some large charts." Keep the group-by limit near the book size.
- **Retention.** Retention is set by Time to Live per org or project, and Amplitude "zeros out charts that query data outside the set retention period." The default period is not stated. Confirm at least 120 days are kept.
- **Time.** Event `time` is ms since epoch. Day buckets follow the project's time zone (unconfirmed). Compute `days_since_last_login` in the same zone.
- **Anonymous traffic.** Device-only users count as users until identified. If marketing pages share the project, ask in setup how to exclude them.

## Sources

- Claude connector listing: https://claude.com/marketplace/connectors/amplitude
- Amplitude MCP server: https://amplitude.com/docs/api/content/amplitude-ai/amplitude-mcp
- Amplitude MCP server (alternate pages): https://amplitude.com/docs/mcp and https://amplitude.com/docs/analytics/amplitude-mcp
- Common Amplitude MCP tasks: https://amplitude.com/docs/api/content/amplitude-ai/amplitude-mcp/common-tasks
- Account-level reporting: https://amplitude.com/docs/analytics/account-level-reporting
- Plan your Accounts instrumentation: https://amplitude.com/docs/analytics/plan-your-accounts-instrumentation
- HTTP V2 API: https://amplitude.com/docs/apis/analytics/http-v2
- Group Identify API: https://amplitude.com/docs/apis/analytics/group-identify
- Dashboard REST API: https://amplitude.com/docs/apis/analytics/dashboard-rest
- Track sessions: https://amplitude.com/docs/data/sources/instrument-track-sessions
- Helpful definitions: https://amplitude.com/docs/get-started/helpful-definitions
- Set an event's activity status: https://www.amplitude.com/docs/data/change-event-activity-status
- Time to Live: https://amplitude.com/docs/data/time-to-live
- Third-party listing of the older tool names (used only to confirm the directory names existed): https://policylayer.com/policies/amplitude
