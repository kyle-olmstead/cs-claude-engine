"""
Schema, integrity, and policy checks for Customer 360 documents and PlaybookActions.

Pure functions, no I/O, no network. Used by the Claude client (validation + retry), the
`validate.py` CLI (which the plugin skills call), the router (policy floors), and the tests.

Checks, in the order they run:
  1. JSON Schema (Draft 2020-12, with format checking)
  2. Evidence integrity — every evidence[].source_path must resolve inside the Customer 360,
     and when a value is claimed it must match the document's value (a real path with a wrong
     number is the most plausible hallucination channel; this closes it)
  3. Recipient safety — communications only to current stakeholders
  4. Policy floors — customer-facing items and commercial/forecast writes always need approval;
     low-confidence actions are lowered to P3; floors are recorded in data_quality_flags and
     never mutate free-text fields
  5. Cooldowns — a playbook that fired inside its window and is still open is not re-fired
"""

from __future__ import annotations

import math
import re
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

import jsonschema

_TOKEN = re.compile(r"([a-zA-Z_][a-zA-Z0-9_]*)|\[(\d+)\]")

CONFIDENCE_FLOOR = 0.55
EVIDENCE_MAX_UNRESOLVED = 2

COOLDOWN_DAYS: Dict[str, int] = {
    "PB-RET-01": 14, "PB-RET-02": 30, "PB-ADP-01": 7, "PB-ADP-02": 21,
    "PB-CAD-01": 60, "PB-EXP-01": 30, "PB-EXP-02": 45,
}

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
ALWAYS_APPROVAL_ACTION_TYPES = {"sales_handoff", "opportunity_suggestion", "support_escalation"}


# --------------------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------------------

def resolve_path(doc: Any, path: str) -> Tuple[bool, Any]:
    """Resolve `relationship.stakeholders[2].enrichment.current_employer` inside a document."""
    cur = doc
    pos = 0
    path = path.strip().lstrip("$").lstrip(".")
    while pos < len(path):
        if path[pos] == ".":
            pos += 1
            continue
        m = _TOKEN.match(path, pos)
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


def get_path(doc: Any, path: str, default: Any = None) -> Any:
    ok, v = resolve_path(doc, path)
    return v if ok and v is not None else default


# --------------------------------------------------------------------------------------
# Schema
# --------------------------------------------------------------------------------------

def schema_errors(instance: Any, schema: Dict[str, Any]) -> List[str]:
    validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.path))
    return [f"{'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}" for e in errors]


def validate_c360(doc: Dict[str, Any], schema: Dict[str, Any]) -> List[str]:
    return schema_errors(doc, schema)


# --------------------------------------------------------------------------------------
# Evidence and recipients
# --------------------------------------------------------------------------------------

_UNTRUSTED_TAG_RE = re.compile(r"</?untrusted_customer_text>")


def _values_match(claimed: Any, actual: Any) -> bool:
    if isinstance(actual, str):
        actual = _UNTRUSTED_TAG_RE.sub("", actual)
    if isinstance(claimed, str):
        claimed = _UNTRUSTED_TAG_RE.sub("", claimed)
    if isinstance(claimed, bool) or isinstance(actual, bool):
        return claimed == actual
    if isinstance(claimed, (int, float)) and isinstance(actual, (int, float)):
        return math.isclose(float(claimed), float(actual), rel_tol=0.01, abs_tol=0.01)
    if isinstance(claimed, str) and isinstance(actual, (int, float)):
        try:
            return math.isclose(float(claimed.replace(",", "").replace("$", "")), float(actual), rel_tol=0.01, abs_tol=0.01)
        except ValueError:
            return False
    if isinstance(claimed, str) and isinstance(actual, str):
        return claimed.strip().lower() == actual.strip().lower()
    return claimed == actual


def check_evidence(action: Dict[str, Any], c360: Dict[str, Any], max_unresolved: int = EVIDENCE_MAX_UNRESOLVED) -> Tuple[List[str], List[str]]:
    """Returns (errors, unresolved_paths). Errors fail the action; unresolved paths are tolerated up to the limit."""
    errors: List[str] = []
    unresolved: List[str] = []
    for i, ev in enumerate(action.get("evidence", [])):
        path = ev.get("source_path", "")
        ok, actual = resolve_path(c360, path)
        if not ok:
            unresolved.append(path)
            continue
        claimed = ev.get("value")
        if claimed is not None and not isinstance(claimed, (list, dict)) and not isinstance(actual, (list, dict)):
            if not _values_match(claimed, actual):
                errors.append(f"evidence[{i}] value mismatch at {path}: claimed {claimed!r}, document has {actual!r}")
    if len(unresolved) > max_unresolved:
        errors.append(f"{len(unresolved)} evidence paths do not resolve in the Customer 360: {unresolved}")
    return errors, unresolved


def check_recipients(action: Dict[str, Any], c360: Dict[str, Any]) -> List[str]:
    stakeholders = {s.get("contact_id"): s for s in get_path(c360, "relationship.stakeholders", [])}
    errors: List[str] = []
    for i, comm in enumerate(action.get("communications", [])):
        rid = comm.get("recipient_contact_id")
        s = stakeholders.get(rid)
        if s is None:
            errors.append(f"communications[{i}] recipient {rid!r} is not in relationship.stakeholders[]")
            continue
        enr = s.get("enrichment") or {}
        if s.get("left_company_at") or enr.get("employer_matches_account") is False:
            errors.append(f"communications[{i}] recipient {rid!r} ({s.get('name')}) has left the account; choose a current stakeholder")
        for cid in comm.get("cc_contact_ids") or []:
            if cid not in stakeholders:
                errors.append(f"communications[{i}] cc {cid!r} is not in relationship.stakeholders[]")
    return errors


# --------------------------------------------------------------------------------------
# Policy floors
# --------------------------------------------------------------------------------------

def enforce_policy(action: Dict[str, Any], confidence_floor: float = CONFIDENCE_FLOOR) -> List[str]:
    """
    Apply code-enforced floors in place. Returns the list of changes made (also appended to
    data_quality_flags with a `policy:` prefix). Never mutates free-text fields.
    """
    changes: List[str] = []
    flags = action.setdefault("data_quality_flags", [])
    for i, comm in enumerate(action.get("communications", [])):
        if comm.get("requires_human_approval") is not True:
            comm["requires_human_approval"] = True
            changes.append(f"communications[{i}] requires_human_approval → true")
    for i, a in enumerate(action.get("actions", [])):
        w = a.get("crm_write")
        reason = None
        if a.get("type") in ALWAYS_APPROVAL_ACTION_TYPES:
            reason = f"type {a['type']} always needs approval"
        if w:
            key = (w.get("object"), w.get("field"))
            if key in ALWAYS_APPROVAL_FIELDS:
                reason = f"crm_write {key[0]}.{key[1]} is a forecast/commercial field"
            elif key not in CRM_WRITE_ALLOWLIST:
                reason = f"crm_write {key[0]}.{key[1]} is not in the allowlist; manual only"
        if reason and a.get("requires_human_approval") is not True:
            a["requires_human_approval"] = True
            changes.append(f"actions[{i}] requires_human_approval → true ({reason})")
    conf = action.get("confidence")
    if isinstance(conf, (int, float)) and conf < confidence_floor and action.get("priority") != "P3":
        changes.append(f"priority {action.get('priority')} → P3 (confidence {conf:.2f} < {confidence_floor})")
        action["priority"] = "P3"
    for c in changes:
        flags.append(f"policy: {c}")
    return changes


# --------------------------------------------------------------------------------------
# Composite
# --------------------------------------------------------------------------------------

def validate_action(action: Dict[str, Any], c360: Dict[str, Any], schema: Dict[str, Any]) -> List[str]:
    """Schema → evidence → recipients. Returns the error list (empty = valid). Does not apply policy."""
    errors = schema_errors(action, schema)
    if errors:
        return errors
    ev_errors, _ = check_evidence(action, c360)
    return ev_errors + check_recipients(action, c360)


def cooldown_active(playbook_id: str, actions_last_30d: List[Dict[str, Any]], today: date) -> Optional[str]:
    """Return the open action_id when this playbook fired inside its cooldown window and is still open."""
    days = COOLDOWN_DAYS.get(playbook_id, 0)
    for a in actions_last_30d or []:
        if a.get("playbook_id") == playbook_id and a.get("status") == "open":
            try:
                age = (today - date.fromisoformat(str(a.get("emitted_at")))).days
            except ValueError:
                continue
            if age < days:
                return str(a.get("action_id"))
    return None
