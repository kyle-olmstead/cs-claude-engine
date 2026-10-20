# Connectors

> **In plain English.** The engine doesn't care which brands you use. It thinks in roles ("the CRM," "the support desk," "the call recorder") and maps whatever you have connected in Claude onto those roles. Only the CRM is required. This page says which tools you can connect today, which ones the repo has been built against, and what to do when your tool isn't on the list.

## How tool references work

Plugin files use `~~category` as a placeholder for whatever tool you have connected in that category. `~~crm` means HubSpot, Salesforce, or any other CRM with a Claude connector; `~~conversation intelligence` means Zoom, Fireflies, or whatever records your customer calls.

Two mechanisms bind categories to real tools:

1. **At install time**, the plugin customizer can rewrite `~~` placeholders to your product names so the skills read naturally in your environment.
2. **At run time**, the `cs-setup` skill inventories the connectors actually present in your Claude account (including custom connectors your admin added), assigns each to a category, saves the mapping as your *stack profile*, and every other skill reads that profile before touching data. If a category has no connector, the skill says so, sets the block's fields to `null`, and the health score leaves that component out rather than scoring it as 0 or 100 (`health.coverage` records how much of the score had inputs; below 60 percent the band is `insufficient_data`).

Nothing in this plugin requires a specific vendor. Nothing requires an API key beyond the connectors you already authorized in Claude.

## What "works with" means here

The engine can only read a tool that has a connector in your Claude workspace. So a tool is plug-and-play when all three are true: a Claude connector for it exists, your org has it enabled, and the connector exposes the records the field map needs. The tiers below are honest about which of those are known.

- **Built against:** this repository has an explicit field map or adapter for it. HubSpot, Salesforce, Zoom, the Gong transcript parser and Clay are mapped in `skills/customer-360/references/field-sources.md` and `src/tools/`. The tools linked in the matrix have their own map in `skills/customer-360/references/tools/`: the connector tools to call, how records match the CRM account, each vendor field, the vocabulary, and a setup check.
- **Mapped from documentation:** every linked map was written on 2026-10-20 from the vendor's documentation and the connector's tool list, and has not yet been run against a live account. `cs-setup` runs each map's check on first use and records the result; treat a field the check could not confirm as unknown, not as zero.
- **Connector available:** it appeared in Claude's connector directory when this page was checked. The mapping is generic; expect to confirm a field or two during `cs-setup`.
- **No connector found:** not plug-and-play today. See "When your tool isn't here."

*Directory checked on 2026-10-17 from one organization's view; the tools with their own map were re-checked on 2026-10-20. The directory changes often, orgs can add custom connectors, and availability can differ by plan or region. Run `cs-setup` for the truth about your workspace.*

## Connector matrix

| Category | Placeholder | Required? | What the engine reads | What it may write (always with your approval) | Built against | Connector available | No connector found |
|---|---|---|---|---|---|---|---|
| CRM | `~~crm` | **Yes** | accounts, contracts and ARR, contacts and titles, activities, opportunities, custom properties | account properties (`cse_risk_tier`, `expansion_candidate`, `onboarding_risk_tier`, `cse_last_playbook`), tasks, notes; never forecast or amount fields | HubSpot, Salesforce | Pipedrive, Attio, Zoho CRM, Close, Nutshell, Clarify | Microsoft Dynamics |
| CS platform | `~~cs platform` | No | the platform's health score (as `health.mart_score`, for comparison), timeline, CTAs and success plans (as `actions_last_30d`), relationships | nothing by default | [Gainsight (CS)](skills/customer-360/references/tools/gainsight.md) | Gainsight (Staircase AI) | Totango, ChurnZero, Vitally, Planhat, Custify, ClientSuccess, Catalyst, SmartKarrot, UserIQ, Natero, Strikedeck, Akkio, Hook, Churn360, Velaris, CustomerGauge, Preact |
| Support desk | `~~support desk` | Recommended | open tickets with priority and age, 30/90-day volume, CSAT, first-response time | nothing by default | [Intercom](skills/customer-360/references/tools/intercom.md), [Pylon](skills/customer-360/references/tools/pylon.md), [Zoho Desk](skills/customer-360/references/tools/zoho-desk.md), [HubSpot Service Hub](skills/customer-360/references/tools/hubspot-service-hub.md) (through the HubSpot connector) | Richpanel, Unthread; Jira Service Management through Atlassian | Zendesk, Freshdesk, Help Scout, Front |
| Conversation intelligence | `~~conversation intelligence` | Recommended | recent customer calls, transcripts, participants | nothing | Zoom (connector and transcript parser), [Fireflies](skills/customer-360/references/tools/fireflies.md), [Fathom](skills/customer-360/references/tools/fathom.md), Gong (transcript parser for exported files; no connector) | tl;dv, Vibe AI, Vylo; Attio call recordings; ZoomInfo's conversation-intelligence tool returns summaries, not transcripts | Gong (connector), Chorus, Avoma |
| Survey / NPS | `~~survey tool` | Optional | NPS and CSAT responses with verbatims, last 180 days | nothing | | SurveyMonkey, Jotform, Tally; in-CRM survey objects | Qualtrics, Delighted, Typeform |
| Product analytics | `~~product analytics` | Recommended | active users per account, feature events, feature-gate hits, value milestones | nothing | [Amplitude](skills/customer-360/references/tools/amplitude.md), [Mixpanel](skills/customer-360/references/tools/mixpanel.md), [Pendo](skills/customer-360/references/tools/pendo.md), [PostHog](skills/customer-360/references/tools/posthog.md) | Fullstory | Heap, Segment |
| Data warehouse | `~~data warehouse` | Optional (replaces analytics and billing when present) | the dbt marts in `dbt/models/marts/`, or any table exposing the Customer 360 fields | nothing | the dbt project, built on DuckDB in CI and checked against the Snowflake, BigQuery and Databricks adapters (`scripts/check_warehouses.py`); [BigQuery](skills/customer-360/references/tools/bigquery.md) (SQL), [Snowflake](skills/customer-360/references/tools/snowflake.md) (through a Cortex Agent over semantic views), [Databricks](skills/customer-360/references/tools/databricks.md) (through Genie) | dbt, Blaze SQL, Neon Postgres | Redshift |
| Billing | `~~billing` | Optional (CRM ARR used when absent) | ARR/MRR, seats, term dates, payment status | nothing | [Stripe](skills/customer-360/references/tools/stripe.md), [Chargebee](skills/customer-360/references/tools/chargebee.md) | NetSuite, ChartMogul, Tabs | Maxio, Recurly |
| Enrichment | `~~enrichment` | Optional | current employer and title for key contacts (champion-change detection) | nothing | Clay (push and callback loop in `src/tools/`), [Apollo.io](skills/customer-360/references/tools/apollo.md), [ZoomInfo](skills/customer-360/references/tools/zoominfo.md) | Unify, Vibe Prospecting, Leadfeeder | Clearbit, LinkedIn Sales Navigator |
| Chat | `~~chat` | Optional | internal channel context for an account | P0/P1 alerts to an internal channel, with approval | [Slack](skills/customer-360/references/tools/slack.md), [Microsoft 365](skills/customer-360/references/tools/microsoft-365.md) (Teams: read only) | | Discord |
| Email | `~~email` | Optional | recent threads with account contacts | drafts only; never sends | [Gmail](skills/customer-360/references/tools/gmail.md), [Microsoft 365](skills/customer-360/references/tools/microsoft-365.md) (Outlook) | | |
| Calendar | `~~calendar` | Optional | upcoming EBRs, last customer meeting | proposed holds, with approval | [Google Calendar](skills/customer-360/references/tools/google-calendar.md), [Microsoft 365](skills/customer-360/references/tools/microsoft-365.md) | Calendly | |
| Documents | `~~documents` | Optional | prior EBR decks, account plans, kickoff notes | new artifacts as documents | [Google Drive](skills/customer-360/references/tools/google-drive.md), [Notion](skills/customer-360/references/tools/notion.md), [Microsoft 365](skills/customer-360/references/tools/microsoft-365.md) (SharePoint, OneDrive) | Box, Dropbox, Atlassian (Confluence), Glean, Claude docs | |
| Tasks | `~~tasks` | Optional | open follow-ups per account | tasks, with approval | | Asana, Linear, Atlassian (Jira) | |

## Minimum viable setup

`~~crm` alone runs every skill in reduced-confidence mode: health is scored on relationship, commercial, and whatever engagement data the CRM carries; the unobserved components are left out; `health.coverage` is about 0.45 and the band is `insufficient_data`, which the digest and the playbooks treat as "unknown, not a signal." Adding `~~product analytics` (or `~~data warehouse`) and `~~support desk` brings the score to full fidelity. Adding `~~conversation intelligence` and `~~survey tool` unlocks the sentiment pillar and transcript-driven root-cause analysis.

## If you already have a CS platform

A CS platform (Gainsight, ChurnZero, Totango and the like) is a system of record with its own health score, CTAs, and playbooks. The engine does not replace it. Where the platform is connectable, the engine reads its score as an input and a second opinion (`health.mart_score`; the drift between the two is reported, never averaged), reads its timeline and CTAs as prior actions so cooldowns respect work already in flight, and writes nothing back without approval. Where it is not connectable, most deployments already sync the platform's score and CTAs into Salesforce or HubSpot fields; point the CRM field map at those and the engine reads them through `~~crm`.

Gainsight is the one CS platform with Claude connectors today. The mapping from Gainsight objects to the Customer 360 is [the Gainsight map](skills/customer-360/references/tools/gainsight.md). It was written from Gainsight's documentation and has not yet been run against a live instance; `cs-setup` checks it, and object and field labels vary by instance, so confirm them with your Gainsight admin.

## When your tool isn't here

Three paths, in order of effort:

1. **The CRM sync path.** Most tools without a connector already push their key numbers into the CRM (health scores, ticket counts, NPS, usage summaries land on company or contact properties). Tell `cs-setup` which properties those are and the engine reads them through `~~crm`. Zero engineering.
2. **The warehouse path.** Export the tool's data to a warehouse the engine can read (BigQuery, Snowflake, Databricks, Postgres) and build the staging models in `dbt/models/staging/`. The marts do the rest. A day of CS Ops or analytics engineering per source.
3. **The custom connector path.** Your admin adds a custom MCP connector for the tool's API to your Claude workspace. `cs-setup` detects custom connectors the same way it detects directory ones. Engineering work on your side, but the engine needs no change.

Say which path you chose in the stack profile so the next person knows where a block comes from.

## How fields map to connectors

The authoritative field-by-field source map, including what to do when a block is missing, is `skills/customer-360/references/field-sources.md`.
