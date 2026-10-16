# A sample conversation

*Illustrative. The company, people, and numbers are made up; the flow, the questions the engine asks, and the shape of what it returns are exactly what the plugin does. The data here matches `examples/sample_customer_360.json`.*

---

**You:** set up the CS engine

**Claude:** I looked at what's connected in your account and sorted it into the roles the engine uses:

| Role | Connector | What it unlocks |
|---|---|---|
| CRM | HubSpot | Accounts, contracts, contacts, activities, renewals — required ✔ |
| Support desk | Zendesk | Open tickets, response times, CSAT |
| Call recorder | Zoom | Recent customer calls and transcripts |
| Product usage | — not connected | Logins, feature use, seat utilization. Without it, the health score runs on relationship, support, sentiment, and contract facts only; adoption is scored as unknown. |
| Surveys | HubSpot (feedback surveys) | NPS responses and comments |
| Chat | Slack | Alerts to a channel, with your approval |
| Email / Calendar / Documents | Gmail, Google Calendar, Google Drive | Engagement recency, EBR dates, prior decks |

Two quick questions: how does your name appear as an owner in HubSpot, and which email domains are yours (so I can tell your people from customers on calls)?

**You:** Priya Natarajan. vendor.io.

**Claude:** Saved. To prove the install I scored the bundled sample account:

> **Contoso Logistics · enterprise · $240,000 · 95 days to renewal · health 60 YELLOW (−19 vs. 30 days ago)**
> Champion marked *departed* with no successor → score capped at 60. Usage is healthy (adoption 74/100); the drop is entirely in the relationship component.

You're set. Try **"review my book"** for the whole picture, or name an account.

---

**You:** review my book

**Claude:** 31 accounts, $4.1M. Here's what needs attention, highest priority first:

**P0 — act today**
- Contoso Logistics · $240k · health 60 (−19) · champion departed, no successor, 95 days to renewal → *red-account-turnaround*
- Fabrikam Health · $180k · health 44 · P1 ticket open 8 days, CSAT 2.8 → *red-account-turnaround*

**P1 — this week**
- Northwind Retail · $65k · onboarding day 41 with no go-live milestone (segment target: 35) → *ttv-acceleration*
- Tailspin Co · $90k · health 68 · renewal in 110 days, 38% of seats active → *renewal-defense*

**P2 — cadence**
- Contoso Logistics · business review due in 21 days → *ebr-generator*

**P3 — expansion-ready**
- Adventure Works · $48k · 112% of seats active, 5 feature-gate hits this week → *expansion-whitespace* (roughly $14k indicative)

**Portfolio:** 19 green / 9 yellow / 3 red · $610k renewing in 90 days · 2 accounts over 85% utilization · one EBR due.
**Data gaps:** no product-usage connector — 31 accounts scored without adoption data.

Which of these do you want me to run the full playbook on now?

**You:** Contoso.

---

**Claude:** Running the turnaround on Contoso. Pulling the full account picture… done (7 stakeholders, 1 open P2, 2 NPS responses, 1 call in the last 90 days). Root-cause analysis next.

> **PB-RET-01 · P0 · primary driver: champion loss · confidence 0.88 · renewal outlook: at risk**
>
> **Diagnosis.** Contoso's champion, Jordan Reyes, now shows a different employer in enrichment data (Northwind Traders) and has had no activity in 38 days; no successor is identified. Usage is strong — Finance Ops is active daily and the latest call reported closing the books four days faster — so this is not dissatisfaction. It is an ownership vacuum: with 95 days to renewal, nobody on the customer side owns the decision, and only two Contoso contacts are engaged. The interrupting move is to secure the executive sponsor as interim owner and recruit the successor before day 60.
>
> **Counter-evidence:** usage and CSAT (4.4) are healthy; the exec sponsor engaged 40 days ago.
> **Question to ask first:** who inherited Jordan's team and budget?

Building the renewal plan from that… done.

| # | Action | Owner | Due | Needs your OK |
|---|---|---|---|---|
| 1 | Confirm departure and successor with Sam Okafor (admin) | you | 2 days | — |
| 2 | **Continuity meeting with Elena Vasquez (SVP Finance Ops, exec sponsor)** ← the interrupting intervention | you | 5 days | yes (email draft) |
| 3 | Set `cse_risk_tier = red_champion` on the account | engine | now | yes (CRM write) |
| 4 | Identify two more contacts in Finance Ops | you | 10 days | — |
| 5 | Schedule the business review before day 60 (renewal variant) | you | 14 days | — |

**Recommended scenario:** full renewal, with multi-year + EMEA module as the fallback (the last call mentioned EMEA asking for access). **Stakeholder asks:** Elena — 30 minutes and a successor's name; Sam — confirm who inherited Jordan's budget; Raj Mehta (procurement) — not yet, not until Elena is engaged.

**Draft ready:** email to Elena Vasquez, subject *"Continuity plan for the Contoso program"*, 138 words, one ask. Saved as `cs-engine/accounts/acc_01HZXK3V8Q/PB-RET-01.comm_1.md`.

**Evidence (top 3):** `relationship.stakeholders[0].enrichment.current_employer = "Northwind Traders"` · `health.score_30d_ago = 79.4` · `relationship.multithreading_depth = 2`

Which of these should I do now?
☐ Create the HubSpot task "Red account review — Contoso" for you and your CS leader (due in 2 days)
☐ Set `cse_risk_tier = red_champion` on the Contoso company record
☐ Post the P0 alert to #cs-red-accounts
☐ Create a Gmail *draft* of the email to Elena
☐ Save the RCA and plan as a Google Doc

**You:** The task, the draft, and the doc.

**Claude:** Done:
- HubSpot task created — [link]
- Gmail draft created in your mailbox (not sent) — subject "Continuity plan for the Contoso program"
- Google Doc "Contoso — RCA and 30-day save plan" — [link]

I skipped the risk-tier write and the Slack alert as you asked. The action is logged; if you run this again after you've spoken to Elena, I'll update it rather than start over. Exit criteria: health off red for 30 days and the renewal closed, or more than 180 days out.

---

*What happened next is up to the CSM. The engine's job ended when the person had the cause, the plan, the draft, and the evidence — in about four minutes.*
