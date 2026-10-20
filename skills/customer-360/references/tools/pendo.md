# Pendo

**Category:** `~~product analytics` · **Claude connector:** Pendo · **Status:** mapped from vendor documentation on 2026-10-20; not yet run against a live account. Confirm in `cs-setup`.

Pendo fills the `usage` block (active visitors, stickiness, Core Event depth, fading features, feature-gate hits) and the product value milestones in `lifecycle`. Accounts are native, so rollup needs no add-on. It feeds the adoption component (DAU/MAU, feature depth, seat utilization), the last-login input to engagement, the low-utilization override, and the PB-RET-02, PB-ADP-01, PB-ADP-02, PB-EXP-01 and PB-EXP-02 triggers.

## What the connector exposes

Claude's directory lists 11 Pendo tools. Pendo's current tool article documents a larger, renamed set. Five directory names appear in Pendo's article. The other six appear in Gong's listing of the Pendo server but not in Pendo's article, so their behavior is (unconfirmed); Pendo's documented counterpart is given. In `cs-setup`, use whichever name the session exposes.

- `list_all_applications` (unconfirmed). Documented counterpart `listAllApplications`: "Retrieve a list of subscriptions and applications you have access to." Used to pick the subscription and app ids.
- `accountQuery` (unconfirmed). Documented counterparts `listAccounts` ("List or search accounts. You can list accounts matching an inline or saved segment.") and `appUsage` ("Retrieve app-level usage metrics, broken down by visitor or account.").
- `visitorQuery` (unconfirmed). Documented counterpart `listVisitors`: "List visitors matching an inline or saved segment."
- `activityQuery` (unconfirmed). Documented counterparts `entityUsage` (usage for one Page, Feature or Track Event, grouped by visitor or account), `aggregateEntityUsage` (ranks all Pages, Features or Track Events of one type by usage), and `appUsageTimeSeries` / `entityUsageTimeSeries` (usage bucketed by day, week or month).
- `pes` (unconfirmed). Documented counterpart `productEngagementScore`: reports PES adoption, stickiness and growth, with a 180-day maximum range.
- `guideMetrics` (unconfirmed). Guide engagement; not used by this map.
- `accountMetadataSchema`: "View the available metadata fields for accounts, such as ARR, industry, renewal date, or product tier." Used in setup to find the CRM id field.
- `visitorMetadataSchema`: "View the available metadata fields for visitors, such as job title, CRM fields, region, or role." Used in setup to find email and department fields.
- `searchEntities`: "Find Pendo items by name or conceptual meaning, including Pages, Features, Track Events, accounts, and saved clips." Used in setup to find feature, gate and milestone tags.
- `segmentList`: "List all publicly shared segments with their names and IDs."
- `sessionReplayList`: not used.
- A subscription admin must turn on "Pendo MCP server (read-only tools)" in Settings > Subscription settings > AI access. The server inherits the user's Pendo permissions. Each region (US, US1, EU, Japan, Australia) is a separate connection, and data cannot be read across regions.
- The connector has no seats or contracts unless account metadata holds them. `contract.seats_purchased` comes from `~~billing` or `~~crm` first.

## Matching records to the CRM account

Pendo has visitors and accounts as first-class records. The install script passes a `visitorId` "and optionally an `accountId`." If the install never passes an Account ID, Pendo has no accounts to match.

1. **Pendo Account ID equals the CRM id.** Check a few known accounts. If Pendo's HubSpot or Salesforce integration is on, reuse its join key: the HubSpot integration matches "The Pendo Account ID" or "Any field in your account metadata that matches with a HubSpot **Company** property," and values "must match one-to-one."
2. **Account metadata field holding the CRM id** (customer-defined; find it with `accountMetadataSchema` and confirm in setup).
3. **Visitor email domain.** Visitor IDs are "typically an email address or a unique number." Use only when the Visitor ID or a visitor email field (customer-defined) holds an email, and the CRM company has one unique domain. Set `usage_matched_by_domain`. Never match on free-mail domains or on a domain shared by a parent and its subsidiaries.
4. **No match.** Do not pick the nearest name from `searchEntities`. Set `usage_account_unmatched` and `usage_unavailable`, leave the usage block null (the field-sources rule for an absent category), and read the Pendo fields pushed to the CRM if the integration runs (see Limits).

IDs are case-sensitive. A visitor "can also have multiple Account IDs." Count activity by the Account ID on the events, not by visitor membership. A subscription can hold several apps; decide in setup which apps count, and dedupe visitors by Visitor ID across apps.

## Setup check

After `list_all_applications` returns the subscription and app ids, run one `accountQuery` (or `appUsage`) call: app usage broken down by account, last 7 days, limit 5.

Pass: rows come back with Account IDs, and at least one matches a CRM account in the user's book. In the same step, confirm whether Core Events are configured, and name the gate and milestone tags.

Record one of these in the status column:

- `connected (mapped; accounts via Pendo Account ID)`
- `connected (mapped; accounts via account metadata <field>)`
- `connected (mapped; Core Events not configured, default feature catalog)`
- `connected (no Account IDs in install; usage_unavailable)`
- `connected (failing: <reason>)`, for example read-only tools not enabled.

## Field map

| Customer 360 field | Source in Pendo | How to derive | If unavailable |
|---|---|---|---|
| `usage.mau_30d` | `appUsage` (or `accountQuery`) broken down by visitor, segment = this `Account ID`, last 30 days | Count visitors with at least 1 event. Pendo: "A visitor or account with any event recorded by Pendo is considered active." If the row count equals the tool's row cap, the list is truncated: do not report it. | `usage_unavailable` (null); `usage_row_cap_hit` when truncated |
| `usage.active_users_30d` | Same call as `mau_30d` | Same as MAU. If visitor metadata marks licensed users (customer-defined; confirm in setup), filter on it. | `usage_unavailable` (null) |
| `usage.dau_mau_30d` | `appUsageTimeSeries` (or `activityQuery`), daily buckets, this `Account ID`, last 30 days | Mean of daily active visitors divided by `mau_30d`. Business-day mean for weekday products. If `mau_30d` is 0, set 0. PES `Stickiness` (DAU/MAU) on a one-account segment is a cross-check only. | `usage_unavailable` (null) |
| `usage.wau_mau_30d` | `appUsage` by visitor, this `Account ID`, last 7 days | 7-day active visitors divided by `mau_30d`. | none (omit) |
| `usage.days_since_last_login` | Account `Last Visit` (as listed in Pendo's HubSpot push fields) or the last active day from `appUsageTimeSeries` | Today minus the last visit date. If neither is in the last 367 days, set the window length and flag it as a lower bound. | `last_login_beyond_window` |
| `usage.feature_depth_30d` | Core Events (the tagged Features or Track Events configured for PES), `entityUsage` per Core Event grouped by account, last 30 days | Core Events with at least 1 event for this account divided by total Core Events. If Core Events are not configured, map the engine's `DEFAULT_FEATURE_CATALOG` (`is_core: true`) to tagged Features in setup. | `feature_taxonomy_default` |
| `usage.feature_breadth_30d` | `aggregateEntityUsage` over tagged Features, segment = this `Account ID`, last 30 days; total from `listCountables` | Distinct tagged Features used divided by all tagged Features. | `feature_taxonomy_default` |
| `usage.core_features_used` | Output of the depth calls (`entityUsage` per Core Event) | Core Events (as engine `feature_key` values) with at least 1 event. | none |
| `usage.core_features_unused` | Output of the depth calls (`entityUsage` per Core Event) | Core Events with 0 events. | none |
| `usage.power_user_ratio` | `entityUsage` per Core Event grouped by visitor, this `Account ID`, last 30 days | Visitors with 3 or more distinct Core Events divided by MAU. | none (omit) |
| `usage.seat_utilization` | `active_users_30d` from above; seats from `~~billing` or `~~crm` | `active_users_30d / contract.seats_purchased`, not capped. If seats are 0 or unknown, set null. | `seats_purchased_unknown` |
| `usage.seat_utilization_90d_ago` | `appUsage` by visitor, this `Account ID`, the 30 days ending 90 days ago | Active visitors in days 91 to 120 ago divided by seats then (current seats if billing has no history). | `utilization_history_missing` |
| `usage.utilization_drift_90d` | Computed from the two `appUsage` results above | `seat_utilization` minus `seat_utilization_90d_ago`. Set 0 if the install started passing Account IDs less than 120 days ago. | `utilization_history_missing` |
| `usage.fading_features[].feature_key` | `aggregateEntityUsage` over tagged Features, this `Account ID`, days 31 to 90 ago and last 30 days | Features with events in days 31 to 90 and none in the last 30. | none (omit) |
| `usage.fading_features[].last_used_days_ago` | `entityUsageTimeSeries`, daily, that Feature, this `Account ID` | Today minus the last day with events. | none (omit) |
| `usage.fading_features[].last_user_email_hash` | `entityUsage` grouped by visitor; the Visitor ID or visitor email field (customer-defined) | Hash the email of the most recent visitor. Null when no email is available. | none (null) |
| `usage.feature_gate_hits_14d[].feature_key` | A tagged Feature on the upgrade prompt, or a Track Event sent with `pendo.track(name, metadata?)` (customer-defined; confirm in setup) | One gate Feature or Track Event per gated feature, or one Track Event with a metadata field naming the feature (customer-defined). Map to the engine `feature_key`. | `feature_gate_events_unmapped` |
| `usage.feature_gate_hits_14d[].hits` | `entityUsage` on the gate Feature or Track Event, grouped by account, last 14 days | Event count per feature for this account. | `feature_gate_events_unmapped` |
| `usage.feature_gate_hits_14d[].gated_to_tier` | Track Event metadata (`pendo.track(name, metadata?)`) field naming the tier (customer-defined), if sent | Else look the feature up in the engine pricing catalog `gated_features`. Else null. | none (null) |
| `usage.integrations_connected` | Account metadata field listing integrations (see `accountMetadataSchema`), or an "integration connected" Track Event (customer-defined; confirm in setup) | Distinct integration names connected and not later disconnected. | `integrations_unknown` |
| `usage.usage_by_business_unit[].business_unit` | Visitor metadata field for department (see `visitorMetadataSchema`; customer-defined; Pendo's docs give department as an example) | Group the MAU visitor list by this field. | none (omit) |
| `usage.usage_by_business_unit[].active_users_30d` | Same `appUsage` visitor list | Active visitors per business unit for this account. | none (omit) |
| `usage.pql_score` | Account metadata field holding a PQL score (see `accountMetadataSchema`; customer-defined), only if the customer computes one on 0 to 100 | Read as is. PES is not a PQL score: never copy it here. | none (null) |
| `lifecycle.value_milestones_reached[].milestone_key` | Tagged Features or Track Events for each milestone (customer-defined; confirm in setup) mapped to the engine's `DEFAULT_VALUE_MILESTONES` keys | Reached when the account has at least 1 such event. `five_active_users` needs sessions per visitor, which the docs read do not expose: take it from the CRM onboarding checklist. | `value_milestones_unmapped` |
| `lifecycle.value_milestones_reached[].reached_at` | `entityUsageTimeSeries`, daily, that Feature or Track Event, this `Account ID` | First day with events, searching back in 367-day steps inside retention. Track Events are not captured retroactively, so the date can be later than the truth: say so in the explanation. | `value_milestones_unmapped` |
| `contract.seats_purchased` | Account metadata field holding licensed seats (customer-defined; see `accountMetadataSchema`) | Last resort after `~~billing` and `~~crm`. | `seats_purchased_unknown` |
| `contract.consumed_units_run_rate_monthly` | `entityUsage` sum of a numeric event property on the metered Track Event (customer-defined; confirm in setup) | Sum over the last 30 days, for consumption products only. Null for seat products. | none (null) |

## Vocabulary

| Pendo | Engine |
|---|---|
| Visitor (Visitor ID) | one user |
| Account (Account ID) | the account key; `account.account_id` once matched |
| Page, Feature (tag rules over raw events) | a feature, via the setup mapping |
| Track Event (`trackType`, sent by code) | a feature, gate or milestone event, via the setup mapping |
| Core Events | the core feature list for `feature_depth_30d` |
| `Time on App` (whole minutes with activity) | not used for active users |
| `Days Active` | not used directly; a cross-check for activity |
| PES (`Adoption`, `Stickiness`, `Growth`, 0 to 100) | not mapped to any field; a cross-check only |

| Engine `feature_key` or milestone | Pendo item |
|---|---|
| `dashboards`, `alerts`, `workflow_automation`, `api_access` (default core catalog) | customer-defined Feature or Track Event; confirm in setup |
| `first_production_workflow`, `integration_connected`, `first_report_shared` | customer-defined Feature or Track Event; confirm in setup |
| `five_active_users` | not available from Pendo; CRM onboarding checklist |

## Limits and gotchas

- **Tool renames.** The directory names and Pendo's current names differ for six tools. Probe once in setup and record which set the session exposes.
- **Date ranges.** `entityUsage`, `aggregateEntityUsage`, `appUsage` and the time-series tools allow up to 367 days. `productEngagementScore` allows 180 days. `visitorActivity` allows 31 days.
- **Row caps.** Pendo documents 10 rows by default and up to 200 for some breakdown tools, and a third-party listing gives the same limits for `appUsage` (unconfirmed by Pendo). An account with more active visitors than the cap gives a truncated count. Set `usage_row_cap_hit` and leave `mau_30d` null rather than report a low number.
- **Track Events do not count as activity by default.** "Track Events aren't considered when we calculate a visitor's time spent in your app," and PES leaves them out of stickiness and growth unless an admin turns on the setting. The setting is not retroactive. A product used mostly through server-side Track Events will look inactive.
- **Tags are retroactive; Track Events are not.** Page and Feature data "are collected retroactively," so a gate or milestone tagged today has history. Track Events "aren't captured retroactively."
- **Processing delay.** Data updates hourly, usually within 15 minutes after the hour. Tag edits reprocess history, and tagged data shows in segments after the most recent 90 days are processed.
- **PES is a cross-check, not a source.** PES `Adoption` uses Core Events adopted per active visitor or account, and `Stickiness` uses averages of daily and monthly actives. Both are close to, but not defined the same as, the engine's `feature_depth_30d` and `dau_mau_30d`.
- **CRM sync fallback.** Pendo's HubSpot integration pushes account fields such as `First Visit`, `Last Visit`, `Days Active`, `Time on App` and `# of Total Visitors` daily between midnight and 1am UTC. The Salesforce integration syncs nightly. If MCP rollup fails, setup can point the CRM field map at those properties.
- **Retention.** Raw events are kept 84 months by default; the customer can shorten this to 1 to 84 months. UI access is limited to 12 months on Pendo Free and 24 months on Pendo Starter (whether MCP follows the UI limit is unconfirmed). Session replays are kept 30 or 90 days.
- **Rate limits.** Not published. For 40 accounts, book-level calls (usage broken down by account) cover activity and last visit; per-account calls are needed for visitor counts and feature depth, about 6 to 10 per account. Spread them across the run.

## Sources

- Claude connector listing: https://claude.com/marketplace/connectors/pendo
- Pendo MCP tools for AI agents: https://support.pendo.io/hc/en-us/articles/42476316360731-Pendo-MCP-tools-for-AI-agents
- Pendo MCP setup (linked from the Claude listing): https://support.pendo.io/hc/en-us/articles/41102236924955
- Pendo MCP server overview: https://support.pendo.io/hc/en-us/articles/51020341547419/
- Product Engagement Score (PES): https://support.pendo.io/hc/en-us/articles/360054782691
- Choose IDs and metadata: https://support.pendo.io/hc/en-us/articles/21326198721563
- Events overview: https://support.pendo.io/hc/en-us/articles/23335876011803
- Track Events: https://support.pendo.io/hc/en-us/articles/360032294151
- Web SDK Track Events: https://web-sdk.pendo.io/events/track-events
- Time on page and app calculations: https://support.pendo.io/hc/en-us/articles/360032203171
- Pendo data processing and visibility: https://support.pendo.io/hc/en-us/articles/10508118459035
- Subscription data retention: https://support.pendo.io/hc/en-us/articles/360051268732
- Two-way HubSpot integration: https://support.pendo.io/hc/en-us/articles/19464314721435
- Troubleshoot the Salesforce integration: https://support.pendo.io/hc/en-us/articles/360037654352
- Gong's listing of the Pendo MCP server (used only to confirm the older tool names existed): https://collective.gong.io/integrations/pendo-mcp-server.md
- Scalekit's Pendo connector page (third-party; source of the `appUsage` row limits): https://www.scalekit.com/connectors/pendomcp
