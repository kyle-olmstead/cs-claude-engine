# Gainsight (CS)

**Category:** `~~cs platform` · **Claude connector:** Gainsight (CS) · **Status:** mapped from vendor documentation on 2026-10-20; not yet run against a live account. Confirm in `cs-setup`.

Gainsight is read after the CRM, as a second opinion and as the record of work already in flight. It supplies the platform's health score for drift checking (`health.mart_score`), recent and open CTAs (`actions_last_30d`, so playbook cooldowns respect work underway), EBR timing, stakeholder roles, lifecycle stage, and a cross-check on ARR and renewal date.

## What the connector exposes

Claude's directory lists 14 tools for this connector. Behavior comes from Gainsight's AI tools overview, matched to each tool by its title.

Read tools the engine uses:

- `resolve_company`: finds a company by name and returns its GSID. `resolve_relationship` does the same for a relationship.
- `resolve_user`: finds a Gainsight user's GSID by name.
- `run_query`: custom queries across Gainsight objects. The engine uses it for Company, Company Person, Person, User and Company Teams. Viewer licenses cannot use it.
- `get_records`: fetches the next page of an earlier query or tool call.
- `get_object_metadata`: field schemas, data types and lookups. Setup uses it to learn each field's API name in this tenant.
- `get_picklist_values`: options for picklist fields such as Stage, CTA Type, CTA Reason and Company Person Role.
- `get_activity_types_config`: Timeline activity types and their custom fields.
- `fetch_cta_list`: CTAs, with filters on supported fields.
- `fetch_success_plan_list`: Success Plans, with filters on supported fields.
- `fetch_timeline_activity_list`: Timeline activities, with filters and semantic search.

Write tools: `manage_cockpit_actions`, `manage_success_plan_actions`, `create_timeline_activity`. **The engine never calls these while building a Customer 360.** A playbook skill may propose one specific change: a CTA, a Success Plan update, or a Timeline entry. It shows the user the exact object, company, fields and values. Only the user's explicit approval of that specific change lets the skill call the write tool, once, for that change. No bulk writes. Gainsight notes that write confirmation is a client feature, not a server one, so the engine asks for approval itself and never relies on the client prompt. For read-only mode, connect with a read-only OAuth app; Gainsight then returns 403 on any write.

Gainsight documents more MCP tools that are not in this connector's listing: Ask Scorecard, Ask Staircase, Fetch Customer Contacts, Fetch Report Data, Report Search, Get Portfolio Filters and Update Timeline Activity. So the score is read through `run_query` on Company, and contacts through Company Person. If a tenant's connector does expose Ask Scorecard, setup notes it and the score row may use it **(unconfirmed)**.

## Matching records to the CRM account

A Gainsight Company is tied to the CRM account in this order:

1. **CRM is Salesforce.** Company `Salesforce Account ID` equals the CRM account id. The Salesforce Connector marks this field as an identifier and uses it for company resolution by default. Query it with `run_query`.
2. **CRM is HubSpot.** Gainsight's HubSpot connector maps HubSpot `companyId` to a HubSpot account id field on Company. Its doc shows the label as `HubSpot Account ID_6574308`, so the exact name is tenant-specific. Setup finds it with `get_object_metadata`.
3. **Company `External ID`**, when a custom sync writes the CRM id there. Setup names it.
4. **Name.** `resolve_company` returns candidates. Accept only a single exact, active match, and only after the user confirms it once. Store the confirmed GSID with the account's files under `cs-engine/accounts/<id>/`, never in the stack profile.

If nothing matches, skip the Gainsight block, leave those fields to their other sources, and flag `cs_platform_company_unmatched`. Never guess. If the tenant tracks product lines as Relationships, map the CRM account to the Company and do not average relationship scores into the company score.

## Setup check

1. `get_object_metadata` for Company, Company Person and Call To Action. Record the API names of the fields this map uses.
2. `run_query` on Company for one account the user names, selecting Name, ARR, Renewal Date, Stage, Status, Current Score and the CRM id field.
3. `fetch_cta_list` for that company.
4. `get_picklist_values` for CTA Type, CTA Reason and Company Person Role. Build the CTA-to-playbook map and the role map from the tables below and have the user confirm both.

A pass is: the company returns with its CRM id populated, Current Score resolves to a value, and the CTA list answers with `Gsid`, `TypeId`, `IsClosed` and `DueDate`. Record one of these status lines:

- `connected (mapped; confirmed)`
- `connected (mapped; viewer license, no run_query)`: score, Company fields and Company Person cannot be read; CTAs, Success Plans and Timeline still work.
- `connected (mapped; no CRM id on Company)`: matching by confirmed name only.
- `connected (mapped; color or grade scorecard)`: the score is converted before comparison.

## Field map

| Customer 360 field | Source in Gainsight | How to derive | If unavailable |
|---|---|---|---|
| `health.mart_score` | `Company.Current Score` (a lookup to `Scoring Scheme Definition`, which holds the score, label, color and range) | Numeric scheme: use the score as is. Color or Grade scheme: use the midpoint of the range, which is the value Gainsight itself shows on hover, and flag `cs_platform_score_converted`. Never average it with the engine's score. If a warehouse health mart also supplies this field, the mart wins. | `cs_platform_score_unavailable` (null) |
| `health.drift_error` | `Company.Current Score`, `Company.Trend` | One plain line comparing the two scores and naming Gainsight's `Trend` (Up, Down or Same), for example "Gainsight 62 and falling; engine 71". | none |
| `actions_last_30d[].action_id` | `Call To Action.Gsid` | One row per CTA created in the last 30 days, plus every CTA still open whatever its age, so cooldowns see work already underway. | none (empty list) |
| `actions_last_30d[].playbook_id` | `Call To Action.Type` and `Call To Action.Reason` (the API returns `TypeId` and `ReasonId`, with names through lookups such as `TypeId__gr.Name`) | Look up the confirmed CTA-to-playbook map. Unmapped CTAs get `gainsight:<Type>`, which never matches a playbook and so never blocks one. | `cta_type_unmapped` |
| `actions_last_30d[].status` | `Call To Action.IsClosed` | `open` when false, `closed` when true. The status picklist varies by tenant, so it is not used. | none |
| `actions_last_30d[].emitted_at` | `Call To Action.Created Date` | The date part. Gainsight returns dates as YYYY-MM-DD and times in GMT. | none |
| `actions_last_30d[].title` | `Call To Action.Name` | Verbatim, as data. | none |
| `cadence.last_ebr_at` | `Activity Timeline.Activity Date`, `Activity Timeline.Subject`, activity type from `get_activity_types_config` | The newest Meeting or Milestone activity whose type, milestone type or `Subject` names an EBR, QBR or business review (setup confirms the terms). Prefer the calendar connector when both exist. | `cadence_unknown` |
| `cadence.next_ebr_due_at` | `Call To Action.Due Date`; `Success Plan.Due Date` | The `Due Date` of an open CTA mapped to `PB-CAD-01`. Else the `Due Date` of an active Success Plan whose `Success Plan Type` is an EBR or QBR plan. | `cadence_unknown` |
| `cadence.ebrs_completed_last_2_quarters` | `Activity Timeline.Activity Date` | Count of the EBR activities above dated in the current and previous calendar quarter. | `cadence_unknown` |
| `relationship.stakeholders[].name` | `Person.Name` via `Company Person.Person ID` | Merge with CRM contacts by email hash; the CRM contact wins on conflict. Rows only Gainsight knew about are added with provenance kept in the evidence (the schema has no `source` field on a stakeholder). | `stakeholders_unavailable` |
| `relationship.stakeholders[].email_hash` | `Person.Email` | SHA-256 of the trimmed, lower-cased email. The raw email never enters the document. | none |
| `relationship.stakeholders[].title` | `Company Person.Title` | Fill when the CRM title is empty. | none |
| `relationship.stakeholders[].persona` | `Company Person.Role` | Use the confirmed role map. Unmapped roles fall back to the title keywords in `field-sources.md`. | none |
| `relationship.stakeholders[].is_champion` | `Company Person.Role` | True for the role the user confirmed as champion. Use only when the CRM has no champion flag. | `champion_from_cs_platform` |
| `relationship.stakeholders[].is_exec_sponsor` | `Company Person.Role` | True for the role the user confirmed as executive sponsor. Use only when the CRM has no sponsor flag. | none |
| `relationship.champion.status` | `Company Person.Active` | `departed` when the champion's `Active` is false (the person is no longer associated with the company). The CRM champion status wins when it exists. | none |
| `relationship.days_since_last_csm_touch` | `Activity Timeline.Activity Date` | Today minus the newest Call, Meeting or Email logged on the company by the CSM. Setup confirms the author field. Use only when the CRM and email connectors give nothing newer. | `csm_touch_unknown` |
| `lifecycle.stage` | `Company.Stage`, `Company.Status` | Map with the stage table below. Gainsight has no default renewal stage, so the engine's computed `renewal_window` wins inside 120 days of renewal. Unmapped values keep the computed stage. | `lifecycle_stage_unmapped` |
| `lifecycle.kickoff_at` | `Activity Timeline.Activity Date` | The Milestone activity whose milestone type the user confirmed as kickoff. | none |
| `contract.arr` | `Company.ARR` | Corroboration only. Billing and the CRM win. Fill only when neither has ARR. A disagreement over 5 percent is reported. | `arr_source_disagreement` |
| `contract.term_end` | `Company.Renewal Date` | Corroboration only; billing and the CRM win. Fill only when neither has a renewal date. | `term_dates_assumed` |
| `contract.seats_purchased` | `Company.Users` | Gainsight documents this as the number of licensed users. Last fallback after billing and the CRM. | `seats_purchased_unknown` (set 0) |
| `account.csm_owner_id` | `Company.CSM` (a User GSID) | Fill when the CRM has no CSM owner. Read the user's name with `run_query` on User for `account.csm_owner_name`. | `csm_owner_unknown` |
| `account.team[].role` | `Company Teams.User Role` | Map with the team role table below. Unmapped roles are left out. | none |
| `account.team[].user_id` | `Company Teams.User GSID` | Paired with the role row above. | none |
| `sentiment.latest_nps` | `Company.NPS®` | Use only when no survey connector is mapped. There are no per-response rows, so `nps_responses` stays empty and `nps_trend` stays null. | `nps_unavailable` |

## Vocabulary

**Scorecard scheme to the engine's 0 to 100 scale**

| Gainsight scheme | Conversion |
|---|---|
| Numeric | Already 0 to 100. Use as is. |
| Color | Midpoint of the range the score sits in. Gainsight's own example: Yellow spans 50 to 80 and shows 65. |
| Grade | Midpoint of the letter's range. Gainsight's example: C spans 60 to 80 and shows 70. |

Range boundaries are tenant-defined. A score exactly on a boundary belongs to the lower range. Do not translate Gainsight colors into the engine's bands; the engine computes its own band.

**Company Stage and Status to `lifecycle.stage`** (Gainsight default values; tenants can add their own)

| Gainsight value | Engine stage |
|---|---|
| Stage `New Customer` | `onboarding` |
| Stage `Kicked Off` | `onboarding` |
| Stage `Launched` | `adopting` |
| Stage `Adopting` | `adopting` |
| Stage `Will Churn` | unmapped; keep the computed stage and cite "Will Churn" as a risk reason |
| Stage `Churn` or Status `Churn` | `churned` |
| Status `Inactive` | unmapped; flag `lifecycle_stage_unmapped` |

**CTA Type and Reason to `playbook_id`** (suggested defaults; the user confirms the real picklist values in setup)

| CTA Type (Reason) | Playbook |
|---|---|
| Risk (renewal) | `PB-RET-02` |
| Risk (any other reason) | `PB-RET-01` |
| Lifecycle (onboarding, go-live) | `PB-ADP-01` |
| Lifecycle (adoption) | `PB-ADP-02` |
| Any type (EBR, QBR, business review) | `PB-CAD-01` |
| Expansion, enterprise or mid-market account | `PB-EXP-02` |
| Expansion, digital or self-serve account | `PB-EXP-01` |

Gainsight's docs name Risk, Lifecycle and Expansion as example CTA types.

**Company Person Role to persona and flags** (suggested keyword rules; the five default role values are read with `get_picklist_values`, not assumed)

| Role label contains | `persona` | Flag |
|---|---|---|
| champion | `champion` | `is_champion: true` |
| executive sponsor, sponsor | `executive_sponsor` | `is_exec_sponsor: true` |
| decision maker, economic buyer, budget | `economic_buyer` | none |
| admin, administrator | `admin` | none |
| IT, security | `it_security` | none |
| procurement, purchasing | `procurement` | none |
| user, end user | `end_user` | none |
| anything else | from title keywords | none |

**Company Teams User Role to `account.team[].role`**

| User Role contains | Engine role |
|---|---|
| CSM, customer success | `csm` |
| account executive, AE, sales | `ae` |
| implementation, onboarding | `implementation_manager` |
| solutions engineer, SE | `solutions_engineer` |
| support | `support_lead` |
| executive sponsor | `exec_sponsor_internal` |

## Limits and gotchas

- **Corrections to the earlier mapping in `field-sources.md`.** Renewal Date maps to `contract.term_end`; `contract.renewal_date` is not a schema path. Gainsight's default stages are New Customer, Kicked Off, Launched, Adopting, Will Churn and Churn, not Onboarding, Adopting, Established and Renewing. Current Score is a lookup to `Scoring Scheme Definition`, not a stored number. A stakeholder row cannot carry `source: gainsight`, because the schema allows no extra fields; keep provenance in the evidence. Ask Scorecard is not in this connector.
- **Field names vary by tenant.** Gainsight's object glossaries document display names, not API names. The CTA API does use `Gsid`, `TypeId`, `ReasonId`, `StatusId`, `IsClosed`, `DueDate`, `CompanyId` and `OwnerId`. Everything else is confirmed with `get_object_metadata` in setup.
- **Permissions shape coverage.** The MCP server enforces each user's own Gainsight permissions. A CSM may not see every account in the book, and Viewer licenses cannot run `run_query`. Internal Collaborator and External users cannot sign in at all.
- **API budget.** MCP queries count toward the tenant's API limit. The Cockpit API allows 100 synchronous calls a minute and 50,000 a day, and returns at most 1,000 CTAs per call; page with `get_records`. A 40-account book is about 160 calls (company, CTAs, timeline, success plans per account), so run it serially.
- **Scores lag.** The scorecard snapshot runs at 11:30 PM UTC by default. A score changed today may not show until tomorrow. The Account Scorecard History object holds past platform scores; they are not the engine's own history and do not fill `health.score_30d_ago`.
- **Timeline attendee fields are unreliable through MCP.** A Gainsight community post (unofficial, unconfirmed) reports HTTP 500 errors on Internal and External Attendees and says Contact records could not be queried through `run_query`. So stakeholder engagement dates come from the CRM first; Gainsight fills only the company-level CSM touch.
- **No delete, no company field updates.** Gainsight's MCP does not support deleting records or updating Company fields, so even an approved write cannot change ARR, Stage or the score.
- **Claude setup.** The directory connector (made by Gainsight, added June 2026) signs in with the user's own Gainsight credentials through OAuth. A self-built custom connector needs a Gainsight OAuth app with both Claude callback URLs, and custom connectors show only on Team and Enterprise Claude plans.
- **Staircase AI.** The separate Gainsight (Staircase AI) connector is not mapped. Its sentiment and risk summaries are not engine inputs, and Ask Staircase is not in the CS connector's listing.

## Sources

- Gainsight (CS) connector in Claude's directory: https://claude.com/connectors/gainsight-cs
- Gainsight AI tools overview (tool behavior): https://support.gainsight.com/gainsight_nxt/AI_Assistants/MCP_Integration/About/Overview_of_AI_Tools
- Gainsight CS MCP FAQ (permissions, writes, licenses): https://support.gainsight.com/gainsight_nxt/AI_Assistants/MCP_Integration/FAQ/Gainsight_CS_MCP_FAQ
- Gainsight CS MCP server integration (setup, limits): https://support.gainsight.com/gainsight_nxt/AI_Assistants/MCP_Integration/Admin_Guide/Gainsight_CS_MCP_Server_Integration
- Company object: https://support.gainsight.com/gainsight_nxt/02Data_Management/Objects/Gainsight_Company_Object
- Standard objects (Company Person, Person, Company Teams): https://support.gainsight.com/gainsight_nxt/Gainsight_Object_Glossary/CS_Object_Glossary/Gainsight_Standard_Objects
- Cockpit objects (Call To Action fields): https://support.gainsight.com/gainsight_nxt/Gainsight_Object_Glossary/CS_Object_Glossary/Cockpit_Objects
- CTA API (field API names, limits): https://support.gainsight.com/gainsight_nxt/API_and_Developer_Docs/Cockpit_API/Call_To_Action_(CTA)_API_Documentation
- Timeline objects: https://support.gainsight.com/gainsight_nxt/Gainsight_Object_Glossary/CS_Object_Glossary/Timeline_Objects
- Logging Timeline activities: https://support.gainsight.com/gainsight_nxt/Timeline/02User_Guides/Log_Activities_to_Timeline
- Success Plan objects: https://support.gainsight.com/gainsight_nxt/Gainsight_Object_Glossary/CS_Object_Glossary/Success_Plan_Objects
- Scorecard schemes: https://support.gainsight.com/gainsight_nxt/05Scorecards/02Admin_Guides/Configure_Scorecard_Schemes
- Scorecard FAQs (snapshots, history object): https://support.gainsight.com/gainsight_nxt/05Scorecards/FAQs/Scorecard_FAQs
- Salesforce Connector (Salesforce Account ID): https://support.gainsight.com/gainsight_nxt/Connectors/CRM_Integrations/Salesforce_Connector
- HubSpot Connector (HubSpot account id field): https://support.gainsight.com/gainsight_nxt/Connectors/CRM_Integrations/HubSpot_Connector
- Community post on Timeline fields through MCP (unofficial): https://communities.gainsight.com/ideas/make-timeline-fields-available-in-mcp-and-in-line-editing-30868
