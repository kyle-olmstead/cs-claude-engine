---
name: cs-setup
description: >
  This skill should be used when the user asks to "set up the CS engine", "set up cs-claude-engine",
  "what's connected", "which tools does the engine see", "configure my stack", "run setup",
  "map my connectors", or on the first use of any other cs-claude-engine skill when no stack
  profile exists yet. It inventories the connectors in the user's Claude account, assigns each to
  a category the engine needs (CRM, support desk, conversation intelligence, survey, product
  analytics, warehouse, billing, enrichment, chat, email, calendar, documents), confirms the
  mapping with the user, saves it as the stack profile, and proves the install by scoring a
  sample account.
metadata:
  version: "1.3.0"
  playbook_id: "SETUP"
---

# CS Engine setup

Build the **stack profile**: the mapping from the engine's tool categories to the connectors
this user actually has. Every other skill in this plugin reads the profile first.

## Step 1: Inventory what is connected

List the tools available in this session. Look at the MCP/connector tool names and descriptions
(`mcp__<server>__<tool>` names; a `ListConnectors` tool when present). Do not ask the user what
they have connected before looking: the point of this skill is to see for them.

Classify every server into one category from `${CLAUDE_PLUGIN_ROOT}/CONNECTORS.md`:

| Category | Recognize by |
|---|---|
| `~~crm` | companies/accounts, contacts, deals/opportunities, properties, tasks (HubSpot, Salesforce, Pipedrive, Attio, Zoho CRM, Close) |
| `~~cs platform` | a CS system of record's health score, timeline, CTAs, success plans (Gainsight; read as a second opinion and as prior actions, never written without approval) |
| `~~support desk` | tickets, conversations, CSAT (Intercom, Pylon, Zoho Desk, HubSpot Service Hub, Jira Service Management) |
| `~~conversation intelligence` | calls, recordings, transcripts, meetings (Zoom, Fireflies, Fathom, tl;dv) |
| `~~survey tool` | NPS, CSAT surveys, responses (SurveyMonkey, Jotform, Tally, in-CRM survey objects) |
| `~~product analytics` | events, active users, cohorts, feature usage (Amplitude, Mixpanel, Pendo, PostHog, Fullstory) |
| `~~data warehouse` | SQL, tables, queries (BigQuery, Snowflake, Databricks, dbt, Postgres) |
| `~~billing` | subscriptions, invoices, MRR/ARR (Stripe, Chargebee, NetSuite, ChartMogul) |
| `~~enrichment` | people/company enrichment, job changes, tech stack (Clay, Apollo, ZoomInfo) |
| `~~chat` | channels, messages (Slack, Microsoft 365 Teams) |
| `~~email` | mail search, threads, drafts (Gmail, Microsoft 365 Outlook) |
| `~~calendar` | events, availability (Google Calendar, Microsoft 365, Calendly) |
| `~~documents` | files, docs, pages (Google Drive, Notion, Microsoft 365 SharePoint, Box, Dropbox, Confluence, Claude docs) |
| `~~tasks` | follow-ups per account (Asana, Linear, Jira) |

A server can fill more than one category (Zoom = conversation intelligence + calendar; HubSpot
= CRM + survey + support when those hubs are in use). If two servers compete for one category,
prefer the one with richer read tools and note the alternate.

## Step 2: Confirm the mapping

Show the user a short table: category → connector found → what it unlocks → what is missing.
Use `AskUserQuestion` only for genuine ambiguity (two CRMs; a warehouse *and* product analytics,
in which case ask which is the source of truth for usage). Otherwise present the mapping and ask for a
one-word confirmation.

For each **missing** category, say in one line what the engine loses without it, taken from the
"Minimum viable setup" section of `CONNECTORS.md`. Do not block setup on missing optional
categories, and name the path from `CONNECTORS.md` ("When your tool isn't here") when the user's tool has no connector. Block only if `~~crm` is missing; then explain that the CRM is the account spine
and suggest connecting one before continuing.

## Step 2b: Check each mapped tool

For every connected tool that has a map in `${CLAUDE_PLUGIN_ROOT}/skills/customer-360/references/tools/`,
run the read described under that map's "Setup check" and record the result in the stack
profile's status column using the wording the map gives (for example
`connected (mapped; confirmed)` or `connected (mapped; CSAT not on this plan)`). These maps were
written from vendor documentation; the check is what confirms them in this workspace. For chat,
email, calendar and documents tools, one list call proving the connector answers is enough. A
failed check is recorded, not fatal: the block falls back to the generic rule in
`field-sources.md` and its flags.

## Step 3: Capture the operator context

Ask, in one `AskUserQuestion` call, only what cannot be inferred:

1. The user's name as it appears in the CRM as an owner (so "my book" resolves); skip if the
   CRM connector exposes the current user.
2. Segment names used in the CRM and how they map to `enterprise / mid_market / smb / digital`;
   skip if the CRM uses those words.
3. Internal email domains (so transcript speakers can be split internal vs customer).
4. Whether the user wants the engine to *propose* CRM writes (default) or never touch the CRM
   at all (read-only mode).

## Step 4: Save the stack profile

Write the profile to `cs-engine/stack-profile.md` in the working folder (create the folder).
Use exactly this shape so other skills can parse it:

```markdown
# CS Engine stack profile
updated: <today>
operator: <name> · crm_owner_id: <id or unknown>
mode: propose-writes | read-only
internal_domains: [<domain>, ...]
segment_map: { "<crm value>": "enterprise", ... }

| category | connector | server | status |
|---|---|---|---|
| crm | HubSpot | mcp__HubSpot | connected |
| support desk | Intercom | mcp__Intercom | connected (mapped; confirmed) |
| conversation intelligence | none | none | missing (sentiment pillar reduced) |
...
```

If memory tools are available, also save a two-line summary under `/areas/cs-claude-engine-stack.md`
(category → connector only; no credentials, no customer data) so a new conversation can skip
re-discovery.

## Step 5: Prove the install

Run the bundled sample through the deterministic scorer and show the result:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/src/models/health_score.py ${CLAUDE_PLUGIN_ROOT}/examples/sample_customer_360.json
```

If Python is unavailable in this session, read `${CLAUDE_PLUGIN_ROOT}/examples/sample_customer_360.json`
and explain the health score from its `health.components` instead. Either way, present it the way
every reply reads (`${CLAUDE_PLUGIN_ROOT}/skills/customer-360/references/writing-standard.md`):
a headline, the account in two sentences, and what is driving the score in plain words. Then end
with:

- the three skills to try first: `customer-360` on a real account, `book-review` for the whole
  book, and whichever playbook matches their biggest worry (red account → `red-account-turnaround`;
  renewal coming → `renewal-defense`; expansion → `expansion-whitespace`; EBR → `ebr-generator`);
- one sentence on the approval model: the engine drafts and proposes; nothing reaches a customer
  or changes a CRM field without the user approving it.

## Rules

- Never ask the user for API keys or tokens. The connectors are already authorized in Claude.
- Never store customer data in the stack profile: it describes tools, not accounts.
- If a connector is present but its tools fail (auth expired, scope missing), record it as
  `connected (failing: <reason>)` and continue; do not abort setup.
- Keep the whole interaction under five exchanges. Setup is a door, not a destination.
