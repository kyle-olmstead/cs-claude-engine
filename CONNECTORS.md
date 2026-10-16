# Connectors

## How tool references work

Plugin files use `~~category` as a placeholder for whatever tool you have connected in that category. `~~crm` means HubSpot, Salesforce, Gainsight, or any other CRM with an MCP connector; `~~conversation intelligence` means Gong, Zoom, Chorus, Fireflies, or whatever records your customer calls.

The engine is tool-agnostic by design. Every skill describes its workflow in terms of categories, and two mechanisms bind those categories to your real tools:

1. **At install time** — the plugin customizer can rewrite `~~` placeholders to your product names so the skills read naturally in your environment.
2. **At run time** — the `cs-setup` skill inventories the connectors actually present in your Claude account, assigns each to a category, saves the mapping as your *stack profile*, and every other skill reads that profile before touching data. If a category has no connector, the skill says so and tells you exactly which Customer 360 fields will be missing and what that costs in confidence — it never silently invents them.

Nothing in this plugin requires a specific vendor. Nothing requires an API key beyond the connectors you already authorized in Claude.

## Connectors for this plugin

| Category | Placeholder | Required? | What the engine reads from it | What the engine may write (always with your approval) | Common options |
|---|---|---|---|---|---|
| CRM | `~~crm` | **Yes** | Accounts/companies, contracts & ARR, contacts & titles, activities, opportunities (renewal/expansion), custom properties (champion flags, business outcomes, tech stack) | Account properties (`cse_risk_tier`, `expansion_candidate`, `onboarding_risk_tier`), tasks, notes; never forecast or amount fields | HubSpot, Salesforce, Gainsight, Pipedrive, Attio, Zoho |
| Support desk | `~~support desk` | Recommended | Open tickets with priority and age, 30/90-day volume, CSAT, first-response time, reopened tickets | Nothing by default; optional ticket tag on onboarding blockers | Zendesk, Intercom, Freshdesk, Help Scout, Jira Service Management |
| Conversation intelligence | `~~conversation intelligence` | Recommended | Recent customer calls, transcripts, participants, dates | Nothing | Gong, Zoom, Chorus, Fireflies, Avoma, Microsoft Teams recordings |
| Survey / NPS | `~~survey tool` | Optional | NPS and CSAT responses with verbatims, per contact, last 180 days | Nothing | Delighted, Qualtrics, SurveyMonkey, Typeform, in-CRM survey objects |
| Product analytics | `~~product analytics` | Recommended | Daily/monthly active users per account, feature events, feature-gate hits, integrations connected, value milestones, seat activity | Nothing | Amplitude, Mixpanel, Pendo, Heap, PostHog, Segment |
| Data warehouse | `~~data warehouse` | Optional (replaces product analytics + billing when present) | The dbt marts in `sql/dbt_marts/`, or any table that exposes the Customer 360 fields | Nothing | Snowflake, BigQuery, Databricks, Postgres, Redshift |
| Billing | `~~billing` | Optional (CRM ARR used when absent) | ARR/MRR by account, seats purchased, term dates, payment status, past-due days | Nothing | Stripe, Chargebee, Maxio, NetSuite, Recurly |
| Enrichment | `~~enrichment` | Optional | Current employer and title for key contacts (champion-change detection), account tech stack | Nothing | Clay, Apollo, ZoomInfo, LinkedIn Sales Navigator, Clearbit |
| Chat | `~~chat` | Optional | Internal channel context for an account (escalations, deal desk) | Alerts to a channel (P0/P1 only, with approval) | Slack, Microsoft Teams, Discord |
| Email | `~~email` | Optional | Recent threads with account contacts (engagement recency, sentiment) | Drafts only — never sends | Gmail, Outlook |
| Calendar | `~~calendar` | Optional | Upcoming EBRs/QBRs, last customer meeting | Proposed holds for value reviews and EBRs (with approval) | Google Calendar, Outlook Calendar |
| Documents | `~~documents` | Optional | Prior EBR decks, account plans, kickoff notes, business-case docs | New artifacts (RCA, save plan, EBR script) as documents | Google Drive, SharePoint, Notion, Confluence, Claude docs |

## Minimum viable setup

`~~crm` alone is enough to run every skill in a reduced-confidence mode: health is scored on relationship, commercial, and whatever engagement/support data the CRM carries, and each action's `data_quality_flags[]` lists what was unavailable. Adding `~~product analytics` (or `~~data warehouse`) and `~~support desk` brings the health score to full fidelity. Adding `~~conversation intelligence` and `~~survey tool` unlocks the sentiment pillar and transcript-driven RCA.

## How fields map to connectors

The authoritative field-by-field source map — which Customer 360 field comes from which category, how to compute it when the connector only exposes raw records, and what to do when it is missing — is in `skills/customer-360/references/field-sources.md`.
