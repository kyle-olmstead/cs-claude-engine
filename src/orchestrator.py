"""
CS-Claude Engine orchestrator.

Feeds (Customer 360 JSON/JSONL) → validation → enrichment → health recompute → trigger
evaluation → Claude (forced tool_use, schema-bound) → PlaybookAction validation →
evidence integrity check → routing (dry-run files, approval queue, CRM/Slack adapters).

    python -m src.orchestrator --input examples/sample_customer_360.json --dry-run --out ./out
    python -m src.orchestrator --input ./feeds/ --csm "Priya Natarajan" --out ./out
    python -m src.orchestrator --input examples/sample_customer_360.json --offline --out ./out   # no API key needed

Environment:
    ANTHROPIC_API_KEY      required unless --offline
    CLAUDE_MODEL           default model id (prompt headers may override)
    CSE_DRY_RUN            "true" (default) → no external writes
    CSE_CONCURRENCY        default 8
    HUBSPOT_ACCESS_TOKEN   optional, enables HubSpot adapter in live mode
    SLACK_BOT_TOKEN / SLACK_ALERT_CHANNEL  optional, enables Slack alerts in live mode
    CLAY_WEBHOOK_URL       optional, enables stakeholder enrichment
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

try:
    import jsonschema
except ImportError:  # pragma: no cover
    jsonschema = None  # validated lazily with a clear error

from src.models.health_score import (
    HealthScoreDriftError,
    HealthWeights,
    assert_no_drift,
    attach_to_customer_360,
    compute_health_score,
)

log = logging.getLogger("cse.orchestrator")

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "src" / "schemas"
PROMPT_DIR = ROOT / "prompts"

DEFAULT_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5")

# --------------------------------------------------------------------------------------
# Benchmarks (overwrite from the warehouse quarterly; see docs/02 Part E)
# --------------------------------------------------------------------------------------

DEFAULT_BENCHMARKS: Dict[str, Dict[str, Any]] = {
    "enterprise":  {"grr_ttm": 0.92, "nrr_ttm": 1.18, "health_green_median": 82, "dau_mau": 0.38, "feature_depth_green_median": 0.62, "seat_utilization": 0.78, "ttv_p50_days": 45, "ttv_p75_days": 70, "multithread_depth": 4, "ecri_median": 28, "arr_per_csm_target": 6_500_000, "power_user_ratio_green_median": 0.30},
    "mid_market":  {"grr_ttm": 0.88, "nrr_ttm": 1.10, "health_green_median": 80, "dau_mau": 0.32, "feature_depth_green_median": 0.55, "seat_utilization": 0.74, "ttv_p50_days": 21, "ttv_p75_days": 35, "multithread_depth": 3, "ecri_median": 32, "arr_per_csm_target": 3_000_000, "power_user_ratio_green_median": 0.25},
    "smb":         {"grr_ttm": 0.80, "nrr_ttm": 1.02, "health_green_median": 78, "dau_mau": 0.28, "feature_depth_green_median": 0.48, "seat_utilization": 0.70, "ttv_p50_days": 10, "ttv_p75_days": 18, "multithread_depth": 2, "ecri_median": 38, "arr_per_csm_target": 4_500_000, "power_user_ratio_green_median": 0.20},
    "digital":     {"grr_ttm": 0.75, "nrr_ttm": 1.00, "health_green_median": 76, "dau_mau": 0.22, "feature_depth_green_median": 0.40, "seat_utilization": 0.65, "ttv_p50_days": 7,  "ttv_p75_days": 14, "multithread_depth": 1, "ecri_median": 45, "arr_per_csm_target": 10_000_000, "power_user_ratio_green_median": 0.15},
}

# --------------------------------------------------------------------------------------
# Prompt registry
# --------------------------------------------------------------------------------------

_HEADER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


def _parse_header(text: str) -> Dict[str, Any]:
    """Minimal YAML-subset parser for prompt headers: `key: scalar` and `key: [a, b, c]`."""
    out: Dict[str, Any] = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, _, val = line.partition(":")
        key, val = key.strip(), val.strip()
        if val.startswith("[") and val.endswith("]"):
            inner = val[1:-1].strip()
            out[key] = [v.strip().strip("'\"") for v in inner.split(",") if v.strip()] if inner else []
        elif val.lower() in ("true", "false"):
            out[key] = val.lower() == "true"
        else:
            try:
                out[key] = int(val) if re.fullmatch(r"-?\d+", val) else float(val) if re.fullmatch(r"-?\d+\.\d+", val) else val.strip("'\"")
            except ValueError:
                out[key] = val
    return out


@dataclass
class Prompt:
    id: str
    version: str
    model: str
    temperature: float
    max_tokens: int
    variables: List[str]
    output_schema: str
    body: str
    path: Path

    def render(self, variables: Dict[str, Any]) -> str:
        missing = [v for v in self.variables if v not in variables]
        if missing:
            raise KeyError(f"Prompt {self.id} missing variables: {missing}")
        text = self.body
        for name, value in variables.items():
            rendered = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
            text = text.replace("{{" + name + "}}", rendered)
        leftover = re.findall(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}", text)
        if leftover:
            raise KeyError(f"Prompt {self.id} has unrendered placeholders: {sorted(set(leftover))}")
        return text


class PromptRegistry:
    def __init__(self, prompt_dir: Path = PROMPT_DIR):
        self.prompts: Dict[str, Prompt] = {}
        for p in sorted(prompt_dir.rglob("*.prompt")):
            self.prompts[self._load(p).id] = self._load(p)

    @staticmethod
    def _load(path: Path) -> Prompt:
        text = path.read_text(encoding="utf-8")
        m = _HEADER_RE.match(text)
        if not m:
            raise ValueError(f"{path}: missing YAML header")
        header = _parse_header(m.group(1))
        return Prompt(
            id=str(header["id"]),
            version=str(header.get("version", "0.0.0")),
            model=str(header.get("model", DEFAULT_MODEL)),
            temperature=float(header.get("temperature", 0.2)),
            max_tokens=int(header.get("max_tokens", 4096)),
            variables=list(header.get("variables", [])),
            output_schema=str(header.get("output_schema", "src/schemas/playbook_action.json")),
            body=m.group(2).strip(),
            path=path,
        )

    def get(self, prompt_id: str) -> Prompt:
        if prompt_id not in self.prompts:
            raise KeyError(f"Unknown prompt id {prompt_id}; have {sorted(self.prompts)}")
        return self.prompts[prompt_id]


# --------------------------------------------------------------------------------------
# Schemas and validation
# --------------------------------------------------------------------------------------

def load_schema(name: str) -> Dict[str, Any]:
    with (SCHEMA_DIR / name).open(encoding="utf-8") as fh:
        return json.load(fh)


def validate(instance: Dict[str, Any], schema: Dict[str, Any]) -> List[str]:
    """Return a list of validation error messages (empty = valid)."""
    if jsonschema is None:
        raise RuntimeError("jsonschema is required: pip install jsonschema")
    validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.path))
    return [f"{'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}" for e in errors]


_PATH_TOKEN_RE = re.compile(r"([a-zA-Z_][a-zA-Z0-9_]*)|\[(\d+)\]")


def resolve_path(doc: Any, path: str) -> Tuple[bool, Any]:
    """Resolve a dotted/bracket path like `relationship.stakeholders[2].enrichment.current_employer`."""
    cur = doc
    pos = 0
    path = path.strip().lstrip("$").lstrip(".")
    while pos < len(path):
        if path[pos] == ".":
            pos += 1
            continue
        m = _PATH_TOKEN_RE.match(path, pos)
        if not m:
            return False, None
        key, idx = m.group(1), m.group(2)
        if key is not None:
            if not isinstance(cur, dict) or key not in cur:
                return False, None
            cur = cur[key]
        else:
            i = int(idx)
            if not isinstance(cur, list) or i >= len(cur):
                return False, None
            cur = cur[i]
        pos = m.end()
    return True, cur


class EvidenceIntegrityError(ValueError):
    pass


def check_evidence_integrity(action: Dict[str, Any], c360: Dict[str, Any], max_unresolved: int = 2) -> List[str]:
    """Every evidence[].source_path must resolve inside the input document. Returns unresolved paths."""
    unresolved = []
    for ev in action.get("evidence", []):
        ok, _ = resolve_path(c360, ev.get("source_path", ""))
        if not ok:
            unresolved.append(ev.get("source_path", ""))
    if len(unresolved) > max_unresolved:
        raise EvidenceIntegrityError(f"{len(unresolved)} evidence paths do not resolve: {unresolved}")
    return unresolved


# --------------------------------------------------------------------------------------
# Trigger evaluation
# --------------------------------------------------------------------------------------

def _g(d: Dict[str, Any], path: str, default: Any = None) -> Any:
    ok, v = resolve_path(d, path)
    return v if ok and v is not None else default


def _bench(c: Dict[str, Any], key: str, default: Any = None) -> Any:
    seg = _g(c, "account.segment", "mid_market")
    return (c.get("benchmarks") or {}).get(key, DEFAULT_BENCHMARKS.get(seg, {}).get(key, default))


def trig_ret_01(c: Dict[str, Any]) -> Optional[str]:
    h, h30 = _g(c, "health.score", 100), _g(c, "health.score_30d_ago")
    if _g(c, "health.band") == "red":
        return "health band red"
    if h30 is not None and (h30 - h) >= 15:
        return f"health dropped {h30 - h:.0f} points in 30d"
    if _g(c, "relationship.champion.status") == "departed" and not _g(c, "relationship.champion.replacement_identified", False):
        return "champion departed without replacement"
    for t in _g(c, "support.open_tickets", []):
        if t.get("priority") == "P1" and (t.get("age_days") or 0) > 5:
            return f"P1 {t.get('ticket_id')} open {t.get('age_days')} days"
    if _g(c, "contract.days_to_renewal", 999) <= 120 and h < 65:
        return "renewal within 120 days with health < 65"
    if _g(c, "sentiment.ecri", 0) >= 60:
        return f"ECRI {_g(c, 'sentiment.ecri')}"
    return None


def trig_ret_02(c: Dict[str, Any]) -> Optional[str]:
    if _g(c, "contract.days_to_renewal", 999) > 120:
        return None
    if _g(c, "health.band") == "yellow":
        return "renewal within 120 days, health yellow"
    if _g(c, "usage.seat_utilization", 1.0) < 0.50:
        return "renewal within 120 days, utilization < 50%"
    if _g(c, "contract.contraction_flag_90d", False):
        return "renewal within 120 days, contraction in last 90 days"
    return None


def trig_adp_01(c: Dict[str, Any]) -> Optional[str]:
    if _g(c, "lifecycle.stage") != "onboarding":
        return None
    if _g(c, "lifecycle.value_milestones_reached", []):
        return None
    days = _g(c, "lifecycle.days_since_term_start", 0)
    p75 = _bench(c, "ttv_p75_days", 35)
    return f"onboarding day {days} > p75 {p75} with no value milestone" if days > p75 else None


def trig_adp_02(c: Dict[str, Any]) -> Optional[str]:
    if _g(c, "health.band") == "red" or _g(c, "contract.days_to_renewal", 999) <= 120:
        return None
    depth, drift = _g(c, "usage.feature_depth_30d", 1.0), _g(c, "usage.utilization_drift_90d", 0.0)
    green = _bench(c, "feature_depth_green_median", 0.55)
    if depth <= green - 0.15:
        return f"feature depth {depth:.2f} vs green median {green:.2f}"
    if drift <= -0.10:
        return f"utilization drift {drift:+.2f}"
    return None


def trig_cad_01(c: Dict[str, Any]) -> Optional[str]:
    due = _g(c, "cadence.next_ebr_due_at")
    if due:
        days = (date.fromisoformat(due) - date.fromisoformat(c["as_of_date"])).days
        if 0 <= days <= 30:
            return f"EBR due in {days} days"
    if _g(c, "contract.days_to_renewal", 999) <= 180 and _g(c, "cadence.ebrs_completed_last_2_quarters", 0) == 0 and _g(c, "cadence.ebr_cadence") != "none":
        return "renewal within 180 days and no EBR in two quarters"
    return None


def trig_exp_01(c: Dict[str, Any]) -> Optional[str]:
    if _g(c, "account.segment") not in ("smb", "digital"):
        return None
    if _g(c, "health.band") == "red":
        return None
    if _g(c, "usage.seat_utilization", 0) >= 0.85:
        return "utilization ≥ 85%"
    gates = sum(g.get("hits", 0) for g in _g(c, "usage.feature_gate_hits_14d", []))
    if gates >= 3:
        return f"{gates} feature-gate hits in 14d"
    if (_g(c, "usage.pql_score") or 0) >= 70:
        return "PQL ≥ 70"
    if _g(c, "usage.dau_mau_30d", 0) >= 0.35:
        return "DAU/MAU ≥ 0.35"
    return None


def trig_exp_02(c: Dict[str, Any]) -> Optional[str]:
    if _g(c, "account.segment") not in ("enterprise", "mid_market"):
        return None
    if _g(c, "health.band") != "green" or _g(c, "usage.seat_utilization", 0) < 0.80:
        return None
    if _g(c, "contract.days_to_renewal", 999) <= 60:
        return None
    if any(o.get("type") in ("expansion", "upsell", "cross_sell") and not o.get("is_closed") for o in _g(c, "opportunities", [])):
        return None
    ws = c.get("whitespace") or {}
    if ws.get("unowned_modules") or ws.get("unowned_business_units"):
        return "green, utilization ≥ 80%, whitespace present, no open expansion opp"
    gates = sum(g.get("hits", 0) for g in _g(c, "usage.feature_gate_hits_14d", []))
    if gates >= 3 or _g(c, "usage.seat_utilization", 0) >= 1.0:
        return "green, feature-gate hits or over-deployment"
    return None


@dataclass(frozen=True)
class PlaybookSpec:
    playbook_id: str
    priority_rank: int           # lower = runs first; P0 retention suppresses P3 expansion
    cooldown_days: int
    prompt_chain: Tuple[str, ...]
    trigger: Callable[[Dict[str, Any]], Optional[str]]


PLAYBOOK_TRIGGERS: List[PlaybookSpec] = [
    PlaybookSpec("PB-RET-01", 0, 14, ("retention.churn_risk_rca", "retention.renewal_defense_playbook"), trig_ret_01),
    PlaybookSpec("PB-RET-02", 0, 30, ("retention.renewal_defense_playbook",), trig_ret_02),
    PlaybookSpec("PB-ADP-01", 1, 7, ("adoption.ttv_acceleration",), trig_adp_01),
    PlaybookSpec("PB-ADP-02", 1, 21, ("adoption.feature_depth_audit",), trig_adp_02),
    PlaybookSpec("PB-CAD-01", 2, 60, ("adoption.feature_depth_audit", "expansion.executive_ebr_generator"), trig_cad_01),
    PlaybookSpec("PB-EXP-01", 3, 30, ("expansion.whitespace_expansion_finder",), trig_exp_01),
    PlaybookSpec("PB-EXP-02", 3, 45, ("expansion.whitespace_expansion_finder", "expansion.executive_ebr_generator"), trig_exp_02),
]


def evaluate_triggers(c360: Dict[str, Any], only: Optional[str] = None) -> List[Tuple[PlaybookSpec, str]]:
    opt_out = set(_g(c360, "account.cse_opt_out_playbooks", []))
    fired: List[Tuple[PlaybookSpec, str]] = []
    open_recent = {a["playbook_id"] for a in c360.get("actions_last_30d", []) if a.get("status") == "open"}
    for spec in PLAYBOOK_TRIGGERS:
        if only and spec.playbook_id != only:
            continue
        if spec.playbook_id in opt_out:
            log.info("%s suppressed by opt-out on %s", spec.playbook_id, _g(c360, "account.account_id"))
            continue
        reason = spec.trigger(c360) if not only else (spec.trigger(c360) or "manual run")
        if reason:
            fired.append((spec, reason))
    fired.sort(key=lambda t: t[0].priority_rank)
    if any(s.priority_rank == 0 for s, _ in fired):
        fired = [(s, r) for s, r in fired if s.priority_rank != 3]      # P0 suppresses expansion
    if "PB-RET-01" in {s.playbook_id for s, _ in fired}:
        fired = [(s, r) for s, r in fired if s.playbook_id != "PB-RET-02"]  # RET-01 subsumes RET-02
    result = []
    for spec, reason in fired:
        if spec.playbook_id in open_recent and not only:
            result.append((spec, f"[signal_update] {reason}"))
        else:
            result.append((spec, reason))
    return result


# --------------------------------------------------------------------------------------
# Claude client
# --------------------------------------------------------------------------------------

TOOL_NAME = "emit_playbook_action"
TOOL_DESCRIPTION = (
    "Emit the single PlaybookAction for this account and instruction. The input must validate "
    "against the PlaybookAction JSON Schema. Every numeric or factual claim must be backed by an "
    "evidence[] entry whose source_path resolves inside the provided Customer 360."
)

UNTRUSTED_FIELDS = (
    "sentiment.nps_responses", "sentiment.transcript_signals", "sentiment.verbatim_signals",
    "support.open_tickets", "lifecycle.kickoff_notes",
)
_INJECTION_RE = re.compile(r"</?\s*(system|instruction|tool|customer_360|untrusted_customer_text)\b[^>]*>", re.IGNORECASE)


def sanitize_untrusted(c360: Dict[str, Any]) -> Dict[str, Any]:
    """Strip tag-like injection attempts from customer-authored fields (prompts also wrap them)."""
    doc = json.loads(json.dumps(c360))  # deep copy

    def scrub(obj: Any) -> Any:
        if isinstance(obj, str):
            return _INJECTION_RE.sub("", obj)
        if isinstance(obj, list):
            return [scrub(x) for x in obj]
        if isinstance(obj, dict):
            return {k: scrub(v) for k, v in obj.items()}
        return obj

    for path in UNTRUSTED_FIELDS:
        ok, val = resolve_path(doc, path)
        if ok and val is not None:
            parts = path.split(".")
            target = doc
            for p in parts[:-1]:
                target = target[p]
            target[parts[-1]] = scrub(val)
    return doc


def render_customer_360_for_prompt(c360: Dict[str, Any]) -> str:
    """Serialize with customer-authored text wrapped in <untrusted_customer_text> tags."""
    doc = sanitize_untrusted(c360)
    for r in _g(doc, "sentiment.nps_responses", []):
        if r.get("verbatim"):
            r["verbatim"] = f"<untrusted_customer_text>{r['verbatim']}</untrusted_customer_text>"
    for s in _g(doc, "sentiment.transcript_signals", []):
        for t in s.get("themes", []):
            if t.get("quoted_evidence"):
                t["quoted_evidence"] = f"<untrusted_customer_text>{t['quoted_evidence']}</untrusted_customer_text>"
    for t in _g(doc, "support.open_tickets", []):
        if t.get("subject"):
            t["subject"] = f"<untrusted_customer_text>{t['subject']}</untrusted_customer_text>"
    if _g(doc, "lifecycle.kickoff_notes"):
        doc["lifecycle"]["kickoff_notes"] = f"<untrusted_customer_text>{doc['lifecycle']['kickoff_notes']}</untrusted_customer_text>"
    return json.dumps(doc, ensure_ascii=False, indent=None, default=str)


@dataclass
class ClaudeCallResult:
    action: Dict[str, Any]
    model: str
    request_id: Optional[str]
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    latency_s: float
    retries: int


class ClaudeEmitter:
    """Wraps the anthropic SDK: cached system blocks + forced tool call + validation retry."""

    def __init__(self, registry: PromptRegistry, action_schema: Dict[str, Any], csm_name: str, today: str,
                 benchmarks: Dict[str, Any], playbook_registry_text: str, max_retries: int = 1):
        try:
            import anthropic  # noqa: F401
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("anthropic SDK required: pip install anthropic") from e
        import anthropic
        self.client = anthropic.Anthropic()
        self.registry = registry
        self.schema = action_schema
        self.max_retries = max_retries
        self.system_prompt = registry.get("core.system_csm_orchestrator").render({
            "csm_name": csm_name, "today": today,
            "playbook_registry_json": playbook_registry_text,
            "segment_benchmarks_json": benchmarks,
        })
        self.playbook_registry_text = playbook_registry_text

    def emit(self, prompt_id: str, variables: Dict[str, Any], c360: Dict[str, Any], instruction: str,
             csm_id: str) -> ClaudeCallResult:
        prompt = self.registry.get(prompt_id)
        body = prompt.render(variables)
        user_content = (
            f"<customer_360>\n{render_customer_360_for_prompt(c360)}\n</customer_360>\n"
            f"<instruction>{instruction}</instruction>"
        )
        messages: List[Dict[str, Any]] = [{"role": "user", "content": user_content}]
        retries = 0
        t0 = time.time()
        last_errors: List[str] = []
        while True:
            resp = self._call(prompt, body, messages)
            tool_blocks = [b for b in resp.content if getattr(b, "type", None) == "tool_use" and b.name == TOOL_NAME]
            if not tool_blocks:
                raise RuntimeError(f"{prompt_id}: model did not call {TOOL_NAME}")
            action = dict(tool_blocks[0].input)
            errors = validate(action, self.schema)
            if not errors:
                try:
                    check_evidence_integrity(action, c360)
                except EvidenceIntegrityError as e:
                    errors = [str(e)]
            if not errors:
                usage = resp.usage
                return ClaudeCallResult(
                    action=action, model=resp.model, request_id=getattr(resp, "_request_id", None),
                    input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
                    cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
                    cache_write_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
                    latency_s=time.time() - t0, retries=retries,
                )
            last_errors = errors
            if retries >= self.max_retries:
                raise ValueError(f"{prompt_id}: output failed validation after {retries + 1} attempts: {errors[:5]}")
            retries += 1
            messages.append({"role": "assistant", "content": resp.content})
            messages.append({"role": "user", "content": [{
                "type": "tool_result", "tool_use_id": tool_blocks[0].id, "is_error": True,
                "content": "Your previous output failed validation:\n- " + "\n- ".join(errors[:10]) +
                           "\nFix every error and call emit_playbook_action again with the corrected object.",
            }]})

    def _call(self, prompt: Prompt, body: str, messages: List[Dict[str, Any]]):
        import anthropic
        backoff = 2.0
        for attempt in range(6):
            try:
                return self.client.messages.create(
                    model=prompt.model or DEFAULT_MODEL,
                    max_tokens=prompt.max_tokens,
                    temperature=prompt.temperature,
                    system=[
                        {"type": "text", "text": self.system_prompt, "cache_control": {"type": "ephemeral"}},
                        {"type": "text", "text": body},
                    ],
                    messages=messages,
                    tools=[{"name": TOOL_NAME, "description": TOOL_DESCRIPTION, "input_schema": self.schema}],
                    tool_choice={"type": "tool", "name": TOOL_NAME},
                )
            except (anthropic.RateLimitError, anthropic.APIStatusError) as e:
                status = getattr(e, "status_code", None)
                if status in (429, 529, 500, 502, 503) and attempt < 5:
                    sleep = backoff * (1 + 0.25 * (attempt % 3))
                    log.warning("Anthropic %s; retrying in %.1fs", status, sleep)
                    time.sleep(sleep)
                    backoff *= 2
                    continue
                raise
        raise RuntimeError("unreachable")


class OfflineEmitter:
    """
    Deterministic stand-in for ClaudeEmitter used by --offline (CI, demos, no API key).
    Produces a schema-valid PlaybookAction derived from the trigger reason and the document
    so the full pipeline (validation, evidence integrity, routing, files) can be exercised.
    """

    def __init__(self, action_schema: Dict[str, Any]):
        self.schema = action_schema

    def emit(self, prompt_id: str, variables: Dict[str, Any], c360: Dict[str, Any], instruction: str,
             csm_id: str) -> ClaudeCallResult:
        pb = variables.get("playbook_id", "ADHOC")
        acct = c360["account"]
        stakeholders = c360["relationship"]["stakeholders"]
        exec_sponsor = next((s for s in stakeholders if s.get("is_exec_sponsor")), stakeholders[0] if stakeholders else None)
        champ_status = c360["relationship"]["champion"]["status"]
        driver = "champion_loss" if champ_status == "departed" else ("expansion_opportunity" if pb.startswith("PB-EXP") else "value_perception" if pb.startswith("PB-RET") else "cadence_due" if pb == "PB-CAD-01" else "onboarding_incomplete" if pb == "PB-ADP-01" else "product_gap")
        days = c360["contract"]["days_to_renewal"]
        action = {
            "playbook_id": pb, "priority": "P0" if pb.startswith("PB-RET") else "P1",
            "related_action_ids": [], "signal_update": None,
            "diagnosis": {
                "summary": (f"[OFFLINE STUB] {acct['name']} fired {pb} because: {instruction}. Health is "
                            f"{c360['health']['score']} ({c360['health']['band']}), champion status {champ_status}, "
                            f"{days} days to renewal. This stub exists to exercise the pipeline; replace with a live Claude call."),
                "primary_driver": driver, "secondary_drivers": [], "counter_evidence": "none identified (offline stub)",
                "blast_radius": "full_account", "revenue_at_risk_usd": c360["contract"]["arr"],
                "timeline": [{"date": c360["as_of_date"], "event": "trigger evaluated", "source_path": "as_of_date"}],
                "candidate_drivers": [], "disambiguating_question": None,
            },
            "renewal_outlook": {"band": "at_risk" if days <= 180 and c360["health"]["band"] != "green" else "unknown",
                                 "rationale": "offline stub: band derived from days_to_renewal and health band"},
            "actions": [
                {"type": "crm_write", "title": "Set CSE risk tier", "description": "Write the engine's risk tier to the account.",
                 "owner_role": "csm", "due_in_days": 0, "requires_human_approval": False,
                 "crm_write": {"object": "account", "object_id": acct["account_id"], "field": "cse_risk_tier", "value": c360["health"]["band"]},
                 "evidence_paths": ["health.band"]},
                {"type": "crm_task", "title": f"Review {pb} output for {acct['name']}", "description": "Human review of the generated playbook action.",
                 "owner_role": "csm", "due_in_days": 2, "requires_human_approval": False, "evidence_paths": ["health.score"]},
            ],
            "communications": ([{
                "recipient_contact_id": exec_sponsor["contact_id"], "channel": "email",
                "subject": f"Quick check-in on the {acct['name']} program",
                "body_markdown": f"Hi {exec_sponsor['name'].split()[0]},\n\nI'd like 30 minutes in the next two weeks to review where the program stands and what's next. Would early next week work?\n\nThanks,\n{acct['csm_owner_name']}",
                "tone_notes": "warm, brief, one ask", "send_after_days": 1, "requires_human_approval": True, "purpose": "value_review",
            }] if exec_sponsor else []),
            "evidence": [
                {"source_path": "health.score", "value": c360["health"]["score"], "supports": "current health"},
                {"source_path": "health.band", "value": c360["health"]["band"], "supports": "band"},
                {"source_path": "contract.days_to_renewal", "value": days, "supports": "renewal proximity"},
                {"source_path": "relationship.champion.status", "value": champ_status, "supports": "champion status"},
            ],
            "confidence": 0.5, "confidence_rationale": "offline stub; no model reasoning performed",
            "data_quality_flags": ["offline_stub"], "notes_for_csm": "Generated without Claude; run with ANTHROPIC_API_KEY for a real analysis.",
        }
        errors = validate(action, self.schema)
        if errors:
            raise ValueError(f"offline stub failed schema validation: {errors}")
        check_evidence_integrity(action, c360)
        return ClaudeCallResult(action, "offline-stub", None, 0, 0, 0, 0, 0.0, 0)


# --------------------------------------------------------------------------------------
# Routing
# --------------------------------------------------------------------------------------

ALWAYS_APPROVAL_FIELDS = {
    ("opportunity", "stage"), ("opportunity", "amount"), ("opportunity", "close_date"), ("opportunity", "probability"),
    ("account", "renewal_probability"), ("account", "forecast_category"), ("account", "arr"), ("account", "contract_value"),
}
CRM_WRITE_ALLOWLIST = {
    ("account", "cse_risk_tier"), ("account", "expansion_candidate"), ("account", "onboarding_risk_tier"),
    ("account", "cse_external_id"), ("account", "cse_last_playbook"), ("cadence", "last_ebr_prepared_at"),
    ("opportunity", "cse_scenario"), ("contact", "cse_persona"), ("contact", "cse_champion_status"),
    ("task", "title"), ("task", "due_date"), ("task", "body"),
} | ALWAYS_APPROVAL_FIELDS


def enforce_approval_floors(action: Dict[str, Any]) -> Dict[str, Any]:
    """Code-enforced: customer-facing comms and forecast/commercial writes always need approval."""
    for comm in action.get("communications", []):
        comm["requires_human_approval"] = True
    for a in action.get("actions", []):
        w = a.get("crm_write")
        if w and (w["object"], w["field"]) in ALWAYS_APPROVAL_FIELDS:
            a["requires_human_approval"] = True
        if a.get("type") in ("sales_handoff", "opportunity_suggestion", "support_escalation"):
            a["requires_human_approval"] = True
        if w and (w["object"], w["field"]) not in CRM_WRITE_ALLOWLIST:
            a["requires_human_approval"] = True
            a.setdefault("evidence_paths", [])
            a["description"] = f"[NOT IN ALLOWLIST — manual] {a['description']}"
    return action


@dataclass
class RoutedAction:
    account_id: str
    playbook_id: str
    prompt_id: str
    action_id: str
    priority: str
    confidence: float
    awaiting_approval: int
    executed: int
    files: List[str]


class ActionRouter:
    def __init__(self, out_dir: Path, dry_run: bool, run_date: str):
        self.out_dir = out_dir
        self.dry_run = dry_run
        self.run_date = run_date
        self.hubspot = None
        self.slack = None
        if not dry_run:
            from src.tools.clay_crm_enrichment import HubSpotAdapter, SlackNotifier
            if os.environ.get("HUBSPOT_ACCESS_TOKEN"):
                self.hubspot = HubSpotAdapter(os.environ["HUBSPOT_ACCESS_TOKEN"])
            if os.environ.get("SLACK_BOT_TOKEN"):
                self.slack = SlackNotifier(os.environ["SLACK_BOT_TOKEN"], os.environ.get("SLACK_ALERT_CHANNEL", "#cs-alerts"))

    def route(self, c360: Dict[str, Any], prompt_id: str, result: ClaudeCallResult, trigger_reason: str) -> RoutedAction:
        action = enforce_approval_floors(result.action)
        account_id = c360["account"]["account_id"]
        pb = action["playbook_id"]
        action_id = f"cse:{account_id}:{pb}:{self.run_date}"
        acct_dir = self.out_dir / account_id
        acct_dir.mkdir(parents=True, exist_ok=True)

        provenance = {
            "action_id": action_id, "prompt_id": prompt_id, "model": result.model, "request_id": result.request_id,
            "input_sha256": hashlib.sha256(json.dumps(c360, sort_keys=True, default=str).encode()).hexdigest(),
            "usage": {"input": result.input_tokens, "output": result.output_tokens,
                      "cache_read": result.cache_read_tokens, "cache_write": result.cache_write_tokens},
            "latency_s": round(result.latency_s, 2), "validation_retries": result.retries,
            "trigger_reason": trigger_reason, "emitted_at": datetime.now(timezone.utc).isoformat(),
            "dry_run": self.dry_run,
        }
        files: List[str] = []
        action_path = acct_dir / f"{pb}.{prompt_id.split('.')[-1]}.action.json"
        action_path.write_text(json.dumps({"provenance": provenance, "action": action}, indent=2, ensure_ascii=False), encoding="utf-8")
        files.append(str(action_path))

        for i, comm in enumerate(action.get("communications", [])):
            fm = {
                "artifact": f"comm_{comm.get('purpose') or 'message'}", "playbook_id": pb, "account_id": account_id,
                "to": [comm["recipient_contact_id"]], "cc": comm.get("cc_contact_ids", []), "channel": comm["channel"],
                "subject": comm["subject"], "tone": comm["tone_notes"], "send_after_days": comm["send_after_days"],
                "approval_status": "pending", "approved_by": None,
            }
            path = acct_dir / f"{pb}.comm_{i + 1}.md"
            path.write_text("---\n" + "\n".join(f"{k}: {json.dumps(v)}" for k, v in fm.items()) + "\n---\n\n" + comm["body_markdown"] + "\n", encoding="utf-8")
            files.append(str(path))

        awaiting = sum(1 for a in action.get("actions", []) if a.get("requires_human_approval")) + len(action.get("communications", []))
        executed = 0
        if not self.dry_run:
            executed = self._execute(c360, action, action_id)
            if self.slack and action["priority"] in ("P0", "P1"):
                self.slack.alert(
                    f"*{action['priority']} {pb}* — {c360['account']['name']} ({account_id})\n"
                    f"{action['diagnosis']['summary'][:400]}\n"
                    f"confidence {action['confidence']:.2f} · {awaiting} item(s) awaiting approval · {action_path.name}"
                )
        return RoutedAction(account_id, pb, prompt_id, action_id, action["priority"], action["confidence"], awaiting, executed, files)

    def _execute(self, c360: Dict[str, Any], action: Dict[str, Any], action_id: str) -> int:
        """Execute only non-approval actions through adapters; idempotent via external_id."""
        executed = 0
        for n, a in enumerate(action.get("actions", [])):
            if a.get("requires_human_approval"):
                continue
            ext = f"{action_id}:{n}"
            w = a.get("crm_write")
            try:
                if a["type"] == "crm_write" and w and self.hubspot:
                    if w["object"] == "account":
                        self.hubspot.update_account_properties(w.get("object_id") or c360["account"]["account_id"], {w["field"]: w["value"]}, ext)
                        executed += 1
                elif a["type"] == "crm_task" and self.hubspot:
                    self.hubspot.create_task(c360["account"]["account_id"], {"title": a["title"], "body": a["description"], "due_in_days": a["due_in_days"]}, ext)
                    executed += 1
            except Exception as e:  # adapter errors never abort the run
                log.error("adapter error on %s: %s", ext, e)
        return executed


# --------------------------------------------------------------------------------------
# Feed loading
# --------------------------------------------------------------------------------------

def load_feed(path: Path) -> Iterable[Tuple[str, Dict[str, Any]]]:
    """Yield (source_name, document) from a .json, .jsonl, or a directory of either."""
    paths = sorted(path.iterdir()) if path.is_dir() else [path]
    for p in paths:
        if p.suffix == ".jsonl":
            with p.open(encoding="utf-8") as fh:
                for i, line in enumerate(fh):
                    line = line.strip()
                    if line:
                        yield f"{p.name}:{i + 1}", json.loads(line)
        elif p.suffix == ".json":
            with p.open(encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, list):
                for i, d in enumerate(data):
                    yield f"{p.name}[{i}]", d
            else:
                yield p.name, data


# --------------------------------------------------------------------------------------
# Per-account run
# --------------------------------------------------------------------------------------

@dataclass
class AccountRunResult:
    account_id: str
    account_name: str
    health: float
    band: str
    fired: List[str] = field(default_factory=list)
    routed: List[RoutedAction] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class Orchestrator:
    def __init__(self, out_dir: Path, dry_run: bool, offline: bool, csm_name: str, today: Optional[str] = None,
                 benchmarks: Optional[Dict[str, Any]] = None, enrich: bool = False, parse_transcripts: bool = False):
        self.out_dir = out_dir
        self.today = today or date.today().isoformat()
        self.registry = PromptRegistry()
        self.c360_schema = load_schema("customer_360.json")
        self.action_schema = load_schema("playbook_action.json")
        self.benchmarks = benchmarks or DEFAULT_BENCHMARKS
        self.weights = HealthWeights.load()
        self.router = ActionRouter(out_dir, dry_run, self.today)
        self.enrich = enrich and bool(os.environ.get("CLAY_WEBHOOK_URL"))
        self.parse_transcripts = parse_transcripts
        registry_text = (ROOT / "docs" / "03_PLAYBOOKS_MASTER_INDEX.md").read_text(encoding="utf-8")
        if offline:
            self.emitter: Any = OfflineEmitter(self.action_schema)
        else:
            if not os.environ.get("ANTHROPIC_API_KEY"):
                raise SystemExit("ANTHROPIC_API_KEY is not set (use --offline to run without the API)")
            self.emitter = ClaudeEmitter(self.registry, self.action_schema, csm_name, self.today, self.benchmarks, registry_text)

    # -- pipeline steps ----------------------------------------------------------------

    def prepare(self, c360: Dict[str, Any]) -> Dict[str, Any]:
        errors = validate(c360, self.c360_schema)
        if errors:
            raise ValueError("Customer 360 failed validation: " + "; ".join(errors[:5]))
        seg = c360["account"]["segment"]
        c360.setdefault("benchmarks", {})
        for k, v in self.benchmarks.get(seg, {}).items():
            c360["benchmarks"].setdefault(k, v)

        if self.enrich:
            from src.tools.clay_crm_enrichment import enrich_account_stakeholders
            c360 = enrich_account_stakeholders(c360)

        if self.parse_transcripts:
            from src.tools.call_transcript_parser import parse_and_analyze_pending
            c360 = parse_and_analyze_pending(c360, offline=isinstance(self.emitter, OfflineEmitter))

        result = compute_health_score(c360, self.weights)
        try:
            assert_no_drift(result, (c360.get("health") or {}).get("mart_score"))
        except HealthScoreDriftError as e:
            log.error("%s: %s", c360["account"]["account_id"], e)
            c360.setdefault("_drift_error", str(e))
        return attach_to_customer_360(c360, result)

    def variables_for(self, prompt_id: str, c360: Dict[str, Any], spec: PlaybookSpec, prior: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        base = {
            "customer_360_json": "(see <customer_360> block)",
            "segment_benchmarks_json": self.benchmarks.get(c360["account"]["segment"], {}),
            "today": self.today,
            "playbook_id": spec.playbook_id,
        }
        extra = {
            "retention.renewal_defense_playbook": {"rca_json": prior.get("retention.churn_risk_rca", {})},
            "adoption.ttv_acceleration": {"value_milestone_definitions_json": c360.get("_value_milestone_definitions", DEFAULT_VALUE_MILESTONES)},
            "adoption.feature_depth_audit": {"feature_catalog_json": c360.get("_feature_catalog", DEFAULT_FEATURE_CATALOG)},
            "expansion.whitespace_expansion_finder": {"pricing_catalog_json": c360.get("_pricing_catalog", DEFAULT_PRICING_CATALOG),
                                                      "feature_audit_json": prior.get("adoption.feature_depth_audit", {}).get("feature_audit", {})},
            "expansion.executive_ebr_generator": {"retention_context_json": c360.get("_retention_context", {}),
                                                  "roi_inputs_json": c360.get("_roi_inputs", DEFAULT_ROI_INPUTS),
                                                  "feature_audit_json": prior.get("adoption.feature_depth_audit", {}).get("feature_audit", {}),
                                                  "expansion_brief_json": prior.get("expansion.whitespace_expansion_finder", {}).get("expansion_brief", {}),
                                                  "variant": "expansion" if spec.playbook_id == "PB-EXP-02" else ("renewal" if spec.playbook_id == "PB-RET-01" else "standard")},
        }
        base.update(extra.get(prompt_id, {}))
        prompt = self.registry.get(prompt_id)
        return {k: v for k, v in base.items() if k in prompt.variables or k == "playbook_id"}

    def run_account(self, c360: Dict[str, Any], only_playbook: Optional[str] = None) -> AccountRunResult:
        try:
            c360 = self.prepare(c360)
        except Exception as e:
            rej = self.out_dir / "_rejected"
            rej.mkdir(parents=True, exist_ok=True)
            aid = (c360.get("account") or {}).get("account_id", "unknown")
            (rej / f"{aid}.json").write_text(json.dumps({"error": str(e), "document": c360}, indent=2, default=str), encoding="utf-8")
            return AccountRunResult(aid, (c360.get("account") or {}).get("name", "?"), 0.0, "unknown", errors=[str(e)])

        res = AccountRunResult(c360["account"]["account_id"], c360["account"]["name"], c360["health"]["score"], c360["health"]["band"])
        if "_drift_error" in c360:
            res.errors.append(c360["_drift_error"])
        for spec, reason in evaluate_triggers(c360, only_playbook):
            res.fired.append(f"{spec.playbook_id}: {reason}")
            prior: Dict[str, Dict[str, Any]] = {}
            for prompt_id in spec.prompt_chain:
                try:
                    variables = self.variables_for(prompt_id, c360, spec, prior)
                    instruction = f"Run {spec.playbook_id} via {prompt_id}. Trigger: {reason}."
                    result = self.emitter.emit(prompt_id, variables, c360, instruction, c360["account"]["csm_owner_id"])
                    prior[prompt_id] = result.action
                    res.routed.append(self.router.route(c360, prompt_id, result, reason))
                except Exception as e:
                    log.exception("%s %s failed", c360["account"]["account_id"], prompt_id)
                    res.errors.append(f"{spec.playbook_id}/{prompt_id}: {e}")
        return res

    def run(self, feed: Path, only_account: Optional[str] = None, only_playbook: Optional[str] = None, concurrency: int = 8) -> Dict[str, Any]:
        docs = [(src, d) for src, d in load_feed(feed) if not only_account or (d.get("account") or {}).get("account_id") == only_account]
        self.out_dir.mkdir(parents=True, exist_ok=True)
        results: List[AccountRunResult] = []
        with cf.ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
            for r in pool.map(lambda sd: self.run_account(sd[1], only_playbook), docs):
                results.append(r)
                log.info("%s (%s) health=%.1f %s fired=%s errors=%s", r.account_name, r.account_id, r.health, r.band, r.fired, r.errors)
        summary = {
            "run_date": self.today, "accounts": len(results),
            "actions": sorted(
                [{"account_id": r.account_id, "account_name": r.account_name, "playbook_id": a.playbook_id, "prompt_id": a.prompt_id,
                  "priority": a.priority, "confidence": a.confidence, "awaiting_approval": a.awaiting_approval,
                  "executed": a.executed, "files": a.files} for r in results for a in r.routed],
                key=lambda x: (x["priority"], -x["confidence"]),
            ),
            "errors": [{"account_id": r.account_id, "errors": r.errors} for r in results if r.errors],
            "by_band": {b: sum(1 for r in results if r.band == b) for b in ("green", "yellow", "red", "unknown")},
        }
        (self.out_dir / "run_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        return summary


# --------------------------------------------------------------------------------------
# Defaults for prompt catalogs (replace with warehouse/CS Ops-maintained versions)
# --------------------------------------------------------------------------------------

DEFAULT_VALUE_MILESTONES = {
    "primary": ["first_production_workflow", "integration_connected", "five_active_users"],
    "definitions": {
        "first_production_workflow": {"prerequisites": ["integration_connected", "admin_assigned"], "description": "A workflow executed against production data"},
        "integration_connected": {"prerequisites": ["admin_assigned"], "description": "At least one source system connected"},
        "five_active_users": {"prerequisites": ["training_delivered"], "description": "Five distinct users with ≥ 3 sessions in a week"},
        "first_report_shared": {"prerequisites": ["first_production_workflow"], "description": "A report shared outside the admin team"},
    },
}

DEFAULT_FEATURE_CATALOG = [
    {"feature_key": "dashboards", "is_core": True, "retention_lift": 0.06, "prerequisites": [], "target_personas": ["end_user", "ops_manager"], "enablement_assets": [{"id": "EA-101", "type": "video", "duration_min": 6}], "typical_time_to_adopt_days": 7, "module": "core", "green_peer_adoption": 0.92},
    {"feature_key": "alerts", "is_core": True, "retention_lift": 0.08, "prerequisites": ["dashboards"], "target_personas": ["ops_manager"], "enablement_assets": [{"id": "EA-102", "type": "doc", "duration_min": 10}], "typical_time_to_adopt_days": 10, "module": "core", "green_peer_adoption": 0.81},
    {"feature_key": "workflow_automation", "is_core": True, "retention_lift": 0.14, "prerequisites": ["integration_connected:crm"], "target_personas": ["ops_manager", "admin"], "enablement_assets": [{"id": "EA-201", "type": "live_session", "duration_min": 45}], "typical_time_to_adopt_days": 21, "module": "core", "green_peer_adoption": 0.68},
    {"feature_key": "api_access", "is_core": True, "retention_lift": 0.09, "prerequisites": [], "target_personas": ["developer"], "enablement_assets": [{"id": "EA-301", "type": "doc", "duration_min": 20}], "typical_time_to_adopt_days": 14, "module": "core", "green_peer_adoption": 0.44},
    {"feature_key": "scheduled_reports", "is_core": False, "retention_lift": 0.03, "prerequisites": ["dashboards"], "target_personas": ["end_user"], "enablement_assets": [{"id": "EA-103", "type": "video", "duration_min": 4}], "typical_time_to_adopt_days": 5, "module": "core", "green_peer_adoption": 0.58},
    {"feature_key": "audit_log", "is_core": False, "retention_lift": 0.04, "prerequisites": [], "target_personas": ["it_security"], "enablement_assets": [{"id": "EA-401", "type": "doc", "duration_min": 8}], "typical_time_to_adopt_days": 7, "module": "security", "green_peer_adoption": 0.35},
    {"feature_key": "sso_scim", "is_core": False, "retention_lift": 0.11, "prerequisites": [], "target_personas": ["it_security", "admin"], "enablement_assets": [{"id": "EA-402", "type": "live_session", "duration_min": 30}], "typical_time_to_adopt_days": 14, "module": "security", "green_peer_adoption": 0.52},
    {"feature_key": "advanced_permissions", "is_core": False, "retention_lift": 0.07, "prerequisites": ["sso_scim"], "target_personas": ["admin"], "enablement_assets": [{"id": "EA-403", "type": "doc", "duration_min": 12}], "typical_time_to_adopt_days": 10, "module": "security", "green_peer_adoption": 0.40},
]

DEFAULT_PRICING_CATALOG = {
    "tiers": [
        {"tier": "team", "list_price_per_seat_annual": 480, "seat_pack": 5, "gated_features": []},
        {"tier": "business", "list_price_per_seat_annual": 840, "seat_pack": 10, "gated_features": ["audit_log", "api_access"]},
        {"tier": "enterprise", "list_price_per_seat_annual": 1200, "seat_pack": 25, "gated_features": ["workflow_automation"]},
        {"tier": "enterprise_plus", "list_price_per_seat_annual": 1560, "seat_pack": 25, "gated_features": ["sso_scim", "advanced_permissions"]},
    ],
    "modules": [
        {"module": "security", "list_price_per_seat_annual": 240, "target_personas": ["it_security", "admin"]},
        {"module": "analytics_plus", "list_price_per_seat_annual": 360, "target_personas": ["ops_manager", "economic_buyer"]},
    ],
    "sales_assist_threshold_arr": {"digital": 12_000, "smb": 20_000, "mid_market": 0, "enterprise": 0},
}

DEFAULT_ROI_INPUTS = {
    "loaded_hourly_rate": None,
    "loaded_hourly_rate_source": "not supplied — ask customer finance; do not assume",
    "notes": "Populate from CS Ops roi_inputs table per account before EBR generation.",
}


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="CS-Claude Engine orchestrator")
    ap.add_argument("--input", required=True, help=".json, .jsonl, or directory")
    ap.add_argument("--out", default="./out")
    ap.add_argument("--csm", default="the CSM")
    ap.add_argument("--account-id", default=None)
    ap.add_argument("--playbook", default=None, help="Force a single playbook id (e.g. PB-CAD-01)")
    ap.add_argument("--dry-run", action="store_true", help="Write files only; never call adapters (also CSE_DRY_RUN=true)")
    ap.add_argument("--offline", action="store_true", help="No API calls; deterministic stub actions to exercise the pipeline")
    ap.add_argument("--enrich", action="store_true", help="Push stale stakeholders to Clay (needs CLAY_WEBHOOK_URL)")
    ap.add_argument("--parse-transcripts", action="store_true", help="Parse pending transcripts into sentiment signals")
    ap.add_argument("--concurrency", type=int, default=int(os.environ.get("CSE_CONCURRENCY", "8")))
    ap.add_argument("--today", default=None)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    dry_run = args.dry_run or args.offline or os.environ.get("CSE_DRY_RUN", "true").lower() == "true"
    orch = Orchestrator(Path(args.out), dry_run, args.offline, args.csm, args.today, enrich=args.enrich, parse_transcripts=args.parse_transcripts)
    summary = orch.run(Path(args.input), args.account_id, args.playbook, args.concurrency)
    print(json.dumps({k: v for k, v in summary.items() if k != "actions"}, indent=2))
    print(f"{len(summary['actions'])} action(s) written under {args.out}/ — see run_summary.json")
    return 0 if not summary["errors"] else 1


if __name__ == "__main__":
    sys.exit(main())
