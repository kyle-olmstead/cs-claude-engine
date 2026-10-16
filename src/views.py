"""
Per-prompt views of the Customer 360.

Each prompt reasons over a subset of the document. Dropping the blocks it never reads and
capping long lists (ranked by relevance, never truncated blindly) cuts 30–50% of the user-turn
tokens per call.

Evidence paths are verified against the VIEW the model saw (the client passes the same object
to the validator), so re-ranked list indices stay consistent, and `_view_note` tells the model
what was trimmed. The full document is what gets written to disk and what plugin-mode skills
validate against; they never apply views.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional

DROP: Dict[str, List[str]] = {
    "retention.churn_risk_rca":              ["whitespace", "cadence.next_ebr_attendees"],
    "retention.renewal_defense_playbook":    ["whitespace.indicative_sizing", "usage.fading_features", "lifecycle.onboarding_steps"],
    "adoption.ttv_acceleration":             ["whitespace", "opportunities", "sentiment.nps_responses", "cadence"],
    "adoption.feature_depth_audit":          ["support.open_tickets", "opportunities", "cadence", "lifecycle.onboarding_steps"],
    "expansion.whitespace_expansion_finder": ["lifecycle.onboarding_steps", "support.open_tickets", "sentiment.nps_responses"],
    "expansion.executive_ebr_generator":     ["support.open_tickets", "lifecycle.onboarding_steps", "usage.feature_gate_hits_14d"],
}

CAPS: Dict[str, int] = {
    "relationship.stakeholders": 12, "sentiment.nps_responses": 6, "sentiment.transcript_signals": 4,
    "support.open_tickets": 10, "usage.fading_features": 8, "opportunities": 8, "actions_last_30d": 10,
    "usage.usage_by_business_unit": 10,
}

_PRIORITY = {"P1": 0, "P2": 1, "P3": 2, "P4": 3}
RANKERS: Dict[str, Callable[[Dict[str, Any]], Any]] = {
    "relationship.stakeholders": lambda s: (not (s.get("is_champion") or s.get("is_exec_sponsor") or s.get("persona") == "economic_buyer"), -(s.get("engagements_90d") or 0)),
    "support.open_tickets": lambda t: (_PRIORITY.get(t.get("priority"), 9), -(t.get("age_days") or 0)),
    "sentiment.transcript_signals": lambda s: s.get("occurred_at") or "",
    "sentiment.nps_responses": lambda r: r.get("responded_at") or "",
    "opportunities": lambda o: (o.get("is_closed", False), o.get("close_date") or ""),
}
_REVERSE = {"sentiment.transcript_signals", "sentiment.nps_responses"}  # newest first


def _walk(doc: Dict[str, Any], path: str) -> Optional[tuple]:
    parts = path.split(".")
    cur: Any = doc
    for p in parts[:-1]:
        if not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    if not isinstance(cur, dict):
        return None
    return cur, parts[-1]


def view_for(prompt_id: str, c360: Dict[str, Any]) -> Dict[str, Any]:
    doc = json.loads(json.dumps(c360))
    notes: List[str] = []
    for path in DROP.get(prompt_id, []):
        hit = _walk(doc, path)
        if hit and hit[1] in hit[0]:
            hit[0].pop(hit[1], None)
            notes.append(f"{path} omitted from this view (not needed by {prompt_id}); it exists in the full document")
    for path, n in CAPS.items():
        hit = _walk(doc, path)
        if not hit:
            continue
        parent, key = hit
        lst = parent.get(key)
        if isinstance(lst, list) and len(lst) > n:
            ranker = RANKERS.get(path)
            ordered = sorted(lst, key=ranker, reverse=path in _REVERSE) if ranker else lst
            parent[key] = ordered[:n]
            notes.append(f"{path} shows {n} of {len(lst)} entries (ranked by relevance); cite indices as they appear here")
    if notes:
        doc["_view_note"] = notes
    return doc
