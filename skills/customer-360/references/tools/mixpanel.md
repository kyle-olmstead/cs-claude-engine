# Mixpanel

**Category:** `~~product analytics` · **Claude connector:** Mixpanel · **Status:** mapped from vendor documentation on 2026-10-20; not yet run against a live account. Confirm in `cs-setup`.

Mixpanel fills the `usage` block (active users, stickiness, feature depth, fading features, feature-gate hits) and the product value milestones in `lifecycle`. It feeds the adoption component (DAU/MAU, feature depth, seat utilization), the last-login input to engagement, the low-utilization override, and the PB-RET-02, PB-ADP-01, PB-ADP-02, PB-EXP-01 and PB-EXP-02 triggers.

## What the connector exposes

Claude's directory lists 20 Mixpanel tools. Mixpanel's MCP page documents most of them. Two directory names are not in Mixpanel's current docs and are marked (unconfirmed).

- `Get-Projects`: "List your projects and workspaces." Used to pick the project.
- `Get-Events`: "Browse and search events in a project, optionally including full metadata." Used in setup to find feature, gate and milestone events.
- `Get-Event-Details` (unconfirmed). Not in Mixpanel's current docs. `Get-Events` with full metadata covers the same need.
- `Get-Property-Names` (unconfirmed). Mixpanel's current docs name `List-Properties` ("List and search event or user properties in a project") for this job. Used in setup to find the account key.
- `Get-Property-Values`: "Discover values for a specific property." Used in setup to check that account key values look like CRM ids.
- `Get-Query-Schema`: "Get the full JSON schema for building a query." Read it before the first `Run-Query`.
- `Run-Query`: "Execute insights, funnels, flows, and retention queries." Every usage number in this map comes from Insights queries through this tool. It "cannot filter or break down results by cohort."
- `Get-Report`, `List-Dashboards`, `Get-Dashboard`: read saved reports and boards. Use `Get-Report` when the customer already keeps an "active users by company" report.
- `Get-Business-Context` is documented ("Get org- and project-specific business context, vocabulary, and query instructions") but is not in the directory sample. If present, read it in setup; it may name the company key.
- Write tools in the directory (`Edit-Event`, `Edit-Property`, `Create-Tag`, `Rename-Tag`, `Delete-Tag`, `Dismiss-Issues`, `Create-Dashboard`) are never called by this map. `Get-Issues`, `Get-Lexicon-URL` and `Get-User-Replays-Data` are not used.
- The connector has no seats, contracts or billing. `contract.seats_purchased` comes from `~~billing` or `~~crm`.
- An org admin must turn MCP on in Settings > Org > Overview, except for free and growth accounts created after August 1, 2026. US, EU and IN projects use different server URLs.

## Matching records to the CRM account

Mixpanel counts unique users by `distinct_id` by default. Rolling users up to the CRM account needs one of these, in preference order.

1. **Group key (Group Analytics add-on).** "Customers on an Enterprise or Growth plan can access Group Analytics as an add-on package." A group key is an event property set up in Project Settings. Mixpanel's docs use `company_id` as the example; the real name is customer-defined, so confirm in setup. If a B2B Company Key is designated, use it. Best case: the key value is the CRM company or account id. Next best: a group profile property (set with `group_set`) holds the CRM id (customer-defined name).
2. **Event property, no add-on.** If every event carries an account id property (customer-defined; confirm in setup), break Insights down by that property. Per-account user counts work the same; you lose group profiles and unique-company counts. No extra flag.
3. **User profile property.** If only the user profile holds the account id (customer-defined), break down by it and set `usage_rollup_via_user_property`. Profiles join to events at query time with their latest values, so a user who changed accounts moves all their history.
4. **Email domain.** From the reserved profile property `$email`, only when the CRM company has one unique domain. Set `usage_matched_by_domain`. Never match on free-mail domains or a domain shared by a parent and its subsidiaries.
5. **No match.** Do not pick the nearest name. Set `usage_account_unmatched` and `usage_unavailable`, leave the usage block null (the field-sources rule for an absent category), and read any CRM usage-sync properties that setup named.

Group key values are lists of strings, so one event can belong to several companies. Compare values exactly. Use the one production project confirmed in setup.

## Setup check

After `Get-Projects` returns the project, read `Get-Query-Schema`, then run one `Run-Query`: Insights, `All Events`, `Unique Users`, last 7 days, broken down by the account key, top 5 segments.

Pass: rows come back keyed by account values, and at least one value matches a CRM account in the user's book. In the same confirmation step, ask for the core feature events, the gate event and the milestone events.

Record one of these in the status column:

- `connected (mapped; accounts via group key <name>)`
- `connected (mapped; no Group Analytics, accounts via event property <name>)`
- `connected (mapped; accounts via profile property <name>)`
- `connected (no account key; usage_unavailable)`
- `connected (failing: <reason>)`, for example MCP not enabled for the org.

## Field map

| Customer 360 field | Source in Mixpanel | How to derive | If unavailable |
|---|---|---|---|
| `usage.mau_30d` | Insights `MAU` ("users who performed [event] within the last 30 days") on `All Events`, broken down by the account key | One query for the whole book. Read this account's value on the as-of date. | `usage_unavailable` (null) |
| `usage.active_users_30d` | Same query as `mau_30d` | Same as MAU. If the customer marks licensed users with a profile property (customer-defined; confirm in setup), filter on it. | `usage_unavailable` (null) |
| `usage.dau_mau_30d` | Insights `Unique Users` on `All Events`, by day, last 30 days, broken down by the account key | Mean of the 30 daily values divided by `mau_30d`. Business-day mean for weekday products. If `mau_30d` is 0, set 0. | `usage_unavailable` (null) |
| `usage.wau_mau_30d` | Insights `WAU` ("users who performed [event] within the last 7 days") on `All Events` | `WAU` on the as-of date divided by `mau_30d`. | none (omit) |
| `usage.days_since_last_login` | Insights `Unique Users` on `All Events`, by day, last 90 days | Today minus the last day with a value above 0. If none in 90 days, widen once (stay within the 93-day `All Events` cap per query). If still none, set the window length and flag it as a lower bound. Do not use `$last_seen`: it is the profile's last update, not the last event. | `last_login_beyond_window` |
| `usage.feature_depth_30d` | Insights `Total Events` of each core feature event (customer-defined; confirm in setup), broken down by the account key | Core features with at least 1 event in 30 days divided by total core features. Core list: events carrying the customer's Lexicon "core" tag if they keep one (tag name customer-defined), else the engine's `DEFAULT_FEATURE_CATALOG` (`is_core: true`) mapped to their events. | `feature_taxonomy_default` |
| `usage.feature_breadth_30d` | Insights `Total Events` of every mapped feature event | Distinct mapped features used in 30 days divided by all mapped features. | `feature_taxonomy_default` |
| `usage.core_features_used` | Output of the depth query (`Total Events`) | Core `feature_key` values with at least 1 event. | none |
| `usage.core_features_unused` | Output of the depth query (`Total Events`) | Core `feature_key` values with 0 events. | none |
| `usage.power_user_ratio` | Per-user counts of core events, broken down by `distinct_id` | Users with 3 or more distinct core features in 30 days divided by MAU. Skip it if the query cannot return per-user rows for the account. | none (omit) |
| `usage.seat_utilization` | `active_users_30d` from above; seats from `~~billing` or `~~crm` | `active_users_30d / contract.seats_purchased`, not capped. If seats are 0 or unknown, set null. | `seats_purchased_unknown` |
| `usage.seat_utilization_90d_ago` | Insights `MAU` on `All Events` on the date 90 days ago | Active users in the 30 days ending 90 days ago divided by seats then (current seats if billing has no history). | `utilization_history_missing` |
| `usage.utilization_drift_90d` | Computed from the two `MAU` results above | `seat_utilization` minus `seat_utilization_90d_ago`. Set 0 if the account key started arriving on events less than 120 days ago. | `utilization_history_missing` |
| `usage.fading_features[].feature_key` | Insights `Total Events` per feature event, broken down by the account key, days 31 to 90 ago and last 30 days | Features with events in days 31 to 90 and none in the last 30. | none (omit) |
| `usage.fading_features[].last_used_days_ago` | Same event, `Total Events` by day, last 90 days | Today minus the last day with a value above 0. | none (omit) |
| `usage.fading_features[].last_user_email_hash` | `$email` profile property of the last user of that event | Hash the email the engine's way. Leave null when no `$email` is set. | none (null) |
| `usage.feature_gate_hits_14d[].feature_key` | `Total Events` of the upgrade-prompt or gated-feature event (customer-defined; confirm in setup), broken down by its event property naming the feature (customer-defined) | Break the last 14 days down by the account key and the feature property. Map the value to the engine `feature_key`. | `feature_gate_events_unmapped` |
| `usage.feature_gate_hits_14d[].hits` | Same gate event, `Total Events` | Event count per feature in 14 days. | `feature_gate_events_unmapped` |
| `usage.feature_gate_hits_14d[].gated_to_tier` | `Total Events` of the gate event broken down by its tier property (customer-defined), if sent | Else look the feature up in the engine pricing catalog `gated_features`. Else null. | none (null) |
| `usage.integrations_connected` | `Total Events` of the "integration connected" event broken down by its integration-name property (customer-defined; confirm in setup), or a group profile property set with `group_set` | Distinct integration names connected and not later disconnected, within retention. | `integrations_unknown` |
| `usage.usage_by_business_unit[].business_unit` | Profile property for department or business unit (customer-defined; confirm in setup), as a second breakdown on `MAU` | Second breakdown on the MAU query. | none (omit) |
| `usage.usage_by_business_unit[].active_users_30d` | Same two-breakdown `MAU` query | Active users per business unit for this account. | none (omit) |
| `usage.pql_score` | Group profile property set with `group_set` holding a PQL score (customer-defined), only if the customer computes one on 0 to 100 | Read as is. Never derive a score here. | none (null) |
| `lifecycle.value_milestones_reached[].milestone_key` | Milestone events (customer-defined; confirm in setup) mapped to the engine's `DEFAULT_VALUE_MILESTONES` keys | Reached when the account has at least 1 such event. `five_active_users`: first week with 5 users who each had 3 or more `Session Start` events, only if the query can return per-user session counts; else leave it to the CRM checklist. | `value_milestones_unmapped` |
| `lifecycle.value_milestones_reached[].reached_at` | Same events, `Total Events` by day | Date of the first event for this account inside retention. If the account key was added to events after the milestone, the true date is earlier: say so in the explanation. | `value_milestones_unmapped` |
| `contract.seats_purchased` | Group profile property set with `group_set` holding licensed seats (customer-defined) | Last resort after `~~billing` and `~~crm`. | `seats_purchased_unknown` |
| `contract.consumed_units_run_rate_monthly` | Insights `Aggregate Property` (Sum) of the metered event's numeric property (customer-defined; confirm in setup) | Sum over the last 30 days, for consumption products only. Null for seat products. | none (null) |

## Vocabulary

| Mixpanel | Engine |
|---|---|
| `distinct_id` (Mixpanel's identifier for a user) | one user |
| Group key, for example `company_id` (customer-defined) | the account key |
| Group key value | `account.account_id` once matched |
| `Session Start`, `Session End` (virtual events computed at query time) | session boundaries |
| `Unique Users`, `DAU`, `WAU`, `MAU` | distinct active users over the stated window |
| `Total Events` | event count, used for feature use, gate hits and milestones |
| Event name (customer-defined) | `feature_key`, milestone or gate event, via the setup mapping |

| Engine `feature_key` or milestone | Mixpanel event |
|---|---|
| `dashboards`, `alerts`, `workflow_automation`, `api_access` (default core catalog) | customer-defined; confirm in setup |
| `first_production_workflow`, `integration_connected`, `first_report_shared` | customer-defined; confirm in setup |
| `five_active_users` | computed from `Session Start`, not an event |

## Limits and gotchas

- **Group Analytics is a paid add-on** on Enterprise or Growth plans. It is not needed to count users per account if every event carries an account id property, only for group profiles and counting companies.
- **Group key setup.** Creating a key needs project owner or admin rights. Data ingested just after the key is created "might not be associated to a group." Up to 300 group keys per event; extra ones are ignored.
- **Users in two accounts.** Uniques are counted per segment, so a user whose events carry two company ids counts in both accounts. That is right per account but wrong if you add accounts together.
- **Profiles use the latest value.** Profiles join to events at query time, so a profile-property rollup rewrites history when a user's account changes.
- **Sessions.** Computed at query time. Default timeout is 30 minutes, and a definition change "will apply historically." Sessions reset at midnight in the project time zone.
- **Date-range cap.** Reports "using All Events" are capped at 93 days. Keep each `All Events` query at 93 days or less. Reports are capped at 40 metric blocks.
- **Rate limit.** "A maximum of 600 MCP requests/hour per user." Free plans "can be subject to Query API access limits." For 40 accounts, run each metric once for the whole book with a breakdown by account (about 10 to 15 queries per refresh), never per account.
- **No cohort breakdowns.** `Run-Query` cannot filter or break down by cohort. Use the account property, not a cohort of account users.
- **Retention.** Event retention is 2 years for projects created on or after September 1, 2025, and 5 years for older projects (reduced to 2 years on a plan change or move to Free). Profiles last while the subscription is active. Enough for every window here.
- **Distinct counts.** Never sum daily `Unique Users` into a 30-day number; use `MAU`.
- **Time.** Day buckets and session resets follow the project time zone. Compute `days_since_last_login` in the same zone.

## Sources

- Claude connector listing: https://claude.com/marketplace/connectors/mixpanel
- Mixpanel MCP Server: https://docs.mixpanel.com/docs/mcp and https://docs.mixpanel.com/docs/features/mcp
- Group Analytics: https://docs.mixpanel.com/docs/data-structure/group-analytics
- Group Analytics implementation guide: https://docs.mixpanel.com/docs/data-structure/group-analytics/group-analytics-implementation
- Sessions: https://docs.mixpanel.com/docs/features/sessions
- Insights: https://docs.mixpanel.com/docs/reports/insights
- User profiles: https://docs.mixpanel.com/docs/data-structure/user-profiles
- Data retention (GDPR compliance page): https://docs.mixpanel.com/docs/privacy/gdpr-compliance
- Query API overview: https://docs.mixpanel.com/reference/query-api
- Third-party listing of the older tool names (used only to confirm `Get-Event-Details` and `Get-Property-Names` existed): https://policylayer.com/tools/mixpanel
