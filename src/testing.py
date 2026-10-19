"""
Test doubles. `OfflineEmitter` stands in for the Claude client (`--offline`, CI, demos) and
produces a deterministic, schema-valid PlaybookAction so the whole pipeline (views, validation,
policy floors, routing, files) can be exercised with no API key.
"""

from __future__ import annotations

from typing import Any, Dict

from src.claude_client import ClaudeCallResult, schema_for
from src.validation import validate_action


class OfflineEmitter:
    def __init__(self, base_schema: Dict[str, Any]):
        self.base_schema = base_schema

    def emit(self, prompt_id: str, static_vars: Dict[str, Any], c360_view: Dict[str, Any], prior_outputs: Dict[str, Any],
             instruction: str) -> ClaudeCallResult:
        c = c360_view
        pb = static_vars.get("playbook_id", "ADHOC")
        acct = c["account"]
        stakeholders = c["relationship"]["stakeholders"]
        current = [s for s in stakeholders if not s.get("left_company_at") and (s.get("enrichment") or {}).get("employer_matches_account") is not False]
        exec_sponsor = next((s for s in current if s.get("is_exec_sponsor")), current[0] if current else None)
        champ_status = c["relationship"]["champion"]["status"]
        driver = ("champion_loss" if champ_status == "departed" else "expansion_opportunity" if pb.startswith("PB-EXP")
                  else "value_perception" if pb.startswith("PB-RET") else "cadence_due" if pb == "PB-CAD-01"
                  else "onboarding_incomplete" if pb == "PB-ADP-01" else "product_gap")
        days = c["contract"]["days_to_renewal"]
        stakeholder_index = next(i for i, s in enumerate(stakeholders) if exec_sponsor and s["contact_id"] == exec_sponsor["contact_id"]) if exec_sponsor else 0
        action: Dict[str, Any] = {
            "playbook_id": pb, "priority": "P0" if pb.startswith("PB-RET") else "P1",
            "related_action_ids": [], "signal_update": None,
            "diagnosis": {
                "summary": (f"[OFFLINE STUB] {acct['name']} fired {pb} because: {instruction}. Health is {c['health']['score']} "
                            f"({c['health']['band']}), champion status {champ_status}, {days} days to renewal. This stub exists to "
                            f"exercise the pipeline; replace with a live Claude call."),
                "primary_driver": driver, "secondary_drivers": [], "counter_evidence": "none identified (offline stub)",
                "blast_radius": "full_account", "revenue_at_risk_usd": c["contract"]["arr"],
                "timeline": [{"date": c["as_of_date"], "event": "trigger evaluated", "source_path": "as_of_date"}],
                "candidate_drivers": [], "disambiguating_question": None,
            },
            "renewal_outlook": {"band": "at_risk" if days <= 180 and c["health"]["band"] != "green" else "unknown",
                                 "rationale": "offline stub: band derived from days_to_renewal and health band"},
            "actions": [
                {"type": "crm_write", "title": "Set CSE risk tier", "description": "Write the engine's risk tier to the account.",
                 "owner_role": "csm", "due_in_days": 0, "requires_human_approval": False,
                 "crm_write": {"object": "account", "object_id": acct["account_id"], "field": "cse_risk_tier", "value": c["health"]["band"]},
                 "evidence_paths": ["health.band"]},
                {"type": "crm_task", "title": f"Review {pb} output for {acct['name']}", "description": "Human review of the generated playbook action.",
                 "owner_role": "csm", "due_in_days": 2, "requires_human_approval": False, "evidence_paths": ["health.score"]},
            ],
            "communications": ([{
                "recipient_contact_id": exec_sponsor["contact_id"], "channel": "email",
                "subject": f"Quick check-in on the {acct['name']} program",
                "body_markdown": (f"Hi {exec_sponsor['name'].split()[0]},\n\nI'd like 30 minutes in the next two weeks to review where the "
                                  f"program stands and what's next. Would early next week work?\n\nThanks,\n{acct['csm_owner_name']}"),
                "tone_notes": "warm, brief, one ask", "send_after_days": 1, "requires_human_approval": True, "purpose": "value_review",
            }] if exec_sponsor else []),
            "evidence": [
                {"source_path": "health.score", "value": c["health"]["score"], "supports": "current health"},
                {"source_path": "health.band", "value": c["health"]["band"], "supports": "band"},
                {"source_path": "contract.days_to_renewal", "value": days, "supports": "renewal proximity"},
                {"source_path": "relationship.champion.status", "value": champ_status, "supports": "champion status"},
            ] + ([{"source_path": f"relationship.stakeholders[{stakeholder_index}].contact_id", "value": exec_sponsor["contact_id"], "supports": "recipient is a current stakeholder"}] if exec_sponsor else []),
            "confidence": 0.5, "confidence_rationale": "offline stub; no model reasoning performed",
            "data_quality_flags": ["offline_stub"], "notes_for_csm": "Generated without Claude; run with ANTHROPIC_API_KEY for a real analysis.",
        }
        errors = validate_action(action, c360_view, schema_for(prompt_id, self.base_schema))
        if errors:
            raise ValueError(f"offline stub failed validation: {errors}")
        return ClaudeCallResult(action, "offline-stub", None, 0, 0, 0, 0, 0.0, 0)
