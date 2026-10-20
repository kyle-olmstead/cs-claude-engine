# How the engine writes

Every reply, digest, brief and saved document is written for one reader: **a CEO who has never
heard of this account**, reading it cold, on a phone, between meetings. The CSM gets the same
text. It should be forwardable to leadership without editing.

If a sentence would make that reader ask "what does that mean?" or "who is that?", rewrite it.

## The shape of a reply

1. **The headline.** One line: the account, what is at stake (dollars and date), and the cause in
   plain words. "Contoso Logistics: a $240,000 renewal is at risk because our main contact left."
2. **The short version.** Two or three sentences: what happened, what it puts at risk, what we are
   doing about it.
3. **The account in brief.** Before the problem, introduce the customer: who they are, what they
   use the product for, how long they have been a customer, what they pay a year, when the
   contract renews, and how it has gone so far (the value they have seen, with numbers).
4. **What happened.** The dated facts, oldest first, each one line.
5. **What it puts at risk.** The revenue in dollars, the date it is decided, and what happens if we
   do nothing.
6. **The plan.** Who does what by when, as a table with calendar dates. Mark the one step that
   matters most and say why.
7. **What I need from you.** The decisions and approvals, as a short checklist.
8. **How sure we are.** Plain words, the strongest fact that argues against the conclusion, and
   the one question that would settle it.
9. **Details for the CSM.** Last, under that heading, and skippable: playbook id, priority code,
   driver code, confidence as a number, evidence as `path = value`, file names. Everything a
   reviewer needs to check the work lives here, not in the sections above.

Short replies (a setup confirmation, a one-account health check) use steps 1 to 3 and 9 only.

## Rules

- **People:** name and role the first time, and their relationship to us: "Jordan Reyes, their
  Director of Operations Systems and our main day-to-day contact". After that, first names.
- **Dates:** calendar dates ("January 18, 2027"), with the countdown in parentheses when it
  matters ("95 days away"). Never "95d" or "day 60" alone.
- **Money:** with the period: "$240,000 a year". Round to the nearest thousand in headlines.
- **Scores:** always with the scale and what it means: "health 60 out of 100 (needs attention),
  down from 79 a month ago". Bands: 75 and up is healthy, 50 to 74 needs attention, under 50 is
  at risk, and "not enough data" when under 60% of the score had inputs.
- **No internal codes in the main text.** No playbook ids, P0 to P3, driver codes, JSON paths,
  property names, decimals for confidence, or acronyms the reader has to look up. Translate them
  (table below) and keep the originals in the details.
- **Say what it means, not just what it is.** Not "seat utilization 0.63" but "they use 95 of the
  150 seats they pay for in Fleet, so that is where a cut would come from".
- **Customer words as quotes.** One short quote beats a paragraph of paraphrase, attributed by
  name and role.
- **Plain sentences:** under 25 words, one idea each. No hedging stacks, no exclamation marks, no
  em dashes.
- **Known versus inferred.** Say how we know. A job change seen only in contact tracking is
  "appears to have left" until someone confirms it; "we don't know who replaces him" is not
  "nobody replaced him". An outreach with no reply is not a conversation.
- **One label per account.** Health bands (healthy, needs attention, at risk) describe the score.
  A risk flag written to the CRM is a different thing: call it "flag as high-risk", never "mark
  red" on an account whose health is not in the red.
- **Honest about gaps.** If a source is not connected, say what we could not see and how it limits
  the conclusion, in one sentence.

## Translation table

| Internal term | Write instead |
|---|---|
| P0 / P1 / P2 / P3 | Act today / This week / Coming up / Room to grow |
| health 60 YELLOW | health 60 out of 100 (needs attention) |
| champion | main contact, the person who drives the product inside the customer |
| exec sponsor (customer side) | the senior executive who backs the purchase |
| internal exec sponsor | our executive assigned to the account |
| multithreading depth 2 | we are in regular contact with only two people there |
| ECRI | the risk of losing a key contact (or leave it out) |
| seat utilization 0.81 | they use 405 of the 500 seats they pay for |
| DAU/MAU | how often active users come back (usually leave it out) |
| TTV, go-live milestone | time to first value; the point where they start using it for real |
| EBR / QBR | business review (the quarterly meeting with their executives) |
| feature-gate hits | times they hit a limit of their current plan |
| `cse_risk_tier = red_<driver>` | flag the account as high-risk (the reason in words) |
| confidence 0.75 or more | high confidence |
| confidence 0.55 to 0.75 | moderate confidence |
| confidence under 0.55 | low confidence (and say what would raise it) |
| renewal outlook likely / at_risk / unlikely / unknown | renewal likely / renewal at risk / renewal unlikely / too early to call |
| scenario full_renewal / right_size / multi_year_expansion | renew as is / renew smaller / renew longer and larger |

### Primary drivers in plain words

| Code | Write instead |
|---|---|
| champion_loss | our main contact left, and nobody has replaced them |
| org_change | a reorganization or new leadership changed who decides |
| onboarding_incomplete | they never fully got started |
| product_gap | the product does not do something they need |
| reliability | the product has been breaking for them |
| support_experience | their support experience has been poor |
| value_perception | they are not sure it is worth what they pay |
| competitive_displacement | a competitor is replacing us |
| relationship_neglect | we have not been in touch enough |
| commercial_dispute | a disagreement over price, terms or billing |
| expansion_opportunity | they are ready to buy more |
| cadence_due | a scheduled review is coming up |
| healthy | nothing is wrong |
| unknown | the cause is not clear yet |
