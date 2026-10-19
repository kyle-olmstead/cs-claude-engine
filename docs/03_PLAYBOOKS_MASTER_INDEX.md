# 03: Playbooks Master Index

> **In plain English.** A playbook is "when X happens, do Y." This is the list of X's the engine watches for (an account turning red, a champion leaving, a renewal approaching, onboarding stalling, a customer outgrowing their plan, a business review coming due) and the Y it does for each: what it produces, who owns the outcome, how fast, and how we know it's finished. The registry table is the whole story; the sections below are the detail.

The registry of every automated loop the engine runs. For each playbook: the trigger predicates the orchestrator evaluates, the prompts it chains, the artifacts it produces, who owns the outcome, the SLA, and the exit condition that closes the loop. Trigger predicates are written in the same pseudo-syntax the orchestrator's `PLAYBOOK_TRIGGERS` table implements; field names are JSON paths into the Customer 360.

Priority order when multiple playbooks fire on one account in one run: **P0 retention → P1 adoption → P2 cadence → P3 expansion**. A red account never receives an expansion play in the same run.

---

## Playbook registry

| ID | Name | Pillar | Priority | Trigger summary | Prompt chain | Long-form doc |
|---|---|---|---|---|---|---|
| `PB-RET-01` | Enterprise at-risk turnaround | Retention | P0 | Health red / sharp drop / champion departed / P1 aged / near renewal + weak | `churn_risk_rca` → `renewal_defense_playbook` (+ `sentiment_analyzer` on fresh verbatims) | `playbooks/enterprise_at_risk_turnaround.md` |
| `PB-RET-02` | Renewal defense (standard) | Retention | P0 | Renewal ≤ 120d and health yellow, or utilization < 0.50 | `renewal_defense_playbook` | this document §B |
| `PB-ADP-01` | TTV acceleration | Adoption | P1 | Onboarding past segment p75 TTV with no milestone | `ttv_acceleration` | this document §C |
| `PB-ADP-02` | Feature depth remediation | Adoption | P1 | Depth below green-median − 0.15, or utilization drift ≤ −0.10 | `feature_depth_audit` | this document §D |
| `PB-CAD-01` | QBR / EBR automation | Cadence | P2 | 30d before due EBR, or renewal ≤ 180d with no EBR in 2 quarters | `feature_depth_audit` → `executive_ebr_generator` | this document §E |
| `PB-EXP-01` | Low-touch digital expansion | Expansion | P3 | Utilization ≥ 0.85 / feature-gate hits / PQL ≥ 70 | `whitespace_expansion_finder` (+ `feature_depth_audit`) | `playbooks/low_touch_digital_expansion.md` |
| `PB-EXP-02` | Enterprise whitespace discovery | Expansion | P3 | Green health + utilization ≥ 0.80 + unowned modules/BUs | `whitespace_expansion_finder` → `executive_ebr_generator` (expansion EBR variant) | this document §F |
| `PB-OPS-01` | Portfolio rebalance note | Capacity | advisory | CSM book > 115% segment target and ≥ 2 red accounts | none (deterministic) | this document §G |

---

## A. `PB-RET-01`: Enterprise at-risk turnaround

Full operating detail lives in `playbooks/enterprise_at_risk_turnaround.md`. Registry entry:

**Trigger (any):**
```
health.band == "red"
OR (health.score_30d_ago - health.score) >= 15
OR relationship.champion.status == "departed" AND relationship.champion.replacement_identified == false
OR exists(support.open_tickets[] where priority == "P1" and age_days > 5)
OR (contract.days_to_renewal <= 120 AND health.score < 65)
OR sentiment.ecri >= 60
```
**Suppression:** not if `PB-RET-01` fired in the last 14 days and its action is still `open`; the orchestrator instead appends a `signal_update` note to the open action.

**Prompt chain:** `retention.churn_risk_rca` → `retention.renewal_defense_playbook`; if any `sentiment.nps_responses[]` or `conversations[]` newer than the last run exist, `core.sentiment_analyzer` runs first and its output is injected as `sentiment.transcript_signals[]`.

**Artifacts:** RCA (`rca.md`), 30-day save plan (`save_plan.md`), executive outreach draft (`comm_exec_outreach.md`, approval required), internal escalation brief (`escalation_brief.md`), CRM: account property `cse_risk_tier`, task "Red account review" to CSM + CS leader, Slack alert to `#cs-red-accounts`.

**Owner / SLA:** CSM owns; CS leader accountable. First customer touch within 72 hours of trigger; save plan approved within 5 business days.

**Exit:** `health.band != "red"` for 30 consecutive days AND (renewal closed-won OR days_to_renewal > 180), OR churn confirmed (logged as outcome).

---

## B. `PB-RET-02`: Renewal defense (standard)

**Trigger:**
```
contract.days_to_renewal <= 120
AND ( health.band == "yellow" OR usage.seat_utilization < 0.50 OR contract.contraction_flag_90d == true )
AND NOT PB-RET-01 fired
```

**Prompt:** `retention.renewal_defense_playbook` with `instruction = "standard renewal defense"`.

**Claude execution (orchestrator does this; shown for operators running ad hoc):**
```bash
python -m src.orchestrator --input feeds/ --account-id <id> --playbook PB-RET-02 --out ./out
```

**Artifacts:**
* `renewal_plan.md`: renewal probability band (not a number but a band, with evidence), the three scenarios (full renew / right-size / multi-year with expansion), the ask of each stakeholder, the dates.
* `comm_renewal_kickoff.md`: draft to economic buyer proposing the renewal review meeting (approval required).
* CRM: renewal opportunity `cse_scenario` property set to the recommended scenario; task "Renewal kickoff meeting" due within 10 days.

**Owner / SLA:** CSM; kickoff meeting held by day 90 pre-renewal.

**Exit:** renewal opportunity `is_closed`.

---

## C. `PB-ADP-01`: TTV acceleration

**Trigger:**
```
lifecycle.stage == "onboarding"
AND lifecycle.days_since_term_start > benchmarks[segment].ttv_p75_days
AND lifecycle.value_milestones_reached == []
```

**Prompt:** `adoption.ttv_acceleration`.

**Artifacts:**
* `ttv_unblock_plan.md`: the blocking step (technical / people / process), the owner on each side, the three next actions with dates, the revised milestone date.
* `comm_onboarding_checkin.md`: draft to the admin/champion (approval required).
* CRM: `onboarding_risk = true`; task to implementation owner.
* If the blocker is classified `technical_integration` the action also opens a support ticket draft tagged `onboarding-blocker`.

**Owner / SLA:** Onboarding/implementation manager; plan within 3 business days.

**Exit:** any primary value milestone reached.

---

## D. `PB-ADP-02`: Feature depth remediation

**Trigger:**
```
health.band != "red"
AND ( usage.feature_depth_30d <= benchmarks[segment].feature_depth_green_median - 0.15
      OR usage.utilization_drift_90d <= -0.10 )
AND contract.days_to_renewal > 120
```

**Prompt:** `adoption.feature_depth_audit`.

**Artifacts:**
* `feature_audit.md`: unused high-lift features ranked by retention lift × fit, with the user persona that should adopt each, and the enablement asset to send.
* `comm_enablement_nudge.md`: one email or in-app message per top-2 feature (approval required for email; in-app nudges are auto-queued to the digital platform with `requires_human_approval=false` only for the digital segment).
* CRM: task "Enablement session: <feature>".

**Owner / SLA:** CSM (enterprise/MM) or digital programs (SMB/digital); 10 business days.

**Exit:** `feature_depth_30d` ≥ trigger threshold + 0.05 for 30 days.

---

## E. `PB-CAD-01`: QBR / EBR automation

**Purpose.** Turn usage data, business outcomes, and ROI into an executive-grade narrative and slide-by-slide script, so the CSM spends their time on the conversation instead of the deck.

**Trigger (any):**
```
cadence.next_ebr_due_at - today <= 30 days
OR ( contract.days_to_renewal <= 180 AND cadence.ebrs_completed_last_2_quarters == 0 )
OR instruction == "generate_ebr"   # on-demand via MCP run_playbook
```

**Prompt chain:** `adoption.feature_depth_audit` (to produce the adoption narrative and the "what's next" section) → `expansion.executive_ebr_generator`.

**Inputs assembled by the orchestrator beyond the Customer 360:**
* `retention_context_json`: the account's segment row from `mart_retention_nrr_grr` (so the deck can say "you are in the top quartile of customers like you").
* `roi_inputs_json`: the account's stated business outcomes from the CRM (`account.business_outcomes[]`: outcome, baseline, current, unit, source) and the ROI model parameters (`loaded_hourly_rate`, `hours_saved_per_workflow`, etc.) maintained by the CS Ops team.
* `benchmarks_json`.

**Claude execution:**
```bash
python -m src.orchestrator --input feeds/ --account-id <id> --playbook PB-CAD-01 --out ./out
# or interactively via MCP:
#   run_playbook({account_id: "...", playbook_id: "PB-CAD-01", dry_run: true})
```

**Artifacts (all written to `out/<account_id>/`):**

| File | Content |
|---|---|
| `ebr_narrative.md` | The one-page executive narrative: where we started, what changed, what it is worth, what is next. Written for a CFO/COO reader. |
| `ebr_script.md` | Slide-by-slide script: for each of 8–10 slides, the title, the single number or claim on the slide, the 60-second talk track, the question to ask the room, and the `source_path` for every number. |
| `ebr_roi_table.md` | ROI table: each business outcome with baseline, current, delta, $ value, confidence, and the formula. Totals with low / base / high cases. |
| `ebr_prework.json` | Structured pre-work for the CSM: the three unknowns to confirm before the meeting, the stakeholder who should attend but is not on the invite, the risk to pre-empt. |
| `comm_ebr_preread.md` | Pre-read email to the exec sponsor (approval required). |
| CRM | `cadence.last_ebr_prepared_at`; task "EBR: <account>" with deck link; opportunity creation *suggested* (not created) if the whitespace section surfaces a qualified play. |

**ROI method the prompt is bound to.** Every $ figure must trace to a `business_outcomes[]` entry or a `roi_inputs` parameter. The prompt may not assume hours saved, headcount avoided, or revenue influenced without an input. Where an outcome is unmeasured the script says so and proposes the measurement, which is itself a value-add in the room.

**Owner / SLA:** CSM; prepared ≥ 7 days before the EBR; pre-read sent ≥ 3 days before.

**Exit:** EBR marked completed in CRM; `ebr_prework.json` unknowns resolved and written back as `account.business_outcomes[]` updates.

**What to measure.** EBR on-time completion rate and CSM prep hours per EBR, before and one quarter after automation. The engine has not yet been run in a production deployment, so there is no measured baseline to quote; the ROI memo (`docs/04_ROI_MEMO.md`) models the expected effect and says how to verify it.

---

## F. `PB-EXP-02`: Enterprise whitespace discovery

**Trigger:**
```
health.band == "green"
AND usage.seat_utilization >= 0.80
AND ( len(whitespace.unowned_modules) > 0 OR len(whitespace.unowned_business_units) > 0 )
AND contract.days_to_renewal > 60
AND NOT exists(opportunities[] where type in ("expansion","upsell","cross_sell") and is_closed == false)
```

**Prompt chain:** `expansion.whitespace_expansion_finder` → `expansion.executive_ebr_generator` with `variant = "expansion"`.

**Artifacts:** `whitespace_brief.md` (ranked plays with sizing, the champion for each, the evidence, the objection to expect); `comm_expansion_exec.md` (approval required); CRM: `expansion_candidate = true`, opportunity *draft* object for the AE/CSM to accept (never auto-created in forecast stages).

**Owner / SLA:** CSM + account AE; qualification call within 15 business days.

**Exit:** expansion opportunity created (any stage) or `expansion_candidate` cleared with reason.

---

## G. `PB-OPS-01`: Portfolio rebalance note (advisory)

Deterministic, no Claude call. Runs once per orchestrator run across the whole feed.

**Trigger:**
```
csm.book_arr > benchmarks[csm.primary_segment].arr_per_csm_target * 1.15
AND count(accounts where csm_owner_id == csm.id and health.band == "red") >= 2
```

**Artifact:** `out/_portfolio/rebalance_<csm_id>.json`: the CSM's book ARR vs. target, the red accounts, and the five lowest-touch green accounts (by `days_since_last_csm_touch` desc, `arr` asc) as transfer candidates. Posted to `#cs-leadership` weekly digest, not daily.

**Owner:** CS leader. Reassignment is a human decision; the engine only surfaces the candidates.

---

## H. Trigger evaluation rules (shared)

1. **Freshness.** A trigger only fires on documents whose `as_of_date` is today or yesterday. Stale feeds raise a drift alarm, not actions.
2. **Suppression window.** Each playbook has a `cooldown_days` (RET-01: 14, RET-02: 30, ADP-01: 7, ADP-02: 21, CAD-01: 60, EXP-01: 30, EXP-02: 45), enforced by `src/triggers.py::evaluate_triggers` via `actions_last_30d[]`. Re-firing inside the window while the action is still open produces a `signal_update` file referencing the open action instead of a new plan. The registry table below is generated from the same code (`registry_table()`) and injected into the orchestrator prompt, so prompt, docs, and code cannot disagree on triggers.
3. **Mutual exclusion.** P0 suppresses P3 on the same account in the same run. P1 and P2 may co-fire.
4. **Confidence floor.** Actions with `confidence < 0.55` have their priority lowered to `P3` by `src/validation.py::enforce_policy` (recorded in `data_quality_flags` as `policy: …`), regardless of what the playbook emitted.
5. **Human override.** A CSM can set `account.cse_opt_out_playbooks[]` in the CRM to suppress specific playbooks (e.g., during a live escalation they are already handling). The orchestrator honors it and logs the suppression.

---

## I. Artifact naming and approval states

All artifacts are written under `out/<account_id>/` with the pattern `<playbook_id>.<artifact>.<ext>`. Communications carry YAML front-matter:

```yaml
---
artifact: comm_exec_outreach
playbook_id: PB-RET-01
account_id: acc_01HZX...
to: [contact_01HZ...]        # CRM contact ids, never raw emails in artifacts
cc: []
subject: "..."
tone: "direct, non-defensive, outcome-focused"
send_after: 2026-10-16
approval_status: pending     # pending | approved | rejected | sent
approved_by: null
---
```

The approval queue reads these headers; nothing with `approval_status: pending` can be sent by any adapter.

---

## J. Playbook lifecycle metrics (tracked in `action_outcomes`)

| Metric | Formula | Target |
|---|---|---|
| Trigger precision | approved actions / fired triggers | ≥ 0.60 |
| Time to first touch | first customer activity after trigger − trigger time | RET-01 ≤ 72h; others ≤ 5 business days |
| Save rate | RET-01 accounts renewed / RET-01 accounts reaching renewal | ≥ 0.65 |
| Expansion conversion | EXP-01/02 actions → closed-won expansion within 120d | ≥ 0.25 |
| TTV lift | p50 TTV for ADP-01 cohort vs. non-triggered cohort | −20% |
| EBR on-time rate | CAD-01 | ≥ 0.80 |
