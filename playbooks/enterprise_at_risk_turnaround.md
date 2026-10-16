# Playbook PB-RET-01 — Enterprise At-Risk Turnaround

> **In plain English.** The step-by-step for the first 30 days after an important customer turns red or loses its champion. It says what sets it off, how serious each case is, who does what by when, what the engine hands you (the diagnosis, the plan, the first email), and how the account exits the playbook. If you run a CS team, §2 (severity tiers) and §4 (timeline) are the parts to know by heart.

**Pillar:** Retention · **Priority:** P0 · **Cooldown:** 14 days · **Owner:** CSM (accountable: CS leader) · **Prompt chain:** `retention.churn_risk_rca` → `retention.renewal_defense_playbook` (+ `core.sentiment_analyzer` on new verbatims/transcripts)

This is the playbook that runs when an enterprise or mid-market account turns red, drops sharply, loses its champion, or carries an aged P1 into the renewal window. It is deliberately front-loaded: the first 72 hours determine whether the account is saveable, and the engine's job is to make those 72 hours count by handing the CSM a diagnosis, a plan, and the first customer touch before they have finished their coffee.

---

## 1. Trigger conditions

Any one of the following, evaluated daily against the Customer 360 (`src/orchestrator.py::trig_ret_01`):

| # | Condition | Customer 360 path | Why it matters |
|---|---|---|---|
| T1 | Health band is red | `health.band == "red"` | The composite says the account is already in trouble |
| T2 | Health dropped ≥ 15 points in 30 days | `health.score_30d_ago − health.score ≥ 15` | Velocity of decline predicts churn better than level |
| T3 | Champion departed, no successor | `relationship.champion.status == "departed" AND replacement_identified == false` | 60%+ of enterprise churn in the reference data had a champion change in the prior two quarters |
| T4 | P1 open > 5 days | `support.open_tickets[].priority == "P1" AND age_days > 5` | An aged P1 is an executive-visibility event on the customer side |
| T5 | Renewal ≤ 120 days and health < 65 | `contract.days_to_renewal ≤ 120 AND health.score < 65` | Inside the renewal window with no margin |
| T6 | Executive Champion Risk Index ≥ 60 | `sentiment.ecri ≥ 60` | Composite relationship fragility even without a formal departure |

**Suppression.** If a PB-RET-01 action is `open` from the last 14 days, the engine appends a `signal_update` to it instead of opening a second. If `account.cse_opt_out_playbooks` contains `PB-RET-01`, the trigger is logged and skipped (use this while a live escalation is being handled by hand).

**Mutual exclusion.** PB-RET-01 suppresses PB-RET-02, PB-EXP-01, and PB-EXP-02 on the same account in the same run.

---

## 2. Severity tiers

The RCA output sets `priority` and the renewal plan sets `renewal_outlook`; together they place the account in a tier that determines who is in the room.

| Tier | Definition | Internal escalation | First customer touch by |
|---|---|---|---|
| **Critical** | T3 or T4 fired, or `renewal_outlook.band == "unlikely"`, or ARR ≥ $250k with health red | VP CS + account AE + exec sponsor (internal) in a 30-minute war room within 24h | 48 hours, by the internal exec sponsor or VP CS |
| **High** | Health red, or T2 + T5 | CS leader + AE notified; weekly red-account review | 72 hours, by CSM |
| **Elevated** | T6 only, or T5 with health 55–64 | CS leader notified; tracked in weekly review | 5 business days, by CSM |

---

## 3. Roles

| Role | Responsibility in this playbook |
|---|---|
| **CSM** | Owns the save plan; executes stakeholder asks; keeps the action record current; makes the approve/edit/reject call on every drafted communication |
| **CS leader** | Approves the plan within 5 business days; unblocks internal resources; owns the internal escalation brief |
| **AE / account owner** | Co-owns commercial scenario preparation (inputs only — no terms until the plan is approved); joins exec touches |
| **Internal exec sponsor** | First customer touch for Critical tier; executive-to-executive continuity |
| **Support / engineering** | Named owner and date for any reliability or P1 driver within 24h of the RCA |
| **CS Ops** | Ensures the Customer 360 is complete (enrichment fresh, transcripts parsed) before the RCA runs; monitors trigger precision |

---

## 4. Timeline

```
T+0h    trigger fires in the daily run (or event-driven: champion left_company_at set, P1 opened)
        ├─ sentiment_analyzer runs on any verbatim/transcript newer than the last run
        ├─ churn_risk_rca emits: mechanism, timeline, blast radius, interrupting intervention
        ├─ renewal_defense_playbook emits: scenario, stakeholder asks, dated actions, kickoff draft
        └─ Slack alert to #cs-red-accounts; CRM task "Red account review" created; cse_risk_tier written

T+4h    CSM reads out/<account_id>/PB-RET-01.*: RCA, save plan, draft comms. Edits or rejects drafts.

T+24h   Critical tier: war room held. Named owner for any reliability driver. Exec touch scheduled.

T+48h   Critical tier: first customer touch made (exec-to-exec).
        High tier: CSM has sent the approved continuity / kickoff communication.

T+72h   High tier: first customer conversation held. Disambiguating question asked and answered.
        CSM updates the action with what was learned (log_outcome notes). If the RCA mechanism was wrong,
        re-run the RCA with the new information (`--playbook PB-RET-01`).

T+5d    Save plan approved by CS leader. Stakeholder asks in motion. Measurement tasks assigned for
        unmeasured value-story inputs.

T+14d   First checkpoint: health components re-reviewed; has the dominant signal moved? If the
        interrupting intervention has not landed (no exec meeting, no successor, no engineering date),
        escalate one tier.

T+30d   Second checkpoint: renewal_outlook re-assessed. If still at_risk/unlikely with R ≤ 90, the
        commercial scenario conversation begins (humans, not the engine).

R−60d   Proposal inputs complete. Value review held. EBR (renewal variant) delivered via PB-CAD-01.

R−30d   Verbal. Exit criteria evaluated.
```

---

## 5. Claude execution scripts

The orchestrator runs these automatically. The commands below are for a CSM or CS Ops re-running on demand (for instance after a customer conversation changes the picture).

### 5.1 Full chain for one account

```bash
python -m src.orchestrator \
  --input ./feeds/customer_360.jsonl \
  --account-id acc_01HZXK3V8Q \
  --playbook PB-RET-01 \
  --parse-transcripts \
  --out ./out
```

Produces under `out/acc_01HZXK3V8Q/`:

```
PB-RET-01.churn_risk_rca.action.json          # diagnosis.{summary, primary_driver, timeline[], candidate_drivers[], disambiguating_question}
PB-RET-01.renewal_defense_playbook.action.json # renewal_plan.{recommended_scenario, scenarios[], stakeholder_asks[], value_story_inputs[]}, actions[]
PB-RET-01.comm_1.md                            # continuity / kickoff draft with approval front-matter
```

### 5.2 Interactive, via MCP (Claude desktop / Claude Code)

```
run_playbook({ "account_id": "acc_01HZXK3V8Q", "playbook_id": "PB-RET-01", "dry_run": true })
explain_health({ "account_id": "acc_01HZXK3V8Q" })
draft_communication({ "account_id": "acc_01HZXK3V8Q", "type": "continuity", "recipient_contact_id": "ct_02", "intent": "ask the exec sponsor for a successor and a 30-minute review" })
```

### 5.3 Re-running the RCA after new information

Add the new facts to the Customer 360 feed (a new transcript signal, an updated champion status) and re-run with `--playbook PB-RET-01`. The orchestrator will see the open action and emit a `signal_update` that references it, so the history stays in one record.

### 5.4 What the prompts are told (summary)

* **RCA** is instructed to build a dated timeline from the last 120 days, rank candidate mechanisms by direct evidence and earliest position, name the single interrupting intervention, and ask one disambiguating question when confidence < 0.75. It may emit at most three actions and one communication (continuity note, only when champion_loss and an exec sponsor exists).
* **Renewal defense** inherits the RCA mechanism, evaluates all three scenarios with GRR-dollar impact, builds the stakeholder ask map, sequences actions against the R−120/90/60/45/30/14 anchors, lists value-story inputs and measurements, drafts exactly one kickoff communication, and sets a renewal outlook band. It is forbidden from proposing pricing or terms.

---

## 6. Automated output artifacts

| Artifact | File | Contents | Approval |
|---|---|---|---|
| Root-cause analysis | `PB-RET-01.churn_risk_rca.action.json` → rendered as `rca.md` by the approval UI | Mechanism, timeline, blast radius, revenue at risk, candidate drivers with for/against, interrupting intervention, disambiguating question | n/a (internal) |
| 30-day save plan | `PB-RET-01.renewal_defense_playbook.action.json` → `save_plan.md` | Recommended + fallback scenario, scenario table with GRR impact, stakeholder ask map, sequenced dated actions with owners, value-story inputs and measurements, renewal outlook | CS leader approves within 5 business days |
| Executive outreach draft | `PB-RET-01.comm_1.md` | ≤ 180 words, to a stakeholder in `relationship.stakeholders[]` (never a departed one), one ask | **Required** — CSM or internal exec sponsor |
| Internal escalation brief | generated by the approval UI from the two action files | One page for the war room: what, why, what we need from whom by when | n/a (internal) |
| CRM writes | via adapter (live) or listed in the action (dry run) | `account.cse_risk_tier = red_*`; task "Red account review" (CSM + CS leader); `opportunity.cse_scenario` on the renewal opp | Risk tier: automatic. Scenario: automatic (informational field). Forecast fields: never written by the engine. |
| Slack alert | `#cs-red-accounts` | Priority, account, 400-char summary, confidence, count of items awaiting approval, file name | n/a |

---

## 7. The save conversation — what the CSM does with the output

The engine does not talk to the customer. What it gives the CSM is the ability to walk into the first conversation already knowing:

1. **The mechanism**, so the conversation is about the cause, not the symptom. ("We noticed usage dropped after the March migration" rather than "we noticed usage dropped.")
2. **The disambiguating question**, so the conversation produces the one piece of information that changes the plan.
3. **The counter-evidence**, so the CSM does not over-rotate on risk with a customer who is actually fine in three business units and broken in one.
4. **The ask**, so the conversation ends with a decision: a name, a date, a meeting.

Anti-patterns the engine's output is designed to prevent:

* Leading with a discount. Pricing is never in the plan; the plan is value and relationship first.
* Apologizing for things the data does not show the customer is unhappy about.
* Asking "how are things going?" — the RCA already knows.
* Treating a champion departure as a product problem. It is an ownership vacuum; the fix is a successor and an exec sponsor, not a feature.
* Running three meetings in two weeks with the same stakeholder.

---

## 8. Exit criteria

The action is closed (`log_outcome`) when **either**:

* `health.band != "red"` for 30 consecutive days **and** (renewal closed-won **or** `contract.days_to_renewal > 180`), outcome `renewed` / `no_change`; or
* churn or contraction is confirmed, outcome `churned` / `contracted`, with notes on which mechanism was correct.

Every closed PB-RET-01 action feeds the quarterly recalibration (Architecture §8.2): was the RCA's `primary_driver` right? Did the recommended scenario happen? That is how the prompts get better.

---

## 9. Metrics for this playbook

| Metric | Target | Source |
|---|---|---|
| Time to first customer touch (Critical) | ≤ 48h | `action_outcomes.first_touch_at − emitted_at` |
| Time to first customer touch (High) | ≤ 72h | same |
| Save plan approval lag | ≤ 5 business days | `approved_at − emitted_at` |
| Save rate | ≥ 65% of PB-RET-01 accounts reaching renewal renew (any scenario) | outcomes joined to `mart_retention_nrr_grr` |
| GRR protected | ≥ 80% of ARR at trigger retained at renewal | same |
| RCA driver precision | ≥ 70% of closed actions have `primary_driver` confirmed by CSM notes | outcomes notes |
| Trigger precision | ≥ 60% of fired triggers lead to an approved (not rejected) plan | `action_outcomes` |

---

## 10. Worked example

**Account:** Contoso Logistics · enterprise · ARR $240,000 · 95 days to renewal · health 58 (79 thirty days ago) · champion departed per Clay enrichment (now at Northwind), no successor · multithreading depth 2 · usage healthy (DAU/MAU 0.36, utilization 0.81) · one P2 open 3 days · exec sponsor last engaged 40 days ago.

**Trigger:** T2 (−21 points) and T3 (champion departed).

**RCA (abridged):** primary_driver `champion_loss`; timeline shows the champion's last activity 38 days ago, enrichment mismatch detected 2 days ago, health decline driven entirely by the relationship component (−19 contribution) with adoption flat; blast radius full_account (renewal ownership vacuum, not dissatisfaction); counter-evidence: usage and CSAT are healthy; interrupting intervention: secure the exec sponsor as interim owner and identify the successor before R−60; disambiguating question: "Who inherited the champion's team and budget?"; confidence 0.88.

**Renewal plan (abridged):** recommended `full_renewal`, fallback `multi_year_expansion` (EMEA rollout mentioned in a transcript 50 days ago); stakeholder asks: exec sponsor (continuity meeting, 5 days, email), admin (confirm successor name, 2 days, call), economic buyer (value review at R−60, meeting). Timeline anchor: inside R−120, kickoff compressed to 10 days. Actions: confirm successor (2d), exec continuity meeting request (5d, approval), CRM risk tier write, multithreading task to add two contacts in the champion's function (10d), EBR renewal variant scheduled (14d, via PB-CAD-01). One communication to the exec sponsor, subject "Continuity plan for the Contoso program", 140 words, one ask. Outlook `at_risk`.

**What happened (illustrative, not a customer result):** The exec sponsor named the successor on day 4; the successor had been a power user and was already in the Customer 360 as `end_user`. The CSM ran the EBR on day 21 with the successor and the exec sponsor. Renewed at R−25 as a 2-year with the EMEA module. Outcome logged `expanded`; RCA driver confirmed.
