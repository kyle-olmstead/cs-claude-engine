# The business case, in plain English

*What this engine is worth to a company, explained so that anyone can follow the math. Every number here comes from one small program, `scripts/roi_model.py`, that you can run with your own figures. Where a number is an assumption, it says so. Where something has not been measured yet, it says that too.*

---

## First, what this thing is

A Customer Success Manager (a CSM) is the person at a software company whose job is to keep customers happy enough to renew, and to spot when they could use more of the product. A good one looks after 50 to 80 companies at once.

The problem is that the clues about whether a customer is drifting away are scattered across five or six different systems: the sales database, the support ticket queue, recorded calls, survey answers, and the product's own usage logs. Nobody has time to check all of them for every customer every day. So trouble gets noticed late, usually when the contract is already up for renewal and the customer has already half-decided.

CS-Claude Engine is free, open-source software that does the checking. It plugs into the tools a team already has, reads everything overnight, and tells each CSM which customers are about to leave, which are ready to buy more, and what to do about each one, with the plan and the first email already drafted. It never contacts a customer or changes a record on its own. A person approves everything.

Think of it as giving every CSM a research assistant who reads every file before they wake up and leaves a one-page brief on their desk. The CSM still makes the call and has the conversation. They just stop spending half their week finding out what they should already know.

This memo answers the question a CEO or CFO will ask next: *what is that worth?*

---

## The 60-second version

| | Year 1 | Every year after |
|---|---|---|
| Cost of two CSM seats you no longer fill | $331,955 avoided | $331,955 avoided |
| Severance for two departures | $35,385 | none |
| Engine, one-time setup | $11,000 | none |
| Engine, annual run cost | $13,400 | $13,400 |
| **Net effect on operating expense** | **+$272,170** | **+$318,555 per year** |

For a company with $30 million in annual recurring revenue, that is about **1.1 points of operating margin** before counting any improvement in retention. The engine has to save **one $13,400 renewal a year** to pay for itself.

If your situation is the more common one, a single seat that just opened rather than two underperformers, Part 8 does the same arithmetic per seat: the engine costs about $16,600 over a five-month gap against $69,000 of salary you are not spending, so you finish about **$52,600 under plan** while the book stays covered.

The rest of this memo shows where those numbers come from, what has to be true for them to hold, and what could go wrong.

---

## Part 1. What a CSM really costs

Most people think a CSM costs their salary. The real number is a lot higher, the same way a car costs more than its sticker price once you add insurance, fuel, and repairs.

Here is one mid-market or enterprise CSM at a growth-stage software company, itemized:

| What you pay for | Why | Per year |
|---|---|---|
| Base salary | Industry data puts enterprise-level CSMs around $110,000 to $135,000 (see Sources) | $115,000 |
| Bonus at target | Usually 15 percent of total pay, tied to renewals and growth | $20,000 |
| **Pay (OTE)** | | **$135,000** |
| Employer payroll taxes | Social Security and Medicare, 7.65 percent | $10,328 |
| Health insurance, employer share | | $11,000 |
| 401(k) match | 3 percent | $4,050 |
| Disability, life insurance, other | | $1,600 |
| **Benefits** | **About 20 percent on top of pay** | **$26,978** |
| Software seats | CRM, success platform, ticketing, call recording, enrichment tools | $2,500 |
| Laptop, equipment, home-office stipend | | $1,500 |
| **Total, if the person stays** | | **$165,978** |

That is the cost if nobody ever leaves. But CSMs do leave, roughly one in five each year. Each departure costs real money:

| When a CSM leaves | How it is figured | Cost |
|---|---|---|
| Finding a replacement | Recruiters and job boards run about 20 percent of salary | $23,000 |
| The new hire's first 90 days | They are about half as productive while learning, so you pay full price for half the work | $20,463 |
| Customers slipping through the cracks | The departed CSM's $3 million in accounts is under-watched for about six months; assume one percent of it is lost | $30,000 |
| **Per departure** | | **$73,463** |
| **Spread across every seat, at 20 percent turnover** | | **$14,693 per seat per year** |
| **Total, with turnover priced in** | | **$180,670** |

So a team of ten CSMs costs **$1.66 million a year** if everyone stays, and **$1.81 million** in the real world where people leave. Together they look after about **$30 million** in annual recurring revenue.

---

## Part 2. The situation every CS leader has been in

Two of the ten are not working out. Their renewal numbers are flat, they are slow to respond, and they spend their weeks on administrative work instead of with customers. Between them they look after **$6 million** in customer contracts.

What are they costing?

| | Per year |
|---|---|
| Their two seats | $331,955 |
| Customers they lose that a stronger CSM would have kept (3 points worse retention on $6 million) | $180,000 in revenue |
| Growth they miss that a stronger CSM would have found (5 points less expansion on $6 million) | $300,000 in revenue |
| **The cost of doing nothing** | **$331,955 in expense plus roughly $480,000 in revenue** |

The revenue drag is an estimate, because it depends on what "underperforming" means at your company. The expense is not.

---

## Part 3. Two ways to fix it

### Option A: Replace them

The traditional answer. Let the two go, hire two more.

| One-time cost | |
|---|---|
| Severance (8 weeks of salary, times two) | $35,385 |
| Recruiting two replacements | $46,000 |
| Two 90-day ramps at half productivity | $40,926 |
| Six months of under-watched accounts on $6 million | $60,000 |
| **Year-one cost to swap** | **$182,311** |

And the two new seats still cost $331,955 a year. You spent $182,000 to end up where you started, with two unknown hires and $6 million of accounts that nobody really owned for half a year.

### Option B: Do not backfill. Give the other eight the engine.

Spread the $6 million across the eight CSMs who are performing. Each one goes from $3.0 million to $3.75 million in accounts, about 60 companies to about 75. That is 25 percent more work per person, which is only reasonable if you take 25 percent of the busywork off their plate.

That is exactly what the engine does. Here is where the hours come from, for one CSM over a year:

| Task | Today | With the engine | Hours returned |
|---|---|---|---|
| Preparing quarterly business reviews (80 a year) | 5 hours each, building the deck and the numbers from scratch | 2 hours, editing a generated script, a return-on-investment table, and a pre-read email | 240 |
| Weekly review of every account | 3 hours a week, clicking through five systems | 45 minutes, reading a ranked list of who needs attention and why | 108 |
| Preparing for renewals (60 a year) | 3 hours each | 1 hour, editing the scenarios and the asks | 120 |
| Diagnosing a customer that turned red (12 a year) | 4 hours each | 1.5 hours | 30 |
| Updating the CRM, creating tasks, writing notes | 2 hours a week | 1 hour, approving what the engine proposes | 48 |
| **Total** | | | **546 hours, or 30 percent of a working year** |

The team needs 25 percent. The engine returns 30. That five-point cushion is the margin of safety, and the engine watches it: it raises a flag when any CSM's book grows past 115 percent of target while carrying two or more at-risk accounts.

What the engine costs:

| | One-time | Per year |
|---|---|---|
| Claude seats for 10 people (assumed $30 a month each; use your plan's price) | | $3,600 |
| AI usage for nightly runs across 600 accounts (budgeted with room to spare) | | $5,000 |
| Two days a quarter for someone in CS Operations to check the scoring against real churn | | $4,800 |
| Setup: two weeks of an engineer, one week of CS Operations | $11,000 | |
| **Total** | **$11,000** | **$13,400** |

### Side by side

| | Option A: replace | Option B: engine |
|---|---|---|
| Cash out in year one | $182,311 | $46,385 (severance plus setup) |
| Ongoing cost, every year after | $331,955 for two seats | $13,400 for the engine |
| **Year-one result versus doing nothing** | **$182,311 worse** | **$272,170 better** |
| **Every year after, versus doing nothing** | **the same** | **$318,555 better** |
| Who watches the $6 million during the change | nobody, for about six months | eight experienced CSMs, from day one |

---

## Part 4. What this means for profit

Boards watch a number called EBITDA, which is close enough to "profit from running the business" for this purpose. Removing $318,555 of expense without losing revenue adds $318,555 to it.

Then there is retention. The whole point of the engine is to notice trouble earlier. If it works even modestly, the company keeps customers it would have lost. Here is what that is worth on a $30 million book, assuming 80 cents of every retained revenue dollar is profit (typical for software):

| If the engine... | Retention change | Revenue effect | Added profit per year | As margin on $30M |
|---|---|---|---|---|
| Hurts a little, because books got bigger | half a point worse | $150,000 lost | **+$198,555** | +0.66 points |
| Changes nothing about retention | none | none | **+$318,555** | +1.06 points |
| Catches risk a bit earlier | half a point better | $150,000 kept | **+$438,555** | +1.46 points |
| Catches risk earlier and surfaces growth | one point better, plus one point more expansion | $600,000 kept and won | **+$798,555** | +2.66 points |

Notice the first row. Even if spreading the accounts thinner costs the company half a point of retention, the decision is still clearly positive, because the expense removed is more than twice the revenue at risk. That is the row a CFO should test first.

The bottom two rows are targets, not promises. Part 6 explains how to find out which row you are actually in.

---

## Part 5. Why this is different from just cutting cost

Hiring scales in a straight line. Every $3 million of new customer revenue needs another CSM: another $166,000 to $181,000, another search, another ramp. Forever.

The engine bends that line. The same eight people cover 25 percent more revenue for an extra $13,400, and the quality of the brief they get on account number 75 is identical to the one on account number 1, because the engine does not get tired or skim. The limiting factor stops being "how many accounts can a person keep track of" and becomes "how many good conversations can a person have." That second thing is what you are paying a CSM for in the first place.

---

## Part 6. What has to be true, and what could go wrong

An honest business case names its own weak points.

**The engine has to return at least 25 percent of a CSM's time.** The 30 percent above is a model. Measure it: pick four CSMs, track their week for two weeks before and two weeks after. If the number comes back at 20 percent, backfill one of the two seats and the case still works, just smaller.

**Retention has to hold.** The engine pays for itself at 0.045 points of retention, which is one saved $13,400 renewal a year. But the real question is whether bigger books hurt. The downside row in Part 4 shows the answer is still positive at half a point of damage. Beyond a point and a half of damage, Option B loses to doing nothing, and you would know within two quarters.

**The health score has to mean something at your company.** It ships with sensible default weights. After one quarter, check whether customers it marked red actually churned more than customers it marked green. If not, adjust the weights (the method is written down in `docs/02_METRICS_TAXONOMY.md`). A score nobody trusts is worse than no score.

**People have to use it.** Tools do not change outcomes; routines do. The README describes a weekly 20-minute routine. A team that skips it gets nothing.

---

## Part 7. What is proven today, and what you should test yourself

This engine has **not** been run in a production deployment yet. Anyone who tells you their new software is "battle-tested" on day one is selling. Here is the honest split.

**Verified. You can check these yourself in minutes; the repository's automated tests run them on every change.**

| Claim | How it is checked |
|---|---|
| The engine cannot invent a number | Every figure in its output must point to a specific field in the customer's data, and the value must match. A wrong number fails and is sent back for correction; a second failure is set aside for a human. |
| It cannot email a customer | There is no code path that sends email. It writes drafts. |
| It cannot change a contract, a price, or a forecast | Those fields are locked behind human approval in code, regardless of what the AI suggests. |
| It cannot write to someone who has left the customer | Recipients are checked against the current contact list before a draft is produced. |
| Its health score is the same whether computed in the database or in Python | A parity check runs on every change; current difference: zero. |
| The whole thing runs with no AI key and no database | A built-in sample lets anyone watch it work before connecting anything. |

**Built in by design, not yet measured under load.**

| Concern | What the design does |
|---|---|
| Hundreds of accounts at once | Each account is handled separately, with its own slice of data. Account 200 gets the same attention as account 1. Nothing is "remembered" between accounts that could get confused or run out of room. |
| Customers typing instructions into surveys or tickets to trick the AI | Customer-written text is fenced off and treated as data, never as instructions. |
| Heavy nightly runs | Uses the AI provider's batch service, which is built for volume and costs half as much. Roughly 5 to 10 cents per account per day. |
| Personal data | Email addresses are scrambled before they enter the system; phone numbers and card-like numbers are stripped from transcripts. |
| An audit trail | Every AI call and every proposed change is logged with what went in, what came out, and who approved it. |

**Not yet measured. How to measure it.**

| Open question | Method |
|---|---|
| How it performs during a sudden burst of alerts | Replay a month of your real support tickets and CRM changes against it and time the result. The replay harness is specified but not yet built. |
| Whether the health score predicts churn *at your company* | One quarter of data, then compare red versus green outcomes. Written procedure in the metrics guide. |
| How much time it actually returns | Two-week time study, four CSMs, before and after. |
| Security and compliance certifications | Certifications like SOC 2 belong to the company running the software, not to the code. The code provides the controls above; your security team confirms data handling, retention, and vendor terms with the AI provider before production use. |

---

## Part 8. The common case: one open seat

Parts 2 through 4 describe a decision: two people are not working out, and you choose not to replace them. Most CS leaders meet this engine in a smaller and far more frequent situation. One seat opens. Someone resigns, gets promoted, or goes on leave. The accounts they owned still have to be covered while you find and ramp the replacement, and the people covering them already had full days. At the 20 percent turnover rate used in Part 1, a ten-person team has one of these roughly twice a year.

The arithmetic for one seat uses the same numbers as the rest of this memo, in a smaller unit: **one seat for one month**, because that is how the budget line reads. Finance calls the salary that goes unspent while a seat is open "vacancy savings." Customer Success calls the same period a coverage gap.

**What the gap costs.** From Part 1, a departure costs $73,463 before the replacement is productive: $23,000 to recruit, $20,463 of reduced output while the new person ramps, and $30,000 of revenue put at risk because nobody fully owned the book for a while. From the day the seat opens to the day the hire is ramped is typically about five months: 45 to 60 days to fill, then 90 days at half productivity.

**What the engine does during the gap.** The same three things it does every day, pointed at the accounts that lost their owner. It spreads them across the remaining team. It gives each covering CSM the account's full record so they are not starting cold. And it reviews every one of those accounts every morning and says which ones need a human today, so an account cannot quietly go dark for six weeks because it belonged to someone who left.

**The numbers, per seat.**

| | One open seat, five months |
|---|---|
| Salary not being spent while the seat is open | $13,831 a month, $69,157 over the gap |
| Revenue at risk in the model while the book is under-covered | $30,000 |
| Engine over the same five months (setup plus five months of run cost) | $16,583 |
| Engine cost as a share of the revenue at risk | 0.55 |
| **Net against plan while the book stays covered** | **$52,574 under budget** |
| The nine people who stayed | each takes 11 percent more book; the engine returns about 30 percent of their hours |

Two seats open at once doubles the salary and risk lines; the engine line does not double, because the setup is paid once and the run cost is the same. If the engine was already installed before the seat opened, the setup is already paid and the gap costs about five months of run cost, roughly $5,600.

**The honest line.** The only modeled hard-dollar figure the engine directly addresses here is the $30,000 of revenue at risk, and the engine costs about half of that over the gap. The rest of the one-seat case is the budget line, which is four times the engine's cost and already approved, and the hours returned to the people absorbing the book. The ramp of the new hire should shorten when they inherit a maintained record instead of a cold CRM, but no number for that belongs in this memo until someone measures it (Part 7 says how).

---

## Run it with your numbers

Every figure in this memo comes from one short program. Change any assumption:

```
python3 scripts/roi_model.py
python3 scripts/roi_model.py --base 125000 --ote 150000 --turnover 0.25 --arr-per-csm 4000000
python3 scripts/roi_model.py --open-seats 2 --gap-months 4        # Part 8 with your own gap
python3 scripts/roi_model.py --json
```

| Assumption | Used here | Reasonable range | What moves |
|---|---|---|---|
| Base pay / total pay | $115,000 / $135,000 | $110,000 to $135,000 base | about $30,000 of annual savings per $15,000 of pay |
| Benefits load | 20 percent of pay, itemized | 18 to 22 percent. Government data for all private workers is closer to 43 percent of wages once paid leave and retirement are included; at that rate a seat costs $196,978 and the savings grow to about $381,000 | the size of every savings figure |
| Annual CSM turnover | 20 percent | 15 to 30 percent | about $3,700 per seat per five points |
| Revenue at risk per departure | 1 percent of a $3M book | 0.5 to 2 percent | $15,000 per departure |
| Revenue per CSM | $3 million | $2 to $5 million for mid-market | scales the retention table |
| Profit on retained revenue | 80 percent | 70 to 85 percent | converts revenue to profit |
| Time returned per CSM | 30 percent | 20 to 40 percent | below 25, backfill one seat |
| Claude seat price | $30 per month | your plan | a few thousand dollars |
| Length of an open-seat gap (Part 8) | 5 months | 3 to 7 months | about $13,800 of unspent salary and $1,100 of engine cost per month |

---

## Sources

- [Founderpath, SaaS Customer Success Manager salary benchmarks, 954 verified salaries, updated September 2026](https://founderpath.com/salary-benchmarks/saas/customer-success-manager): median base $75,000 across all CSMs; average $110,730; enterprise CSMs 20 to 35 percent higher; variable pay typically 15 to 25 percent of base.
- [U.S. Bureau of Labor Statistics, Employer Costs for Employee Compensation, June 2026](https://www.bls.gov/opub/ted/2026/compensation-costs-for-private-industry-workers-averaged-46-89-per-hour-worked-in-june-2026.htm): private industry total compensation $46.89 per hour; wages 70.0 percent; benefits 30.0 percent.
- `scripts/roi_model.py` in this repository: the arithmetic.
