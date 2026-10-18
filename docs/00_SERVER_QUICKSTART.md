# 00 — Server mode: quickstart and technical overview

> **In plain English.** Plugin mode (the README) runs the engine inside one person's Claude account using their connectors. Server mode runs the *same* engine as a scheduled job against your data warehouse — every account, every night, with history and an audit log — and writes results back to the CRM through the same approval rules. It needs an engineer and takes one to two weeks. This page is the install guide and the technical overview for that path. If you're not setting up server mode, you don't need it.

---

## Prerequisites

* Python 3.10+
* An Anthropic API key (`ANTHROPIC_API_KEY`) — for live runs only; everything below up to "Run against your warehouse" works without one
* For your own data: a warehouse dbt supports (Snowflake, BigQuery, Databricks, Postgres, Redshift) with your CRM, billing, product, support, survey and call data landed by your ELT tool
* Optional: HubSpot private-app token, Salesforce connected-app credentials, Clay webhook URL, Slack bot token

## Install

```bash
git clone https://github.com/kyle-olmstead/cs-claude-engine.git
cd cs-claude-engine
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt dbt-duckdb        # dbt-duckdb is for the local run; add dbt-snowflake / dbt-bigquery / dbt-postgres for yours
```

## Two minutes: the whole pipeline on your laptop, no warehouse

The repo ships a complete dbt project (`dbt/`) with the fourteen upstream tables as **seeds** — a synthetic history for three accounts, including the sample account from `examples/`. It builds on DuckDB, runs the marts and their tests, and the parity script proves the SQL health score and the Python health score agree to the cent.

```bash
cd dbt
DBT_PROFILES_DIR=. dbt seed --quiet                         # load the 14 seed tables into dev.duckdb
DBT_PROFILES_DIR=. dbt build --exclude resource_type:seed   # 18 models + 14 tests
cd ..
python scripts/check_parity.py                             # SQL ↔ Python health score, per account
```

Expected: `PASS=32`, then a parity table ending in `PARITY OK`. You now have `dbt/dev.duckdb` with `mart_customer_health_daily` (850 account-days) and `mart_retention_nrr_grr` to query.

## Configure

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export CLAUDE_MODEL=claude-sonnet-5-5          # any current Claude model id; prompt headers may override
export HUBSPOT_ACCESS_TOKEN=pat-na1-...       # optional
export CLAY_WEBHOOK_URL=https://api.clay.com/v3/sources/webhook/...   # optional
export SLACK_BOT_TOKEN=xoxb-...               # optional
export SLACK_ALERT_CHANNEL=#cs-alerts         # optional
export CSE_DRY_RUN=true                       # default: never write to CRM unless explicitly disabled
```
A `.env` file in the repo root is loaded automatically.

If the engine will write back to HubSpot, create these custom properties first — four text properties on **Company** (`cse_risk_tier`, `expansion_candidate`, `onboarding_risk_tier`, `cse_last_playbook`), one on Company and one on Task for idempotency (`cse_external_id`), and a date property `cse_last_playbook_at` on Company. Salesforce equivalents are external-id fields `CSE_External_Id__c` on Account, Contact, and Task.

## Run against the bundled example

```bash
# No credentials required:
python -m src.models.health_score examples/sample_customer_360.json      # score + component breakdown + drift check
python -m src.models.metrics_calculator --demo                            # NRR/GRR/churn/velocity/TTV/ECRI/CRC/LTV:CAC/QBR
python -m src.orchestrator --input examples/sample_customer_360.json --offline --out ./out
#   --offline exercises the whole pipeline (validation → triggers → schema-bound actions → files)
#   with a deterministic stub in place of Claude, so CI and demos need no API key.
python -m src.orchestrator --input examples/sample_customer_360.json --triggers-only --out ./out
#   --triggers-only scores every account and reports which playbooks would fire, nothing else.

# With ANTHROPIC_API_KEY set — real Claude reasoning, still no external writes:
python -m src.orchestrator --input examples/sample_customer_360.json --dry-run --out ./out
```

## Run against your warehouse

Pointing the project at real data is three edits, all in `dbt/`:

1. **Profile** — add your warehouse target to `dbt/profiles.yml` (templates for Snowflake, BigQuery and Postgres are already there, reading credentials from env vars) and run with `--target <name>`.
2. **Sources** — in `dbt/models/sources.yml`, set the dbt vars `source_database` / `source_schema` to where your ELT lands the raw tables, and change each table's `identifier` to your table name. The column names each staging model expects are documented there; if yours differ, rename inside the matching `dbt/models/staging/stg_*.sql` — that is the only place source column names appear.
3. **Weights** — `config/health_weights.json` is the single source of truth; `python scripts/sync_health_weights.py --write` copies it into `dbt_project.yml`, and `--check` runs in CI so the two can never drift.

```bash
# 1. Build the marts against your warehouse
cd dbt && DBT_PROFILES_DIR=. dbt build --exclude resource_type:seed --target snowflake && cd ..
python scripts/check_parity.py --jsonl <latest mart rows exported as JSONL>   # or extend the script with your warehouse client

# 2. Export today's Customer 360 feed (one JSON object per line) from your warehouse into ./feeds/
#    The orchestrator accepts .json, .jsonl, a directory of either, or a directory of accounts/<id>/customer_360.json.

# 3. Orchestrate the whole book
python -m src.orchestrator --input ./feeds/ --csm "Priya Natarajan" --out ./out

# 4. Nightly: the same run through the Messages Batches API (half price, no rate-limit tuning)
python -m src.orchestrator --input ./feeds/ --csm "Priya Natarajan" --out ./out --batch

# 5. Your own catalogs (feature catalog with your retention lifts, price book, value milestones, ROI inputs by account id,
#    retention context by segment, benchmarks by segment) — a single JSON file overriding the defaults in src/catalogs.py
python -m src.orchestrator --input ./feeds/ --out ./out --catalogs config/catalogs.json
```

### Verify

```bash
pip install -r requirements-dev.txt
pytest -q          # schemas, golden health score, triggers, prompt rendering, validation + policy floors, mocked live path, CLI runs
```

Outputs land in `./out/<account_id>/<playbook_id>.<prompt>.action.json` plus any drafted communications as `.md`, and a run-level `run_summary.json` listing every alert by priority.

---

## The operating loop

1. **Transform** — dbt builds `mart_customer_health_daily` and `mart_retention_nrr_grr` from CRM, billing, telemetry, support, survey, and conversation sources.
2. **Assemble** — `src/orchestrator.py` builds one `Customer360` document per account (validated against `src/schemas/customer_360.json`), enriching stakeholders through Clay and parsing recent call transcripts.
3. **Score** — `src/models/health_score.py` computes the weighted health score with full component-level explainability and hard-gate overrides (champion departed, payment past due, open P1).
4. **Trigger** — the orchestrator evaluates playbook trigger conditions (`docs/03_PLAYBOOKS_MASTER_INDEX.md`) and selects the prompts to run.
5. **Reason** — Claude is called with a cached system prompt, the Customer 360 as context, and a forced tool call whose `input_schema` is `src/schemas/playbook_action.json`. The response is a `PlaybookAction`: diagnosis, evidence, confidence, CRM writes, drafted communications, and tasks.
6. **Act** — validated actions route to adapters (HubSpot, Salesforce, Gainsight, Clay, Slack). Anything that touches a customer or changes a forecast passes through a human approval gate.
7. **Learn** — every action and its outcome (renewed, churned, expanded, no-op) is logged so weights, thresholds, and prompts are recalibrated quarterly.

---

## Module map

| Module | Responsibility |
|---|---|
| `src/orchestrator.py` | Wiring and CLI: feed → prepare → triggers → views → client → router; `--offline`, `--triggers-only`, `--batch` |
| `src/prompts.py` | Prompt registry; YAML headers with declared `inputs:`; rendering |
| `src/claude_client.py` | Cached system + body blocks, per-prompt schema slicing, truncation-safe retries, Batches API |
| `src/validation.py` | Schema, evidence paths **and values**, recipient safety, policy floors, cooldowns |
| `src/views.py` | Per-prompt Customer 360 views (drop unused blocks, cap long lists by relevance) |
| `src/triggers.py` | The playbook registry: triggers, precedence, cooldowns; generates the registry table for the system prompt |
| `src/router.py` | Policy floors → files → approval queue / adapters (live mode) |
| `src/catalogs.py` | Default benchmarks, feature catalog, price book, value milestones, ROI inputs |
| `src/testing.py` | `OfflineEmitter` — deterministic stand-in for Claude |
| `src/validate.py` | CLI the plugin skills call |
| `src/models/` | `health_score.py`, `metrics_calculator.py` |
| `src/tools/` | Clay enrichment + CRM adapters; transcript parser |

## How Claude is used

**One contract, every call.** Every prompt in `prompts/` ends with an `<output_format>` block that points at `src/schemas/playbook_action.json` (or, for the sentiment analyzer, its own embedded schema). The orchestrator calls the Messages API with `tools=[{"name": "emit_playbook_action", "input_schema": <that schema>}]` and `tool_choice={"type": "tool", "name": "emit_playbook_action"}`. Claude cannot return prose; it must return a conforming object. The client validates with `jsonschema`, resolves every cited evidence path against the input document **and checks the claimed value matches**, verifies communication recipients are current stakeholders, and rejects anything that fails — once with the errors fed back for a retry, then to `out/<account>/_invalid/` for manual review. A truncated response (`stop_reason: max_tokens`) is never accepted as a partial object.

**Prompt files are versioned artifacts.** Each `.prompt` file has a YAML header (`id`, `version`, `model`, `temperature`, `max_tokens`, `variables`, `output_schema`, `description`) followed by the system prompt body, written with explicit XML sections:

```
<role>            who Claude is and the standard it is held to
<context>         what the data means, how the business defines its metrics
<inputs>          the exact variables injected, with their shapes
<analysis_steps>  the ordered reasoning Claude must perform before emitting
<guardrails>      what it must never do (invent numbers, promise discounts, contact customers directly, …)
<output_format>   the schema and field-level rules
<examples>        worked example(s) of the expected output
```

**Prompt caching.** The orchestrator system prompt and the playbook registry are sent as cached system blocks; only the Customer 360 and the instruction change per account. Across a 300-account book this cuts input cost by roughly 80%.

**Plugin mode uses the same files.** The skills in `skills/` read the same prompt files and schemas and run the same `health_score.py` and `validate.py`; only the data source (connectors vs. warehouse) and the execution surface (a conversation vs. a batch job) differ. See `docs/01_ARCHITECTURE.md` §0.

---

## Playbooks

| Playbook | Trigger (any) | Prompts invoked | Primary artifact |
|---|---|---|---|
| **Enterprise at-risk turnaround** (PB-RET-01) | Health red; drop ≥ 15 pts in 30d; champion departed; open P1 > 5 days; renewal ≤ 120d and health < 65; ECRI ≥ 60 | `churn_risk_rca` → `renewal_defense_playbook` (+ `sentiment_analyzer`) | RCA + 30-day save plan + exec outreach draft + internal escalation brief |
| **Renewal defense** (PB-RET-02) | Renewal ≤ 120d and yellow / utilization < 50% / contraction | `renewal_defense_playbook` | Scenario plan + kickoff draft |
| **TTV acceleration** (PB-ADP-01) | Onboarding past segment p75 TTV with no value milestone | `ttv_acceleration` | Unblock plan + check-in draft |
| **Feature depth remediation** (PB-ADP-02) | Depth below green median − 0.15, or utilization drift ≤ −10 pts | `feature_depth_audit` | Ranked enablement plan + narrative |
| **QBR / EBR automation** (PB-CAD-01) | 30 days before scheduled EBR; or renewal ≤ 180d with no EBR in 2 quarters | `feature_depth_audit` → `executive_ebr_generator` | Narrative + slide script + ROI table + pre-read email |
| **Low-touch digital expansion** (PB-EXP-01) | Utilization ≥ 85%; gate hits ≥ 3 in 14d; PQL ≥ 70; DAU/MAU ≥ 0.35 | `whitespace_expansion_finder` | Expansion brief + nudge copy + sales handoff |
| **Enterprise whitespace** (PB-EXP-02) | Green, utilization ≥ 80%, whitespace present, no open expansion opp | `whitespace_expansion_finder` → `executive_ebr_generator` (expansion variant) | Whitespace brief + expansion EBR |

Full trigger logic, SLAs, roles, and exit criteria: `docs/03_PLAYBOOKS_MASTER_INDEX.md` and the two long-form playbooks in `playbooks/`.

---

## Guardrails and human-in-the-loop

* **Dry-run by default.** `CSE_DRY_RUN=true` unless explicitly disabled. Dry runs produce every artifact but write nothing to external systems.
* **Approval gates.** Any action with `requires_human_approval: true` (all customer-facing communications, any forecast or renewal-probability change, any discount or commercial term) is written to the approval queue, never executed. The floors are enforced in code (`enforce_approval_floors`), not trusted from the model.
* **No invented numbers.** Prompts forbid fabrication; every numeric claim in a Claude output must cite a field path in the Customer 360 (`evidence[].source_path`). The orchestrator resolves every cited path against the input document and fails the action when more than two do not exist.
* **PII minimization.** Transcripts and survey verbatims are redacted of emails, phone numbers, and payment identifiers before reaching Claude (`call_transcript_parser.redact_pii`); contacts carry email hashes, never raw emails.
* **Prompt-injection handling.** Customer-authored text is wrapped in `<untrusted_customer_text>` tags and scrubbed of tag-like instructions; the prompts treat its contents as data.
* **Idempotent writes.** Every CRM write carries a deterministic `external_id` (`cse:<account_id>:<playbook_id>:<prompt_short_name>:<run_date>[:n]`) so re-runs update rather than duplicate.
* **Audit trail.** Every Claude request/response pair is logged with prompt id, prompt version, model, token counts, and the SHA-256 of the input document.

---

## Extending

* **Add a metric:** define it in `docs/02_METRICS_TAXONOMY.md`, implement in `src/models/metrics_calculator.py` and the relevant mart, add the field to `src/schemas/customer_360.json`, map its source in `skills/customer-360/references/field-sources.md`, reference it in the prompt that should reason over it.
* **Add a playbook:** register it in `docs/03_PLAYBOOKS_MASTER_INDEX.md`, add the trigger to `orchestrator.PLAYBOOK_TRIGGERS`, write the prompt, add its `playbook_id` to the enum in `playbook_action.json`, and add a skill under `skills/` that follows `skills/customer-360/references/playbook-protocol.md`.
* **Add a CRM:** implement the `CRMAdapter` protocol in `src/tools/clay_crm_enrichment.py` (`find_contact`, `upsert_contact`, `create_task`, `update_account_properties`). Plugin mode needs no adapter — it uses whatever connector is present.
