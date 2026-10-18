# 01 — Architecture

> **In plain English.** How the engine is built, in five layers: where data comes from, how it's cleaned, how the account picture is assembled, how Claude reasons about it, and how actions get back into your tools — plus the feedback loop that keeps the health score honest. If you're not an engineer, read the table in §0 and stop; it tells you the two ways the engine can run and which one you're on.

CS-Claude Engine is a five-layer system. Each layer has a single responsibility, a typed interface to the next, and can be replaced independently. This document specifies every layer, the data contracts between them, the MCP server, the deployment topology, and the security model.

---

## 0. Two runtimes, one engine

The same prompts, schemas, scoring code, and playbook logic run in two environments:

| | **Plugin mode** | **Server mode** |
|---|---|---|
| Runtime | Claude itself, inside a user's Claude account (app, Cowork, or Claude Code), with the repo installed as a plugin | A Python process (`src/orchestrator.py`) on a schedule, calling the Messages API |
| L0 sources | The user's **connectors** (MCP tools for HubSpot/Salesforce, Zendesk, Gong/Zoom, Amplitude, Clay, Slack, Gmail, Drive…) as discovered by the `cs-setup` skill and recorded in the stack profile | ELT into a warehouse |
| L1 transform | None persisted — the `customer-360` skill assembles the document in-session per `skills/customer-360/references/field-sources.md`; history is kept in `cs-engine/accounts/<id>/history/` in the user's working folder | dbt marts |
| L2 assembly | The skill, writing `customer_360.json` and running `health_score.py` + `validate.py` as bundled scripts | The orchestrator |
| L3 intelligence | Claude reasons directly from the prompt files, following the same `<analysis_steps>` and `<guardrails>`; outputs the same `PlaybookAction` schema | Messages API with forced `tool_use` |
| L4 action | Proposed writes presented to the user; executed through the connectors only on approval, in-conversation | Adapters + approval queue |
| L5 feedback | `history/actions.jsonl` per account | `action_outcomes` table |
| Scheduling | A scheduled task in the user's Claude account running the `book-review` skill (digest only, no writes when unattended) | Airflow / cron |

Plugin mode is how an individual CSM adopts the engine in an afternoon with zero infrastructure. Server mode is how CS Ops runs it across thousands of accounts with warehouse-grade history and an audit trail. Teams typically start in plugin mode and graduate the Customer 360 export to the warehouse once the field definitions have settled; the schema is identical, so nothing downstream changes.

The sections below describe server mode in full; where plugin mode differs it is noted inline.

---

## 1. Layer overview

```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│ L0  SOURCES                                                                          │
│   CRM (HubSpot / Salesforce / Gainsight) · Billing (Stripe / Chargebee / NetSuite)   │
│   Product telemetry (Segment / Snowplow / Amplitude) · Support (Zendesk / Intercom)  │
│   Surveys (Delighted / Qualtrics) · Conversations (Gong / Zoom / Chorus) · Clay      │
└───────────────────────────────┬──────────────────────────────────────────────────────┘
                                │ ELT (Fivetran / Airbyte / custom)
┌───────────────────────────────▼──────────────────────────────────────────────────────┐
│ L1  WAREHOUSE + dbt                                                                  │
│   stg_* (1:1 with sources) → int_* (conformed) → mart_customer_health_daily,         │
│   mart_retention_nrr_grr, mart_capacity_csm, mart_stakeholder_graph                  │
└───────────────────────────────┬──────────────────────────────────────────────────────┘
                                │ SELECT … → JSONL feed (one Customer 360 per line)
┌───────────────────────────────▼──────────────────────────────────────────────────────┐
│ L2  ASSEMBLY  (src/orchestrator.py · src/tools/*)                                    │
│   Customer360 builder · schema validation · Clay enrichment · transcript parsing     │
│   · health_score.py recompute · trigger evaluation                                   │
└───────────────────────────────┬──────────────────────────────────────────────────────┘
                                │ system prompt (cached) + Customer360 + forced tool call
┌───────────────────────────────▼──────────────────────────────────────────────────────┐
│ L3  INTELLIGENCE  (prompts/* · Anthropic Messages API · MCP server)                  │
│   Prompt registry · tool_use structured output · PlaybookAction validation           │
└───────────────────────────────┬──────────────────────────────────────────────────────┘
                                │ PlaybookAction JSON
┌───────────────────────────────▼──────────────────────────────────────────────────────┐
│ L4  ACTION  (adapters)                                                               │
│   Approval queue · HubSpot/SFDC/Gainsight writes · Clay pushes · Slack alerts         │
│   · email drafts (never auto-sent) · task creation                                   │
└───────────────────────────────┬──────────────────────────────────────────────────────┘
                                │ outcome events
┌───────────────────────────────▼──────────────────────────────────────────────────────┐
│ L5  FEEDBACK                                                                         │
│   action_outcomes table · prompt eval harness · weight recalibration · drift alarms  │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. L0 — Sources and the canonical identity model

Everything joins on two keys:

| Entity | Canonical key | Source of truth | Resolution rule |
|---|---|---|---|
| Account | `account_id` (CRM company/account id) | CRM | Billing `customer_id` → CRM via `crm_account_id` custom property; telemetry `workspace_id`/`org_id` → CRM via a maintained `int_account_crosswalk` table. Unresolved telemetry orgs are quarantined, never dropped silently. |
| Contact | `contact_id` (CRM contact id) | CRM | Email (lower-cased, plus-tag stripped) is the join key to telemetry users, survey respondents, and transcript participants. Clay enrichment writes back a `clay_person_id`. |

**Required source tables (staging names used by the marts):**

| Staging model | Grain | Key columns |
|---|---|---|
| `stg_crm__accounts` | account | `account_id, account_name, segment, industry, csm_owner_id, created_at` |
| `stg_crm__contacts` | contact | `contact_id, account_id, email, title, seniority, persona, is_champion, is_exec_sponsor, left_company_at` |
| `stg_crm__activities` | activity | `activity_id, account_id, contact_id, activity_type, direction, occurred_at, owner_id` |
| `stg_crm__opportunities` | opportunity | `opportunity_id, account_id, type (new/renewal/expansion), stage, amount, created_at, close_date, is_won, is_closed` |
| `stg_billing__subscriptions` | subscription line | `subscription_id, account_id, product_sku, seats_purchased, mrr, term_start, term_end, status` |
| `int_arr_daily_snapshot` | account × day | `account_id, snapshot_date, arr, seats_purchased, segment, csm_owner_id` |
| `stg_product__daily_usage` | account × user × day | `account_id, user_email, usage_date, sessions, events, minutes_active` |
| `stg_product__feature_events` | event | `account_id, user_email, feature_key, is_core_feature, event_at` |
| `stg_product__value_milestones` | account × milestone | `account_id, milestone_key, reached_at` |
| `stg_support__tickets` | ticket | `ticket_id, account_id, priority (P1–P4), status, created_at, first_response_at, resolved_at, csat_score` |
| `stg_survey__responses` | response | `response_id, account_id, contact_id, survey_type (nps/csat), score, verbatim, responded_at` |
| `stg_conversation__calls` | call | `call_id, account_id, occurred_at, duration_sec, transcript_uri, participants_json` |
| `int_champion_status` | account | `account_id, champion_contact_id, champion_status (active/at_risk/departed/none), champion_last_engaged_at, replacement_identified` |
| `int_csm_cost` | csm × month | `csm_owner_id, month, fully_loaded_cost` |

---

## 3. L1 — Warehouse and dbt

### 3.1 Model layering

* **Staging (`stg_`)**: rename, cast, dedupe, nothing else. One model per source table.
* **Intermediate (`int_`)**: conformed, cross-source joins. `int_arr_daily_snapshot` is the single most important model in the system — every revenue metric derives from it. It must be built as a *daily* snapshot (not month-end only) so that any cohort window can be computed without re-deriving history.
* **Marts (`mart_`)**: consumer-facing, one row per business grain, materialized incrementally.

### 3.2 The two shipped marts

| Mart | Grain | Refresh | Consumers |
|---|---|---|---|
| `mart_customer_health_daily` | account × as_of_date | Daily 03:00 UTC, incremental on `(account_id, as_of_date)` | Customer 360 builder, BI, alerting |
| `mart_retention_nrr_grr` | period_month × segment (incl. `ALL`) | Daily (cheap) — recomputes last 3 months, full refresh monthly | Board reporting, orchestrator context block, EBR generator |

### 3.3 Health score: SQL and Python must agree

`mart_customer_health_daily` computes the health score in SQL for BI and alerting; `src/models/health_score.py` recomputes it in Python inside the orchestrator so Claude's explanation refers to component contributions identical to what the dashboard shows. The weights live in one place — `config/health_weights.json` — and `scripts/sync_health_weights.py --write` copies them into `dbt_project.yml`'s `vars.health_weights` (`--check` runs in CI so the two cannot drift). Two guards enforce agreement:

* `scripts/check_parity.py` rebuilds the scorer's inputs from the latest mart row per account and fails if any score differs by more than 0.5 points. CI runs it after `dbt build` on the bundled seeds (current delta: 0.000 across the three seeded accounts).
* At run time the orchestrator asserts the Python score equals `health.mart_score` within 0.5 and records a `drift_error` on the account otherwise.

### 3.4 The dbt project (`dbt/`)

```
dbt/
├── dbt_project.yml          vars.health_weights, source_database/source_schema
├── profiles.yml             dev = local DuckDB; snowflake / bigquery / postgres templates
├── models/
│   ├── sources.yml          the 14 upstream tables, column by column
│   ├── staging/             14 stg_*/int_* models — the only place raw column names appear
│   └── marts/               mart_customer_health_daily, mart_retention_nrr_grr (+ schema tests)
├── macros/                  median_of, cse_incremental_strategy (date math uses dbt's own cross-db macros)
├── seeds/                   synthetic history for three accounts so the project builds with no warehouse
└── tests/                   singular tests: grain uniqueness, score range, override caps, GRR bounds, cohort identity
```

The marts are written against dbt's cross-database macros (`dbt.dateadd`, `dbt.datediff`, `dbt.last_day`, `dbt.concat`) so one SQL file runs on DuckDB, Snowflake, BigQuery, Postgres/Redshift and Databricks.

### 3.5 Customer 360 feed

The orchestrator does not query the warehouse row-by-row. A single export query (run after the marts) assembles one JSON document per account by joining the marts with the staging tables listed above, and writes JSONL to object storage (`s3://cse-feeds/<run_date>/customer_360.jsonl`). The export query is the only place the JSON shape is constructed; the Python side only validates and consumes.

Portable pattern (Snowflake shown; BigQuery uses `TO_JSON_STRING(STRUCT(...))`, Postgres uses `jsonb_build_object`):

```sql
select object_construct(
  'schema_version', '1.0',
  'as_of_date', h.as_of_date,
  'account', object_construct('account_id', a.account_id, 'name', a.account_name, 'segment', a.segment, ...),
  'health', object_construct('score', h.health_score, 'band', h.health_band, 'score_30d_ago', h.health_score_30d_ago, ...),
  'usage', object_construct('dau_mau_30d', h.dau_mau_30d, 'feature_depth_30d', h.feature_depth_30d, ...),
  ...
) as customer_360
from mart_customer_health_daily h
join stg_crm__accounts a using (account_id)
where h.as_of_date = current_date;
```

---

## 4. L2 — Assembly

`src/orchestrator.py` is the entry point. Its responsibilities, in order:

1. **Load feed** — `.json`, `.jsonl`, or a directory of either. Each document is validated against `src/schemas/customer_360.json`. Invalid documents are written to `out/_rejected/` with the validation error and skipped; the run continues.
2. **Enrich (optional)** — if `CLAY_WEBHOOK_URL` is set and the document's `stakeholders[]` has anyone with `enrichment_stale: true`, push them to Clay and merge the callback results. Champion job-change detection runs here (`clay_crm_enrichment.detect_champion_change`).
3. **Parse conversations (optional)** — any `conversations[]` entry with a `transcript_uri` and no `sentiment` block is parsed by `call_transcript_parser` and the resulting signals are merged into `sentiment.transcript_signals[]`.
4. **Recompute health** — `health_score.compute_health_score` runs; result is compared against the mart's score (drift guard, §3.3) and attached as `health.components[]` for Claude's explainability.
5. **Evaluate triggers** — `PLAYBOOK_TRIGGERS` (a list of `(playbook_id, predicate)` pairs) is evaluated against the document. Multiple playbooks can fire; they are ordered by priority (retention > adoption > expansion > cadence) and de-duplicated against the `actions_last_30d[]` block so the same account is not hammered.
6. **Call Claude** — per fired playbook, build the prompt (§5), call the Messages API, validate the `PlaybookAction`.
7. **Route** — hand each action to `ActionRouter` which writes files in dry-run or calls adapters in live mode.
8. **Summarize** — `run_summary.json` with every action, priority, confidence, and whether it awaits approval.

Concurrency: accounts are independent, so the orchestrator uses a `ThreadPoolExecutor` sized by `CSE_CONCURRENCY` (default 8). Anthropic rate limits are respected via exponential backoff on 429/529 with jitter; the SDK's built-in retry handles transient 5xx.

---

## 5. L3 — Intelligence

### 5.1 Prompt registry (`src/prompts.py`)

`prompts/**/*.prompt` files are loaded at startup. A file is a YAML header between `---` fences followed by the prompt body. The header declares the prompt's **inputs** — every `{{variable}}` the body uses, each with a source spec the orchestrator resolves generically:

```yaml
id: adoption.feature_depth_audit
version: 2.1.0
model: claude-sonnet-5-5
temperature: 0.2
max_tokens: 4096
inputs:
  segment_benchmarks_json: c360:benchmarks|catalog:benchmarks   # dotted path into the 360, else the default catalog
  feature_catalog_json: catalog:feature_catalog                   # a catalog (overridable with --catalogs)
  today: run:today                                                # a run-level value
cache: [system, body]
```

A body that uses an undeclared variable fails at load time, not at API time. Outputs of earlier prompts in a chain are **not** variables; they travel in the user turn (see §5.2) so the rendered body is identical across every account in a segment and is served from the prompt cache.

### 5.2 Request construction (`src/claude_client.py`)

```python
client.messages.create(
    model=prompt.model, max_tokens=prompt.max_tokens, temperature=prompt.temperature,
    system=[
        {"type": "text", "text": orchestrator_system_prompt, "cache_control": {"type": "ephemeral"}},  # includes the generated playbook registry table
        {"type": "text", "text": prompt.body_rendered,       "cache_control": {"type": "ephemeral"}},  # static per segment → cached
    ],
    messages=[{"role": "user", "content":
        "<customer_360>…per-prompt view…</customer_360>\n<prior_outputs>…earlier prompt outputs, keyed by id…</prior_outputs>\n<instruction>…</instruction>"}],
    tools=[{"name": "emit_playbook_action", "input_schema": schema_for(prompt_id)}],   # base schema minus the sub-objects this prompt doesn't own
    tool_choice={"type": "tool", "name": "emit_playbook_action"},
)
```

Three things keep the per-call cost low:

* **Both system blocks are cached.** After the first call for a segment, only the Customer 360 view and the instruction are billed as fresh input.
* **The tool schema is sliced per prompt** (`OWNED_SUBOBJECTS`): the RCA prompt doesn't carry the EBR's ten-slide schema. Typically 45–60% smaller, with measurably fewer constrained-decoding retries.
* **The Customer 360 is sent as a per-prompt view** (`src/views.py`): blocks the prompt never reads are dropped and long lists are capped by relevance, with a `_view_note` saying what was trimmed. Evidence is verified against the view the model saw, so indices stay consistent.

For nightly runs, `--batch` submits every first-stage prompt through the Messages Batches API (half price, no rate-limit tuning) and runs chained second stages synchronously with the first stage's output as `<prior_outputs>`.

### 5.3 Structured output guarantee (`src/validation.py`)

`tool_choice` forces a tool call; the SDK returns a `tool_use` block whose `input` is a dict. The client then:

1. Checks `stop_reason`. A `max_tokens` stop never yields a partial object: the request is retried once with 1.5× headroom and a tightening instruction (prompts carry a "length discipline" block for exactly this).
2. Validates against the sliced JSON Schema (`jsonschema.Draft202012Validator`).
3. Verifies every `evidence[].source_path` resolves inside the view **and that the claimed `value` matches the document's value** (numeric within 1%, strings case-insensitive). A real path with a wrong number is the most plausible hallucination channel; this closes it. More than two unresolvable paths fails the action.
4. Verifies every `communications[].recipient_contact_id` (and cc) is a current stakeholder — present in `relationship.stakeholders[]` and not departed.
5. Feeds failures back once as a `tool_result` with `is_error: true` and the error list; on a second failure the attempts are written to `out/<account_id>/_invalid/` for manual review, as the playbook index promises.
6. Applies the policy floors in code (`enforce_policy`): every communication and every forecast/commercial CRM write → `requires_human_approval: true`; `confidence < 0.55` → priority P3. Each change is recorded in `data_quality_flags` with a `policy:` prefix; free-text fields are never mutated.
7. Attaches provenance: `prompt_id`, `prompt_version`, `model`, `input_sha256`, `request_id`, token usage, `stop_reason`, policy changes.

Cooldowns are enforced before any call: a playbook that fired inside its window and is still open (`actions_last_30d[]`) gets a `signal_update` on the open action rather than a new one (`src/triggers.py`).

### 5.4 Prompt evaluation harness

`evals/` (not shipped in this repo's minimal layout but specified here) holds golden Customer 360 documents with labeled expected outcomes (`expected_primary_action`, `expected_risk_drivers`, `must_cite_paths`). CI runs every prompt against its goldens on every PR that touches `prompts/` and fails if precision on `primary_action` drops below 0.85 or any `must_cite_paths` is missed. Prompt version bumps require a passing eval run.

---

## 6. MCP server

The same capabilities are exposed as an MCP server (`cse-mcp`) so Claude can be used interactively by a CSM from Claude Code, Claude desktop, Slack, or an IDE, with identical reasoning and identical guardrails.

### 6.1 Tools

| Tool | Input | Output | Side effects |
|---|---|---|---|
| `get_customer_360` | `{account_id}` or `{account_name}` | Customer 360 JSON | none |
| `list_book` | `{csm_id?, band?, renewal_within_days?, sort?}` | array of `{account_id, name, arr, health, band, days_to_renewal, open_actions}` | none |
| `explain_health` | `{account_id}` | `health.components[]` with contributions and 30/90-day deltas | none |
| `query_mart` | `{mart, filters, limit}` (allowlisted marts, read-only) | rows | none |
| `run_playbook` | `{account_id, playbook_id, dry_run=true}` | `PlaybookAction` | writes to `out/` only unless `dry_run=false` **and** the caller has the `cse:execute` scope |
| `draft_communication` | `{account_id, type, recipient_contact_id, intent}` | `{subject, body_markdown, tone_notes}` | none — drafts are returned, never sent |
| `create_crm_task` | `{account_id, title, due_date, owner_id, body}` | `{task_id}` | **write** — requires approval scope |
| `log_outcome` | `{action_id, outcome, notes}` | `{ok}` | **write** to `action_outcomes` |

### 6.2 Resources

* `cse://metrics/taxonomy` — the contents of `docs/02_METRICS_TAXONOMY.md`
* `cse://playbooks/index` — the contents of `docs/03_PLAYBOOKS_MASTER_INDEX.md`
* `cse://prompts/{id}` — any registered prompt body, read-only

### 6.3 Authorization

The MCP server authenticates the connecting user and maps them to a `csm_id` and a scope set (`cse:read`, `cse:draft`, `cse:execute`, `cse:admin`). `list_book` and `get_customer_360` are scoped to the user's own book unless they hold `cse:admin`. Every tool call is logged with `user_id`, tool, arguments hash, and result hash.

---

## 7. L4 — Action layer

### 7.1 The approval gate

A `PlaybookAction` contains an array of `actions[]`. Each has `requires_human_approval`. The router's rule set, in priority order:

1. `CSE_DRY_RUN=true` → write everything to `out/`, call no adapter.
2. `requires_human_approval=true` → write to the approval queue (a table or a Slack message with approve/reject buttons). Nothing executes until an approver with scope acts. Approval payloads carry the action's SHA-256; a modified action requires re-approval.
3. Everything else → execute via the adapter, idempotently.

Actions that are **always** `requires_human_approval=true` regardless of what Claude emits (enforced in `ActionRouter`, not trusted from the model): any `communication` with `send: true`, any `crm_write` to a forecast / renewal probability / contract field, any `commercial_term`.

### 7.2 Adapters

All adapters implement:

```python
class CRMAdapter(Protocol):
    def find_contact(self, email: str) -> Optional[dict]: ...
    def upsert_contact(self, contact: dict, external_id: str) -> str: ...
    def update_account_properties(self, account_id: str, props: dict, external_id: str) -> None: ...
    def create_task(self, account_id: str, task: dict, external_id: str) -> str: ...
```

`external_id` is `cse:<account_id>:<playbook_id>:<prompt_short_name>:<run_date>[:<n>]`. HubSpot stores it in a custom property `cse_external_id`; Salesforce in an External ID field; Gainsight in the CTA's `externalId`. Re-running the same day updates in place.

### 7.3 Communications

Claude drafts; humans send. `communication` actions produce a `.md` file with YAML front-matter (`to`, `cc`, `subject`, `tone`, `send_after`, `approval_status: pending`) and the body. An optional Gmail/Outlook adapter can create a *draft* in the CSM's mailbox. There is no code path that sends email.

---

## 8. L5 — Feedback

### 8.1 Outcome logging

`action_outcomes(action_id, account_id, playbook_id, prompt_id, prompt_version, emitted_at, approved_at, executed_at, outcome, outcome_at, notes)` where `outcome ∈ {renewed, churned, expanded, contracted, no_change, superseded, rejected}`.

### 8.2 Recalibration

Quarterly, a notebook joins `action_outcomes` to `mart_retention_nrr_grr` and `mart_customer_health_daily` and answers:

* **Health score calibration** — for accounts scored red 90 days before renewal, what fraction churned? Target: red cohort churn ≥ 3× green cohort churn. If not, component weights are re-fit by logistic regression on the trailing 4 quarters and proposed as a PR to `dbt_project.yml`.
* **Trigger precision** — for each playbook, what share of fired triggers led to an action the CSM approved (not rejected)? Triggers below 40% approval are tightened.
* **Prompt drift** — eval harness scores by prompt version over time.

### 8.3 Drift alarms

Daily checks, posted to `#cse-ops` on failure:

* Health score SQL vs Python disagreement > 0.5 pts on > 1% of accounts.
* Customer 360 schema validation failure rate > 2%.
* Claude validation-retry rate > 10%.
* Any account with `arr > 0` missing from the feed for 2 consecutive days.

---

## 9. Deployment

```
                ┌──────────────┐  03:00 UTC   ┌──────────────┐  04:00 UTC  ┌───────────────────┐
  Airflow /     │  dbt run     │ ───────────► │ export feed  │ ──────────► │ orchestrator run  │
  Prefect /     │  (marts)     │              │ (JSONL → S3) │             │ (K8s Job / ECS)   │
  GitHub Actions└──────────────┘              └──────────────┘             └─────────┬─────────┘
                                                                                     │
          event-driven (webhooks):                                                   ▼
          · CRM contact left_company_at set  ──► run_playbook(enterprise_at_risk)  out/ · approval queue
          · Support P1 opened                ──► run_playbook(enterprise_at_risk)       · Slack · CRM
          · Clay enrichment callback         ──► detect_champion_change
          · Call transcript ready            ──► call_transcript_parser → sentiment merge
```

* **Batch**: one orchestrator run per day per region. 300 accounts × ~2.5 prompts each ≈ 750 Claude calls; wall time ≈ 12 minutes at concurrency 8.
* **Event-driven**: a thin FastAPI service receives webhooks and enqueues single-account runs. Same code path (`orchestrator.run_account`).
* **Secrets**: injected from the platform's secret store; never in the repo, never in prompts.
* **Observability**: structured JSON logs; OpenTelemetry spans per account and per Claude call; metrics `cse_actions_emitted_total{playbook,priority}`, `cse_claude_latency_seconds`, `cse_validation_failures_total{prompt}`.

---

## 10. Security and privacy

| Concern | Control |
|---|---|
| PII in prompts | `redact_pii()` strips emails, phones, card-like numbers, SSN-like patterns from transcripts and verbatims. Contact names are retained (necessary for stakeholder reasoning); emails are replaced by stable hashes so joins still work. |
| Data residency | Feed, outputs, and logs stay in the customer's cloud account. Only the Customer 360 payload transits to the Anthropic API. |
| Prompt injection | Customer-authored text (verbatims, transcripts, ticket bodies) is wrapped in `<untrusted_customer_text>` tags; the system prompt instructs Claude to treat its contents as data. The orchestrator additionally strips anything matching `</?(system|instruction|tool)` from untrusted fields. |
| Least privilege | CRM tokens are scoped to the objects/fields in the adapter allowlist. The batch job has no email-send scope at all. |
| Auditability | Every Claude call: prompt id/version, model, input SHA-256, request id, usage. Every CRM write: external_id, payload hash, approver. Retained 24 months. |
| Model output trust | Nothing from Claude is executed without schema validation + evidence integrity + adapter allowlist. `requires_human_approval` floors are enforced in code, not in the prompt. |

---

## 11. Non-goals

* The engine does not replace the CSM's judgment; it compresses the time from signal to decision.
* It does not send customer communications autonomously.
* It does not own the forecast; it produces evidence the forecast owner uses.
