# A sample conversation

*Illustrative. The company, people and numbers are made up. The flow, the questions the engine asks, and the way it writes are what the plugin does. Everything about Contoso matches `examples/sample_customer_360.json`, scored as of October 15, 2026.*

*Every reply is written for a CEO who has never heard of the account and could read it cold. The technical detail a CSM needs to check the work sits at the end, under "Details for the CSM".*

---

**You:** set up the CS engine

**Claude:** I checked what's connected to your Claude account and matched each tool to the job the engine needs it for:

| Job | Connected tool | What it lets the engine see |
|---|---|---|
| CRM (required) | HubSpot | Customers, contracts and renewal dates, contacts, activity history |
| Support | Intercom | Open tickets, how fast they're answered, satisfaction scores |
| Customer calls | Zoom | Recorded calls and transcripts |
| Product use | Amplitude | Who logs in, which features they use, how many seats are active |
| Surveys | HubSpot feedback surveys | Satisfaction scores and comments |
| Contact tracking | Clay | Job changes at the people we work with |
| Team chat | Slack | Posting alerts to a channel, only when you approve |
| Email, calendar, documents | Gmail, Google Calendar, Google Drive | Recent emails, upcoming meetings, past review decks |
| Billing | not connected | Contract values will come from HubSpot instead |

Two quick questions: how does your name appear as an account owner in HubSpot, and which email domains are your company's (so I can tell your people from the customer's on calls)?

**You:** Priya Natarajan. vendor.io.

**Claude:** Saved. To show it working, I scored the sample account that ships with the engine:

> **Contoso Logistics (sample): health 60 out of 100, down from 79 a month ago.** Contoso pays $240,000 a year. Their product use, support and contract all score well. The drop has one cause: their main contact appears to have left, and the scoring won't rate an account above 60 until it has a main contact again.

You're set. Say **"review my book"** to see every account, or ask about one by name. Nothing reaches a customer or changes a CRM field until you approve it.

---

**You:** review my book

**Claude:** **31 customers worth $4.1M a year. Two need action today, together worth $420,000 a year.**

*Health is a score from 0 to 100 built from product use, support, relationships and the contract. 75 and up is healthy, 50 to 74 needs attention, under 50 is at risk.*

**Act today**
- **Contoso Logistics** ($240,000 a year, renews January 18, 2027): their main contact appears to have moved to another company, and we don't know who replaces him. Health fell from 79 to 60 in a month. Next: I can build a save plan.
- **Fabrikam Health** ($180,000 a year, renews June 30, 2027): an urgent support ticket has been open for 8 days, and their rating of our support has fallen to 2.8 out of 5. Health 44. Next: I can build a save plan.

**This week**
- **Wingtip Toys** ($65,000 a year, signed in September): 41 days in and still not using the product for real work; similar customers are usually live by day 35. Next: I can find what's blocking them.
- **Tailspin Co** ($90,000 a year, renews February 2, 2027): they use only 38% of the seats they pay for, which usually means they'll ask to renew smaller. Next: I can build the renewal plan.

**Coming up**
- **Contoso Logistics**: quarterly business review with their SVP of Finance Operations and their admin, due November 5.

**Room to grow**
- **Adventure Works** ($48,000 a year, renews March 15, 2027): using 112% of the seats they bought, and they hit their plan's limits 5 times this week. Roughly $14,000 a year if they move to the next plan up.

**Since last time:** Contoso moved from healthy to needs attention. Fabrikam opened its urgent ticket.

**The whole book:** 19 healthy, 9 need attention, 3 at risk. $610,000 renews in the next 90 days; none of those accounts needs action today.

**What I couldn't see:** billing isn't connected, so annual values come from HubSpot. Four accounts' scores are less reliable because I can't see their product use.

Want a full plan for any of these?

**You:** Contoso.

---

**Claude:** Pulling everything on Contoso: 5 contacts and 1 open support ticket, plus 2 survey responses and 1 recorded call from the last 90 days.

Found the cause: their main contact appears to have left, and we don't know who replaces him. Building the renewal plan next.

## Contoso Logistics: a $240,000 renewal with no owner on the customer's side

**The short version.** Contoso pays us $240,000 a year, and the contract ends January 18, 2027, 95 days from now. It doesn't renew automatically. Jordan Reyes, the person who drove our product inside Contoso, appears to have moved to another company, and we don't know who owns the renewal on their side now. The product is working well for them, so this is a people problem, not a product problem. The plan is to get their SVP of Finance Operations, Elena Vasquez, to own it and name Jordan's successor by November 19, two months before the contract ends, so there is time to negotiate.

Contoso's health is 60 out of 100 (needs attention, not yet at risk). We're treating it as urgent because a renewal with no owner can slip quietly.

**The account in brief.** Contoso Logistics is a transportation and logistics company with about 4,200 employees and a customer since January 2025. Two teams use our operations platform: Finance Operations (310 of their 350 seats in use) and Fleet (95 of 150). It has paid off: Finance Operations cut month-end reconciliation from 340 hours a month to 95, a 72% cut against a kickoff goal of half.

| Person | Role | Where things stand |
|---|---|---|
| Jordan Reyes | Director, Operations Systems; our main contact | Our contact tracking shows him at Northwind Traders since at least October 13 (no relation to any customer of ours). Our last outreach, September 7, got no reply on record. |
| Elena Vasquez | SVP Finance Operations; the senior executive who backs the purchase | Engaged: on our August call, last two-way contact September 5. |
| Sam Okafor | Finance Systems Admin | Our most active contact: 7 conversations in 90 days, the latest October 13. |
| Tasha Lindqvist | Fleet Operations Manager | Lukewarm: rated us 6 out of 10 in September. |
| Raj Mehta | VP Procurement | No contact since December 2025. |

On our side: Priya Natarajan (customer success manager), Marcus Bell (account executive) and Dana Whitfield (our executive on the account).

**What happened.** On August 26, Elena and Sam told us they "closed the books four days faster last quarter," and that their EMEA team keeps asking for access. On September 12, Tasha wrote: "Fleet hasn't really adopted it. We were told Jordan would drive that and now Jordan's gone." On October 13, our contact tracking showed Jordan working at Northwind Traders.

**What it puts at risk.** The full $240,000. With no owner, the renewal could be decided by procurement with no one on Contoso's side arguing for us. The likeliest cut is Fleet, which holds 150 of the 500 seats, close to a third of the contract, and has the weakest adoption. What argues against this: use and support are healthy (one open ticket, about intermittent export failures in their EU region, 3 days old; support rated 4.4 out of 5), and Elena was engaged in September.

**The plan.** Goal: renew at $240,000. EMEA's interest is a reason to talk about growth later, once someone owns the account again.

| # | Step | Who | By when |
|---|---|---|---|
| 1 | Confirm with Sam that Jordan has left, and who took over his team and budget | Priya | October 17 |
| 2 | **30-minute meeting with Elena to agree who owns the program now.** This matters most: she can own the renewal today. Uses the email below. | Priya | October 20 |
| 3 | Flag Contoso as high-risk in HubSpot, so it shows in leadership's renewal review | Claude, after your OK | now |
| 4 | Meet one more person in Operations and one in Fleet (ask Tasha who now leads the Fleet rollout) | Priya | October 25 |
| 5 | Book the business review, focused on the renewal, before November 19 | Priya | October 29 |

Don't contact Raj in procurement until Elena backs the renewal, so the first renewal conversation is with a supporter.

**The email to Elena** (a draft; nothing is sent):

> **To:** Elena Vasquez, SVP Finance Operations
> **Subject:** Continuity plan for the Contoso program
>
> Hi Elena,
>
> I heard Jordan may have moved on, and I want to make sure the work your team has built keeps its momentum. Finance Operations has taken month-end reconciliation from 340 hours to 95 a month.
>
> Jordan was also leading the Fleet rollout, which is only partly done. Could we take 30 minutes in the next week to agree who owns the program on your side? If you already have someone in mind, I'd be glad to include them.
>
> I'll bring a short plan for Fleet and a summary of results so far.
>
> Thanks,
> Priya

**What I need from you.** Which of these should I do now?
- ☐ HubSpot task for you and your CS leader: "Red account review: Contoso", due October 17
- ☐ Flag Contoso as high-risk in HubSpot (step 3)
- ☐ Alert #cs-red-accounts in Slack
- ☐ Put the email to Elena in your Gmail drafts (not sent)
- ☐ Save this brief as a Google Doc

**How sure we are.** We're confident Jordan's departure is the cause. The first thing to learn: who took over his team and budget?

**Details for the CSM.** Playbook PB-RET-01 (red account turnaround), fired on a 19-point health drop in 30 days. Priority P0, primary driver `champion_loss`, confidence 0.88, renewal outlook `at_risk`, recommended scenario `full_renewal`. Health capped at 60 by `champion_departed_no_replacement` (73.34 before the cap: weighted sum 74.55, trend adjustment -1.21). Evidence: `relationship.stakeholders[0].enrichment.current_employer = "Northwind Traders"` · `health.score_30d_ago = 79.4` · `relationship.multithreading_depth = 2`. Step 3 writes `cse_risk_tier = red_champion`. Files: `cs-engine/accounts/acc_01HZXK3V8Q/PB-RET-01.churn_risk_rca.action.json`, `PB-RET-01.renewal_defense_playbook.action.json`, `PB-RET-01.renewal_defense_playbook.comm_1.md`.

**You:** The task, the draft, and the doc.

**Claude:** Done:
- **HubSpot task** "Red account review: Contoso", due October 17, for you and your CS leader: [link]
- **Gmail draft** to Elena, "Continuity plan for the Contoso program", in your drafts folder, not sent
- **Google Doc** "Contoso Logistics: what happened and the plan to November 19": [link]

I didn't flag the account in HubSpot or post to Slack, as you asked. I'll keep this open until the renewal is signed. After you talk to Elena, tell me what you learned and I'll update the plan rather than start a new one.

---

*The engine's job ended when Priya had the cause, the plan, the email and a brief her CEO could read cold, in about four minutes. What happens next is up to her.*
