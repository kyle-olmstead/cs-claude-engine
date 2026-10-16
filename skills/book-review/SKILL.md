---
name: book-review
description: >
  This skill should be used when the user says "review my book", "book review", "what's at
  risk in my book", "which accounts need attention", "run the engine across my accounts",
  "daily CS digest", "morning CS rundown", "what changed in my book", "who's up for renewal",
  "portfolio health", or when scheduled as a recurring task. It walks the user's book from the
  CRM, builds or refreshes a lightweight Customer 360 per account, scores health, evaluates
  every playbook trigger, and returns a prioritized digest — P0 retention first — with one-line
  reasons and the playbook to run, plus portfolio capacity notes. It runs full playbooks only
  on request or when the user has pre-approved them for a schedule.
metadata:
  version: "1.1.0"
  playbook_id: "BOOK"
---

# Book review

The engine's daily loop, run inside Claude. Produces the digest; runs playbooks only when asked.

## Step 1 — Scope the book

Read `cs-engine/stack-profile.md`. Resolve "my book" as accounts in `~~crm` owned by the operator's `crm_owner_id` (ask once if unknown). Accept a narrower scope when the user gives one ("enterprise only", "renewing this quarter", "the ten biggest"). Cap a single run at 40 accounts; for larger books, run by segment or ARR tier and say so — a digest that takes an hour is not a digest.

## Step 2 — Tier 0: score everything from the CRM alone (1–3 calls)

List the book's accounts with their properties in as few calls as the CRM allows: ARR, renewal date, seats,
owner, champion/decision-maker flags, last activity date, contraction flags, open renewal opportunity. Build a
**provisional** Customer 360 for each with only `account`, `contract`, `relationship` (from CRM contacts),
`opportunities`, `cadence`, `lifecycle`, and `actions_last_30d`; every other block gets its "unavailable"
default and flag from `field-sources.md`. Score and evaluate triggers on these:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/src/orchestrator.py --input cs-engine/accounts/ --triggers-only --out cs-engine/runs/<today>
```

(`--input` accepts a directory; it reads every `customer_360.json` beneath it.) This pass is seconds, not minutes.
Reuse any `customer_360.json` less than one day old instead of rebuilding it.

## Step 2b — Tier 1: deep pull only where it matters

For accounts that fired any trigger at Tier 0, or are inside 120 days of renewal, or are in the top 10 by ARR,
pull `usage`, `support`, and `sentiment` from their connectors (per `field-sources.md`) and re-score. Everything
else stays at Tier 0 and is labeled **CRM-only score** in the digest. Never deep-pull more than 15 accounts in
one run; say when the cap was hit and which accounts were left at Tier 0.

Without Python, score and evaluate by hand using `docs/02_METRICS_TAXONOMY.md` §B1 and
`docs/03_PLAYBOOKS_MASTER_INDEX.md` §H, and say so.

## Step 3 — Portfolio notes

Compute with `src/models/metrics_calculator.py` (or by hand): book ARR, ARR-weighted health, band counts, renewals in 30/60/90/120 days with ARR, accounts over 85% utilization (expansion-ready) and under 50% (contraction risk), QBR/EBR due in 30 days, and the capacity flag (book > 115% of the segment target with ≥ 2 red accounts) per `docs/02_METRICS_TAXONOMY.md` §D1. When `~~data warehouse` exposes `mart_retention_nrr_grr`, add the segment's TTM NRR/GRR.

## Step 4 — The digest

Write `cs-engine/runs/<today>/digest.md` and reply with it, in this order, each item one line:

1. **P0 — act today**: red accounts, champion departures, aged P1s, ECRI ≥ 60, renewals ≤ 120d with health < 65. `<account> · $ARR · health <score> (<delta>) · <reason> · → red-account-turnaround`
2. **P1 — this week**: TTV stalls, feature-depth erosion, standard renewal defense.
3. **P2 — cadence**: EBRs due in 30 days.
4. **P3 — expansion-ready**: utilization ≥ 85%, gate hits, PQL, with indicative size when obvious.
5. **Changes since last run**: band transitions, new tickets, champion status changes (diff against the previous `runs/<date>/digest.json`).
6. **Portfolio**: the numbers from step 3 in one short block.
7. **Data gaps**: connectors missing and how many accounts are reduced-confidence because of it.

Then one `AskUserQuestion` (multi-select): which flagged accounts to run the full playbook on now. Run only the selected ones, each through its skill. If the stack profile records pre-approved playbooks for scheduled runs, run those automatically for P0 items only and leave the rest as the digest.

## Scheduling

If the user wants this daily or weekly, set it up as a scheduled task with this skill as the instruction ("run the cs-claude-engine book review for <operator>, digest only, post to <channel> if ~~chat is connected"). In a scheduled run with nobody present: never execute CRM writes or communications; write the digest, post it to ~~chat when permitted, and stop.

## Rules

- A digest line is one line. The playbook skills carry the detail.
- Never rank by ARR alone; rank by priority, then ARR within priority.
- Keep connector calls proportionate to the book: batch reads where the CRM allows (list companies with properties in one call; list open tickets filtered by account ids in one call).
- Save `runs/<today>/digest.json` (machine-readable: per-account score, band, fired playbooks, reasons) for the next run's diff.
