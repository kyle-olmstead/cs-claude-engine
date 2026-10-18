# CS-Claude Engine

**An AI teammate for Customer Success that works inside the tools you already use.**

**If you read nothing else:**
- It connects to your CRM and the other tools your team already has, and tells you which customers are about to leave, which are ready to buy more, and what to do about each one, with the plan and the first email already drafted.
- It never contacts a customer or changes a record without a person approving it.
- It's free, open source, and a CSM can install it in about ten minutes. A sample account is included so you can watch it work before connecting anything.

---

## Start here

```
                          What are you here to do?
                                    │
       ┌───────────────┬────────────┼─────────────┬───────────────┐
       ▼               ▼            ▼             ▼               ▼
  Understand       Try it on    Roll it out   Run it for     Change how
  what it is       my own       to my CS      the whole      it thinks
                   accounts     team          company        (scoring, prompts)
       │               │            │             │               │
    5 min           10 min       1 hour       1–2 weeks       as needed
       │               │            │         (needs an eng)      │
       ▼               ▼            ▼             ▼               ▼
  Read §1–4       §5 Install   §5, then      §11 Server     §12 Under the
                  then say     share this    mode           hood
                  "set up the  link; each
                  CS engine"   person runs
                               setup
```

| If you are… | Start with | What you'll have | Time |
|---|---|---|---|
| **A CEO or exec** deciding if this is worth the team's time | §1–4 (§4 is the business case), then ask your CS lead to run it on five accounts | A clear picture of what it does, what it won't do, and what it needs from you | 5 min |
| **A CSM** with a set of accounts | §5 Install → say *"set up the CS engine"* → say *"review my book"* | A ranked list of who needs attention today, why, and the plan for each | 10 min |
| **A Head of CS / VP** rolling it out | Same on your own accounts, then §8 (the operating rhythm) and share this link | Everyone on one health score, one set of playbooks, one weekly routine | 1 hour |
| **CS Ops / RevOps** | §11 Server mode | Nightly runs across every account, history in your warehouse, an audit trail | 1–2 weeks |
| **An engineer or data person** | §12 → `docs/01_ARCHITECTURE.md` | The full design, every formula, every prompt | As long as you like |

A few words used throughout: a **CSM** is a Customer Success Manager, the person responsible for keeping customers happy and renewing. Their **book** is the set of accounts they look after. A **champion** is your main internal advocate inside a customer's company. A **health score** is a 0–100 estimate of how likely an account is to stay. Full list in §13.

---

## 1. The problem it solves

A CSM typically looks after 30 to 300 accounts. The warning signs that a customer is drifting (logins dropping, the champion leaving, a support ticket aging, a lukewarm survey answer) are spread across five or six systems. Nobody has time to check all of them for every account.

So problems get noticed late, usually in the renewal conversation, when the options are already bad. Meanwhile, customers quietly outgrowing their plan go unnoticed too.

This engine does the checking: every day if you schedule it, or whenever you ask.

---

## 2. What it does, in plain English

1. **Watches every account for trouble.** Each account gets a health score (green / yellow / red) built from usage, support, sentiment, relationships, and contract facts. The score always comes with its explanation, which factor moved it and by how much, never a mystery number.
2. **Explains why, not just what.** When an account turns red, the engine works out the cause (lost champion, incomplete onboarding, reliability problems, doubt about value, a competitor…) and names the single action most likely to fix it.
3. **Writes the plan.** A renewal plan with scenarios, who to talk to, what to ask, and dates, plus a draft of the first email for you to edit and send, or not.
4. **Finds growth.** Accounts using more than they bought, teams hitting feature limits, departments never offered the product. Sized against your price book, with the likely sponsor and the objection to expect.
5. **Preps your business reviews.** A one-page executive narrative, a slide-by-slide script, an ROI table where every number shows its source, and the pre-read email.
6. **Reports the numbers.** Net and gross revenue retention, logo vs. dollar churn, expansion pipeline, revenue per CSM, with the formulas written down so the numbers can be defended.

**What it will never do:** email a customer · change a CRM record without your approval · state a number it can't trace to your data · propose a discount or a contract term.

---

## 3. How it works (one picture)

```
  YOUR TOOLS                    THE ENGINE                                    YOU
  ──────────                    ──────────                                    ───
  CRM             ┐
  Support desk    │     1. Builds one complete picture of the account
  Call recordings ├──►  2. Scores its health and explains the score
  Surveys         │     3. Spots the problem or the opportunity
  Product usage   │     4. Writes the plan and drafts the email      ──►   approve · edit · reject
  Billing         ┘                                                               │
                                                                                  ▼
                        5. Only then: creates the CRM task, posts the alert, saves the email draft
```

Every recommendation carries its evidence: the exact fields in your data it was based on. If the engine can't find the data, it says so and lowers its confidence instead of guessing.

---

## 4. What it's worth

Start with one person. A Customer Success Manager costs about **$165,978 a year** fully loaded, which is about **$92 an hour** of productive time. The engine takes over the reading and the first drafts for the work that eats a CSM's week (business-review prep, the weekly account review, renewal planning, red-account diagnosis, CRM upkeep), and in the model that returns **546 hours a year, about 30 percent of a working year**.

| | One CSM, per year |
|---|---|
| Time the engine gives back | 546 hours (about 30 percent) |
| What that time costs you today | $50,347 |
| What the engine costs | $1,340 a year, plus $1,100 once |

Those hours are time, not cash. The cash shows up in what a leader does with 30 percent of ten people's time, and the memo prices the three common answers:

- **Cover an open seat while you hire.** Per seat, the engine costs about **$16,600** over a five-month gap against **$69,000** of salary that isn't being spent, so the team finishes about **$52,600 under plan** while every orphaned account is still reviewed each morning.
- **Grow without the next hire.** The same ten people absorb about **$3 million** of new revenue, one seat's worth, before anyone is added.
- **Run with one fewer seat.** About **$152,600 a year** in expense removed, or half a point of operating margin on a $30 million book. A leadership decision; the engine makes it safe, not automatic.

The engine pays for itself if it saves one $13,400 renewal a year, and the one-seat case stays positive even if bigger books cost half a point of retention.

These are modeled figures, not customer results, and the engine has not yet run in a production deployment. The full memo explains every number in plain English, names what could go wrong, separates what is verified from what you should test yourself, and ships with the calculator so you can rerun it with your own figures: [`docs/04_ROI_MEMO.md`](docs/04_ROI_MEMO.md).

---

## 5. Install (10 minutes)

You need a paid Claude plan (Pro, Max, Team, or Enterprise) with your CRM connected. It works best in **Claude Code** or the **Claude desktop app with a working folder**, where it can save each account's file and run its scoring script. In a plain web chat it still works, but it scores by hand and can't keep history between conversations.

**In the Claude app:** open **Customize → Plugins → Add marketplace**, enter `kyle-olmstead/cs-claude-engine`, then add the **cs-engine** plugin from that marketplace. (The repository is called *cs-claude-engine*; the plugin inside it is called *cs-engine*. Same thing.)

**In Claude Code:**
```
/plugin marketplace add kyle-olmstead/cs-claude-engine
/plugin install cs-engine@cs-engine
```

Then, in any conversation: **"set up the CS engine."**

Setup looks at which tools you have connected, sorts them into the roles the engine needs (CRM, support desk, call recorder, surveys, product usage, billing, enrichment, chat, email, calendar, documents), confirms the mapping with you, and scores the sample account to prove everything works. Only the CRM is required. Each additional connection sharpens the picture; if something is missing, the engine tells you what it can't see and what that costs in confidence.

---

## 6. What it needs from you

The engine is only as good as three things in your CRM. Thirty minutes here is worth more than any setting:

| Make sure your CRM has… | Because | Where |
|---|---|---|
| **A flag on contacts for champion and decision-maker** | Champion loss is the #1 churn signal; the engine can't detect what isn't marked | Contact property / buying role |
| **Accurate renewal dates and annual revenue on each account** | Every renewal and retention play keys off these | Company / account properties |
| **Your price book** (or just list prices per seat and tier) | Expansion sizing uses placeholder prices until it has yours | A document, or your CRM's product library |

**What it works with.** The engine reads whatever connectors your Claude workspace already has, and `cs-setup` maps them to the roles it needs. Checked against Claude's connector directory on 2026-10-17:

| Role | Built against | Connectors available today |
|---|---|---|
| CRM (required) | HubSpot, Salesforce | Pipedrive, Attio, Zoho CRM, Close |
| CS platform (optional) | | Gainsight |
| Support desk | | Intercom, Pylon, Zoho Desk, HubSpot Service Hub |
| Calls | Zoom | Fireflies, Fathom, tl;dv |
| Product analytics | | Amplitude, Mixpanel, Pendo, PostHog |
| Warehouse | the dbt project | BigQuery, Snowflake, Databricks, dbt |
| Billing, enrichment, chat, email, calendar, docs | Clay | Stripe, Chargebee, Apollo, ZoomInfo, Slack, Microsoft 365, Gmail, Google Calendar, Google Drive, Notion |

Any custom connector your admin adds works the same way. Tools with no connector yet (Zendesk, Gong, Qualtrics, and most CS platforms other than Gainsight) are listed with three ways to bring their data in: [`CONNECTORS.md`](CONNECTORS.md).

If you'll let the engine write back to the CRM (it asks first, every time), create four custom text fields on the account: `cse_risk_tier`, `expansion_candidate`, `onboarding_risk_tier`, `cse_last_playbook`. Skip this and it still works; it just reports instead of writing.

**One honest note on the health score.** It ships with sensible default weights, and they are a starting point, not a verdict. After one quarter, check: did red accounts actually churn more than green ones? If not, the weights need adjusting to your business. The engine includes the method (`docs/02_METRICS_TAXONOMY.md`, section B1); it takes an afternoon.

---

## 7. What to say to it

| Say… | What happens |
|---|---|
| "set up the CS engine" | Finds your connected tools and configures itself |
| "review my book" | Ranks all your accounts: who needs attention today, why, which play to run. Schedule it to run daily. |
| "how healthy is Contoso?" | Builds the full picture of one account and explains its health score |
| "Contoso just went red" / "our champion at Contoso left" | Root-cause analysis → save plan → executive outreach draft |
| "prep the Contoso renewal" | Renewal scenarios, stakeholder asks, dated plan, kickoff email draft |
| "Contoso is stuck in onboarding" | Finds the blocker, assigns owners, sets a go-live date, drafts the check-in |
| "what features is Contoso not using?" | Compares to similar healthy customers and ranks what to enable next |
| "where can we expand Contoso?" | Sized growth plays, the sponsor, the objection, the sales handoff |
| "prep the Contoso business review" | Narrative, slide script, ROI table, pre-read email |
| "what's our net revenue retention?" | Retention and efficiency metrics with the formulas shown |

*"Contoso" stands for any account name in your CRM; say whatever your customer is called. The engine looks the name up in your CRM, asks if more than one record matches, and tells you if none does.*

Every one ends the same way: it shows what it found and asks which actions you want: a CRM task, a Slack alert, an email *draft*, a saved document. Nothing happens until you say yes. A full sample conversation is in [`examples/demo_conversation.md`](examples/demo_conversation.md).

---

## 8. The operating rhythm (this is the part that makes it work)

Tools don't change outcomes; routines do. The engine is built around this cadence:

| When | Who | What | Time |
|---|---|---|---|
| **Daily** | Each CSM | Read the scheduled book-review digest. Act on anything marked P0. | 5 min |
| **Weekly** | CSM, Monday | "review my book" in full; run the playbook on the top two flagged accounts; approve or reject the proposed actions | 20–30 min |
| **Weekly** | CS leader | Red-account review using the engine's root-cause analyses instead of status updates | 30 min |
| **Before every renewal / business review** | CSM | "prep the renewal" or "prep the business review" | 15 min vs. the usual 4–6 hours |
| **Quarterly** | CS Ops or leader | Validate the health score against what actually churned; adjust weights; review which triggers were ignored and why | one afternoon |

A team that only does the weekly 20 minutes gets most of the value. A team that skips the quarterly check gets a score nobody trusts within six months.

---

## 9. A worked example

*The account below is made up. The reasoning is exactly what the engine does.*

Contoso Logistics, a $240,000-a-year enterprise customer, 95 days from renewal. Health dropped from 79 to 60 in a month.

The engine notices that the champion's enrichment data now shows a different employer, that product usage is actually fine (the Finance team is active daily), and that only two people at Contoso talk to us. Its diagnosis: this is not a product problem; it is an *ownership vacuum*: nobody at Contoso owns the renewal anymore. Its plan: ask the executive sponsor to name a successor within a week, add two more contacts in the champion's department, and run a business review before day 60. It drafts a 140-word note to the sponsor asking for 30 minutes and a name, and lists the seven data points it relied on.

The CSM edits one sentence, sends it, and the next conversation starts from the cause instead of the symptom.

---

## 10. Trust and control

- **You approve everything customer-facing.** Emails are drafts. CRM changes are proposals. The engine has no way to send mail.
- **Every number has a source.** Each recommendation lists the exact data fields it relied on; claims without evidence are rejected automatically.
- **It knows what it doesn't know.** Missing data becomes a flag and lower confidence, never a guess.
- **Where your data goes.** The engine reads through connectors you already authorized in Claude. Claude processes that data under your plan's terms, the same as any other Claude conversation. Working files stay in your own folder. Nothing is sent to the author of this repository.
- **No pricing, ever.** It will flag that a commercial conversation is needed. The terms are yours.

---

## 11. For bigger teams: server mode

The same engine can run as a scheduled job against your data warehouse (every account, every night, with history and an audit log), writing back to the CRM through the same approval rules. It ships with the warehouse models (dbt), the scoring code, and the orchestration script. This path needs an engineer and takes one to two weeks: [`docs/00_SERVER_QUICKSTART.md`](docs/00_SERVER_QUICKSTART.md).

---

## 12. Under the hood (for the technical reader)

```
cs-claude-engine/
├── skills/        10 plugin skills: what runs when you talk to it
├── prompts/       8 versioned prompts: how the engine reasons (guardrails built in)
├── src/           Python: health score, retention math, orchestrator, validator, CRM/enrichment/transcript tools
├── src/schemas/   The two contracts: customer_360.json (input) and playbook_action.json (output)
├── dbt/           A runnable dbt project: sources, 14 staging models, the two marts, tests, and seeds that build on your laptop
├── scripts/       Seed generator, SQL↔Python parity check, weight sync, ROI calculator
├── docs/          Server quickstart · architecture · metrics (every formula) · playbook index · ROI memo
├── playbooks/     Long-form operating playbooks with triggers, timelines, roles, exit criteria
├── CONNECTORS.md  How tool categories map to real products
├── examples/      A complete sample account and a sample conversation
└── tests/         The checks CI runs on every change (pytest)
```

Every technical document opens with a plain-English summary so you can stop reading when you've learned what you came for.

---

## 13. Words used here

| Term | Meaning |
|---|---|
| **CSM** | Customer Success Manager, responsible for keeping customers happy and renewing |
| **Book** | The accounts one CSM looks after |
| **Health score** | A 0–100 estimate of how likely an account is to stay and grow |
| **Champion** | Your main internal advocate inside the customer's company |
| **Executive sponsor** | The senior person on the customer side who backed the purchase |
| **Churn** | Customers (or revenue) that leave |
| **NRR / GRR** | Net / gross revenue retention: how much of last year's revenue from existing customers you still have, with and without growth counted |
| **EBR / QBR** | Executive / quarterly business review: the periodic meeting where you show the customer what they got |
| **Customer 360** | The single data picture of an account the engine builds before deciding anything |
| **Playbook** | "When X happens, do Y": the engine's repeatable responses to specific situations |

---

## FAQ

**Does it need an API key?** No. Plugin mode uses the connectors already in your Claude account. Server mode does.

**I only have a CRM. Is that enough?** Yes. You'll get health scores and every playbook at reduced confidence, and the engine tells you which extra connection would help most.

**Does it work with HubSpot? Salesforce? Zendesk? Gong?** HubSpot and Salesforce, yes; the repo is built against both. Zendesk and Gong have no Claude connector yet, so they are not plug-and-play; most teams bring their numbers in through the CRM, a warehouse export, or a custom connector, and [`CONNECTORS.md`](CONNECTORS.md) walks through all three. Everything with a connector in Claude's directory works through setup, because the engine is built around roles, not brands.

**Can my whole team use it?** Yes. Each person installs it and runs setup once; everyone gets the same scoring and playbooks.

**Will it ever email my customers?** No. There is no send path. It writes drafts for you.

**Is the health score accurate?** It's a well-reasoned default. Validate it against your own churn after one quarter (§6); that's true of every health score ever built.

**What does it cost?** The software is free (Apache 2.0). You need a paid Claude plan.

---

## License

Apache 2.0: use it, change it, ship it. Improvements to the prompts and playbooks are the most valuable pull requests.
