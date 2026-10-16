# CS-Claude Engine

**An open-source AI Customer Success Operating System.** Claude runs continuously across a CSM's book of business: it reads the warehouse, scores health, diagnoses churn risk, finds expansion whitespace, drafts the next customer touch, and writes every decision back to the CRM as a validated, auditable `PlaybookAction`.

CS-Claude Engine is not a chatbot bolted onto a CRM. It is a closed loop:

```
   warehouse (dbt marts)  ──►  Customer 360 JSON  ──►  Claude (prompt + tool_use)  ──►  PlaybookAction JSON
        ▲                                                                                      │
        │                                                                                      ▼
   outcome log  ◄──────────────  CRM / Slack / Email adapters  ◄──────────────  human approval gate
```

Every stage is typed, versioned, and testable. Claude never free-texts into a CRM field; it emits structured JSON against a schema the orchestrator validates before anything is written.

The engine runs two ways from the same files:

| Mode | Where it runs | Data comes from | Best for |
|---|---|---|---|
| **Plugin mode** | Inside your Claude account (Claude app, Cowork, or Claude Code) as an installed plugin | The connectors you already have — HubSpot/Salesforce, Zendesk, Gong/Zoom, Amplitude, Clay, Slack, Gmail, Drive… | A CSM or CS leader who wants the engine on their own book today, with no infrastructure |
| **Server mode** | A scheduled Python job against your warehouse (`src/orchestrator.py` + dbt marts) | JSONL feeds exported from the marts | CS Ops running the whole customer base daily, with audit logs and CRM write-back |

---

## Install into your Claude account (plugin mode)

The repository is itself a Claude plugin and a one-plugin marketplace. Nobody needs to clone it or set an API key; the plugin uses the connectors already authorized in your Claude account.

**Claude app / Cowork (paid plans):** open *Customize → Plugins*, choose *Add marketplace*, enter `kyle-olmstead/cs-claude-engine`, then add the **cs-engine** plugin from that marketplace. (You can also upload a packaged `cs-engine.plugin` as a custom plugin — build it from the repo root with `zip -r cs-engine.plugin . -x '.git/*'`.)

**Claude Code:**

```
/plugin marketplace add kyle-olmstead/cs-claude-engine
/plugin install cs-engine@cs-engine
```

Then, in any conversation:

```
set up the CS engine
```

The `cs-setup` skill inventories your connectors, maps each to a category the engine needs (CRM, support desk, conversation intelligence, survey tool, product analytics or warehouse, billing, enrichment, chat, email, calendar, documents), confirms the mapping with you, saves it as your *stack profile*, and scores the bundled sample account to prove the install. From then on every skill reads that profile; a missing category is reported as a data-quality flag with its cost in confidence, never silently invented. Full category reference: [`CONNECTORS.md`](CONNECTORS.md). Field-by-field source map: [`skills/customer-360/references/field-sources.md`](skills/customer-360/references/field-sources.md).

**Skills you get:**

| Say… | Skill | What happens |
|---|---|---|
| "set up the CS engine", "what's connected" | `cs-setup` | Connector inventory → stack profile |
| "how healthy is Contoso", "pull the 360 on Contoso" | `customer-360` | Schema-valid Customer 360 from your connectors + explained health score |
| "review my book", "what's at risk", or on a schedule | `book-review` | Prioritized digest across your accounts, P0 first, with the playbook to run |
| "Contoso just went red", "our champion left" | `red-account-turnaround` | Churn RCA → save plan → exec outreach draft (PB-RET-01) |
| "prep the Contoso renewal" | `renewal-defense` | Scenarios, stakeholder asks, dated plan, kickoff draft (PB-RET-02) |
| "Contoso is stuck in onboarding" | `ttv-acceleration` | Blocker diagnosis, owners, milestone date, check-in draft (PB-ADP-01) |
| "what features is Contoso not using" | `feature-depth-audit` | Peer comparison, ranked recommendations, adoption narrative (PB-ADP-02) |
| "where can we expand Contoso" | `expansion-whitespace` | Readiness gate, sized plays, sponsor, objections, sales handoff (PB-EXP-01/02) |
| "prep the Contoso EBR" | `ebr-generator` | Narrative, slide script, ROI table, pre-work, pre-read email (PB-CAD-01) |
| "what's our NRR by segment" | `retention-report` | NRR/GRR/churn decomposition, velocity, ARR per CSM, CRC, LTV:CAC, QBR velocity |

Every skill ends the same way: it shows what it found with evidence paths, then asks which proposed writes you want — CRM property, task, Slack alert, email *draft*, document. Nothing reaches a customer or changes a CRM field until you say so.

---

## What it does

| Pillar | Lagging / Leading | Metrics the engine computes and reasons over |
|---|---|---|
| **Retention & Revenue** | Lagging | NRR, GRR, logo churn, dollar churn, net dollar churn, expansion pipeline velocity |
| **Adoption & Product Health** | Leading | Weighted multi-variable Health Score, Time-to-Value, DAU/MAU stickiness, feature depth & breadth, seat utilization and 90-day drift |
| **Sentiment & Alignment** | Leading | NPS/CSAT qualitative extraction, transcript sentiment, Executive Champion Risk Index, multithreading depth |
| **Capacity & Efficiency** | Operational | ARR per CSM, Customer Retention Cost, LTV:CAC, QBR/EBR completion velocity |

Each metric has a formal definition in [`docs/02_METRICS_TAXONOMY.md`](docs/02_METRICS_TAXONOMY.md), a SQL implementation in [`sql/dbt_marts/`](sql/dbt_marts/), a Python implementation in [`src/models/`](src/models/), and a prompt that teaches Claude how to interpret it in [`prompts/`](prompts/).

---

## The operating loop

1. **Transform** — dbt builds `mart_customer_health_daily` and `mart_retention_nrr_grr` from CRM, billing, telemetry, support, survey, and conversation sources.
2. **Assemble** — `src/orchestrator.py` builds one `Customer360` document per account (validated against `src/schemas/customer_360.json`), enriching stakeholders through Clay and parsing recent call transcripts.
3. **Score** — `src/models/health_score.py` computes the weighted health score with full component-level explainability and hard-gate overrides (champion departed, payment past due, open P1).
4. **Trigger** — the orchestrator evaluates playbook trigger conditions (see [`docs/03_PLAYBOOKS_MASTER_INDEX.md`](docs/03_PLAYBOOKS_MASTER_INDEX.md)) and selects the prompts to run.
5. **Reason** — Claude is called with a cached system prompt, the Customer 360 as context, and a forced tool call whose `input_schema` is `src/schemas/playbook_action.json`. The response is a `PlaybookAction`: diagnosis, evidence, confidence, CRM writes, drafted communications, and tasks.
6. **Act** — validated actions route to adapters (HubSpot, Salesforce, Gainsight, Clay, Slack). Anything that touches a customer or changes a forecast passes through a human approval gate.
7. **Learn** — every action and its outcome (renewed, churned, expanded, no-op) is logged so weights, thresholds, and prompts are recalibrated quarterly.

---

## Repository layout

```
cs-claude-engine/
├── README.md                              ← you are here
├── requirements.txt
├── .claude-plugin/
│   ├── plugin.json                        ← plugin manifest (the repo root is the plugin)
│   └── marketplace.json                   ← one-plugin marketplace so the repo can be added by owner/repo
├── CONNECTORS.md                          ← tool categories (~~crm, ~~support desk, …) and what each unlocks
├── skills/                                ← plugin mode: one skill per workflow, each driving the prompts below
│   ├── cs-setup/                          ← connector inventory → stack profile
│   ├── customer-360/                      ← assembles the 360 from connectors (+ references/field-sources.md, playbook-protocol.md)
│   ├── book-review/                       ← digest across the book; schedulable
│   ├── red-account-turnaround/ · renewal-defense/ · ttv-acceleration/
│   ├── feature-depth-audit/ · expansion-whitespace/ · ebr-generator/
│   └── retention-report/
├── config/
│   └── health_weights.json                ← single source of truth for score weights (exported from dbt vars)
├── docs/
│   ├── 01_ARCHITECTURE.md                 ← layers, data flow, MCP server, deployment, security
│   ├── 02_METRICS_TAXONOMY.md             ← every metric: definition, formula, thresholds, gotchas
│   └── 03_PLAYBOOKS_MASTER_INDEX.md       ← trigger → playbook → prompt → artifact registry (incl. QBR/EBR automation)
├── prompts/
│   ├── core/
│   │   ├── system_csm_orchestrator.prompt ← the agent's standing system prompt
│   │   └── sentiment_analyzer.prompt      ← NPS/CSAT/transcript qualitative extraction
│   ├── retention/
│   │   ├── churn_risk_rca.prompt          ← root-cause analysis for red accounts
│   │   └── renewal_defense_playbook.prompt← renewal save plan generator
│   ├── adoption/
│   │   ├── ttv_acceleration.prompt        ← onboarding accounts behind TTV target
│   │   └── feature_depth_audit.prompt     ← feature adoption vs. segment benchmark
│   └── expansion/
│       ├── whitespace_expansion_finder.prompt ← tier/seat/module whitespace
│       └── executive_ebr_generator.prompt     ← C-suite EBR script and deck outline
├── src/
│   ├── orchestrator.py                    ← anthropic SDK orchestration: feeds → Claude → actions (+ --triggers-only, --offline)
│   ├── validate.py                        ← schema + evidence-integrity + approval-floor validator (used by the skills)
│   ├── models/
│   │   ├── health_score.py                ← weighted health score with explainability
│   │   └── metrics_calculator.py          ← NRR/GRR/churn/velocity/TTV/CRC/LTV:CAC/QBR velocity
│   ├── schemas/
│   │   ├── customer_360.json              ← input contract (JSON Schema 2020-12)
│   │   └── playbook_action.json           ← output contract for every Claude call
│   └── tools/
│       ├── clay_crm_enrichment.py         ← Clay enrichment + HubSpot/Salesforce sync + champion-change detection
│       └── call_transcript_parser.py      ← Gong/Zoom/VTT parsing → Claude sentiment & risk signals
├── sql/
│   └── dbt_marts/
│       ├── mart_customer_health_daily.sql ← daily per-account health components and score
│       └── mart_retention_nrr_grr.sql     ← monthly + trailing-12 NRR/GRR/logo/dollar churn by segment
├── playbooks/
│   ├── enterprise_at_risk_turnaround.md   ← red account turnaround (health drop / champion loss)
│   └── low_touch_digital_expansion.md     ← PLG / digital-tier expansion discovery
└── examples/
    └── sample_customer_360.json           ← a complete, schema-valid Customer 360 for local runs
```

---

## Quickstart (server mode)

### Prerequisites

* Python 3.10+
* An Anthropic API key (`ANTHROPIC_API_KEY`)
* A warehouse with the staging models referenced in `sql/dbt_marts/` (Snowflake, BigQuery, Databricks, Postgres, or Redshift — the SQL is written to the ANSI subset dbt compiles portably, with the two dialect-specific functions isolated and commented)
* Optional: HubSpot private-app token, Salesforce connected-app credentials, Clay webhook URL, Slack bot token

### Install

```bash
git clone https://github.com/kyle-olmstead/cs-claude-engine.git
cd cs-claude-engine
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### Configure

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export CLAUDE_MODEL=claude-sonnet-5-5          # any current Claude model id; override per prompt via its header
export HUBSPOT_ACCESS_TOKEN=pat-na1-...       # optional
export CLAY_WEBHOOK_URL=https://api.clay.com/v3/sources/webhook/...   # optional
export SLACK_BOT_TOKEN=xoxb-...               # optional
export SLACK_ALERT_CHANNEL=#cs-alerts         # optional
export CSE_DRY_RUN=true                       # default: never write to CRM unless explicitly disabled
```

### Run against the bundled example

```bash
# No credentials required:
python -m src.models.health_score examples/sample_customer_360.json      # score + component breakdown + drift check
python -m src.models.metrics_calculator --demo                            # NRR/GRR/churn/velocity/TTV/ECRI/CRC/LTV:CAC/QBR
python -m src.orchestrator --input examples/sample_customer_360.json --offline --out ./out
#   --offline exercises the whole pipeline (validation → triggers → schema-bound actions → files)
#   with a deterministic stub in place of Claude, so CI and demos need no API key.

# With ANTHROPIC_API_KEY set — real Claude reasoning, still no external writes:
python -m src.orchestrator --input examples/sample_customer_360.json --dry-run --out ./out
```

### Run against your warehouse

```bash
# 1. Build the marts
dbt run --select mart_customer_health_daily mart_retention_nrr_grr

# 2. Export today's Customer 360 feed (one JSON object per line) from your warehouse into ./feeds/
#    The orchestrator accepts .json, .jsonl, or a directory of either.

# 3. Orchestrate the whole book
python -m src.orchestrator --input ./feeds/ --csm "Priya Natarajan" --out ./out
```

Outputs land in `./out/<account_id>/<playbook_id>.action.json` plus any drafted communications as `.md`, and a run-level `run_summary.json` listing every alert by priority.

---

## How Claude is used

**One contract, every call.** Every prompt in `prompts/` ends with an `<output_format>` block that points at `src/schemas/playbook_action.json` (or, for the sentiment analyzer, its own embedded schema). The orchestrator calls the Messages API with `tools=[{"name": "emit_playbook_action", "input_schema": <that schema>}]` and `tool_choice={"type": "tool", "name": "emit_playbook_action"}`. Claude cannot return prose; it must return a conforming object. The orchestrator validates with `jsonschema` and rejects anything that fails.

**Prompt files are versioned artifacts.** Each `.prompt` file has a YAML header (`id`, `version`, `model`, `temperature`, `max_tokens`, `variables`, `output_schema`) followed by the system prompt body, written with explicit XML sections:

```
<role>            who Claude is and the standard it is held to
<context>         what the data means, how the business defines its metrics
<inputs>          the exact variables injected, with their shapes
<analysis_steps>  the ordered reasoning Claude must perform before emitting
<guardrails>      what it must never do (invent numbers, promise discounts, contact customers directly, …)
<output_format>   the schema and field-level rules
<examples>        worked example(s) of the expected output
```

**Prompt caching.** The system prompt body and the playbook registry are sent as cached system blocks; only the Customer 360 and the instruction change per account. Across a 300-account book, this cuts input cost by roughly 80%.

**MCP.** The same tool definitions the orchestrator uses are exposed by an MCP server (spec in `docs/01_ARCHITECTURE.md` §6) so a CSM can ask Claude in their IDE, Slack, or desktop app questions like *"why did Acme go yellow this week?"* and get the identical, schema-bound reasoning the batch job uses.

---

## Playbooks

| Playbook | Trigger (any) | Prompts invoked | Primary artifact |
|---|---|---|---|
| **Enterprise at-risk turnaround** | Health < 50; health drop ≥ 15 pts in 30d; champion departed; open P1 > 5 days; renewal ≤ 120d and health < 65 | `churn_risk_rca` → `renewal_defense_playbook` → `sentiment_analyzer` | RCA + 30-day save plan + exec outreach draft + internal escalation brief |
| **Low-touch digital expansion** | Seat utilization ≥ 85%; feature-gate hits ≥ 3 in 14d; PQL score ≥ 70; DAU/MAU ≥ 0.35 | `whitespace_expansion_finder` → `feature_depth_audit` | Expansion brief + in-app/email nudge sequence + sales handoff record |
| **QBR / EBR automation** | 30 days before scheduled EBR; or renewal ≤ 180d and no EBR in 2 quarters | `feature_depth_audit` → `executive_ebr_generator` | Executive narrative + slide-by-slide script + ROI table + pre-read email |
| **TTV acceleration** | Onboarding account past p50 TTV for its segment with no value milestone | `ttv_acceleration` | Unblock plan + milestone owner map + customer check-in draft |

Full trigger logic, SLAs, roles, and exit criteria: [`docs/03_PLAYBOOKS_MASTER_INDEX.md`](docs/03_PLAYBOOKS_MASTER_INDEX.md) and the two long-form playbooks in [`playbooks/`](playbooks/).

---

## Guardrails and human-in-the-loop

* **Dry-run by default.** `CSE_DRY_RUN=true` unless explicitly disabled. Dry runs produce every artifact but write nothing to external systems.
* **Approval gates.** Any action with `requires_human_approval: true` (all customer-facing communications, any forecast or renewal-probability change, any discount or commercial term) is written to the approval queue, never executed.
* **No invented numbers.** Prompts forbid fabrication; every numeric claim in a Claude output must cite a field path in the Customer 360 (`evidence[].source_path`). The orchestrator spot-checks a sample of cited paths against the input document and fails the action if a path does not exist.
* **PII minimization.** Transcripts and survey verbatims are redacted of emails, phone numbers, and payment identifiers before reaching Claude (see `call_transcript_parser.redact_pii`).
* **Idempotent writes.** Every CRM write carries a deterministic `external_id` (`cse:<account_id>:<playbook_id>:<run_date>`) so re-runs update rather than duplicate.
* **Audit trail.** Every Claude request/response pair is logged with prompt id, prompt version, model, token counts, and the SHA-256 of the input document.

---

## Extending

* **Add a metric:** define it in `02_METRICS_TAXONOMY.md`, implement in `metrics_calculator.py` and the relevant mart, add the field to `customer_360.json`, reference it in the prompt that should reason over it.
* **Add a playbook:** register it in `03_PLAYBOOKS_MASTER_INDEX.md`, add the trigger to `orchestrator.PLAYBOOK_TRIGGERS`, write the prompt, add its `playbook_id` to the enum in `playbook_action.json`.
* **Add a CRM:** implement the `CRMAdapter` protocol in `clay_crm_enrichment.py` (`find_contact`, `upsert_contact`, `create_task`, `update_account_properties`).

---

## License

Apache 2.0. Use it, fork it, ship it. If you improve a prompt, the community would love the PR.
