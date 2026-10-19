"""
Playbook triggers: the single executable definition of "when X happens, run Y".

`PLAYBOOKS` is the registry. `evaluate_triggers` applies it to one Customer 360 with the
precedence rules (P0 retention suppresses P3 expansion; RET-01 subsumes RET-02), opt-outs,
and cooldowns. `registry_table()` renders the same registry as the markdown table injected
into the orchestrator system prompt, so the prompt can never disagree with the code.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.catalogs import DEFAULT_BENCHMARKS
from src.validation import cooldown_active, get_path as _g, parse_iso_date

Predicate = Callable[[Dict[str, Any]], Optional[str]]


def _bench(c: Dict[str, Any], key: str, default: Any = None) -> Any:
    seg = _g(c, "account.segment", "mid_market")
    return (c.get("benchmarks") or {}).get(key, DEFAULT_BENCHMARKS.get(seg, {}).get(key, default))


def _score_is_usable(c: Dict[str, Any]) -> bool:
    """A score built on less than 60% of its weight is unknown, not a signal (see health_score.MIN_COVERAGE)."""
    return _g(c, "health.band") != "insufficient_data"


def trig_ret_01(c: Dict[str, Any]) -> Optional[str]:
    h, h30 = _g(c, "health.score", 100), _g(c, "health.score_30d_ago")
    usable = _score_is_usable(c)
    if _g(c, "health.band") == "red":
        return "health band red"
    if usable and h30 is not None and (h30 - h) >= 15:
        return f"health dropped {h30 - h:.0f} points in 30d"
    if _g(c, "relationship.champion.status") == "departed" and not _g(c, "relationship.champion.replacement_identified", False):
        return "champion departed without replacement"
    for t in _g(c, "support.open_tickets", []):
        if t.get("priority") == "P1" and (t.get("age_days") or 0) > 5:
            return f"P1 {t.get('ticket_id')} open {t.get('age_days')} days"
    if usable and _g(c, "contract.days_to_renewal", 999) <= 120 and h < 65:
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
    if _g(c, "lifecycle.stage") != "onboarding" or _g(c, "lifecycle.value_milestones_reached", []):
        return None
    days, p75 = _g(c, "lifecycle.days_since_term_start", 0), _bench(c, "ttv_p75_days", 35)
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
    due, as_of = parse_iso_date(_g(c, "cadence.next_ebr_due_at")), parse_iso_date(c.get("as_of_date"))
    if due and as_of:
        days = (due - as_of).days
        if 0 <= days <= 30:
            return f"EBR due in {days} days"
    if _g(c, "contract.days_to_renewal", 999) <= 180 and _g(c, "cadence.ebrs_completed_last_2_quarters", 0) == 0 and _g(c, "cadence.ebr_cadence") != "none":
        return "renewal within 180 days and no EBR in two quarters"
    return None


def _gate_hits(c: Dict[str, Any]) -> int:
    return sum(g.get("hits", 0) for g in _g(c, "usage.feature_gate_hits_14d", []))


def trig_exp_01(c: Dict[str, Any]) -> Optional[str]:
    if _g(c, "account.segment") not in ("smb", "digital") or _g(c, "health.band") == "red" or not _score_is_usable(c):
        return None
    if _g(c, "usage.seat_utilization", 0) >= 0.85:
        return "utilization ≥ 85%"
    if _gate_hits(c) >= 3:
        return f"{_gate_hits(c)} feature-gate hits in 14d"
    if (_g(c, "usage.pql_score") or 0) >= 70:
        return "PQL ≥ 70"
    if _g(c, "usage.dau_mau_30d", 0) >= 0.35:
        return "DAU/MAU ≥ 0.35"
    return None


def trig_exp_02(c: Dict[str, Any]) -> Optional[str]:
    if _g(c, "account.segment") not in ("enterprise", "mid_market"):
        return None
    if _g(c, "health.band") != "green" or _g(c, "usage.seat_utilization", 0) < 0.80 or _g(c, "contract.days_to_renewal", 999) <= 60:
        return None
    if any(o.get("type") in ("expansion", "upsell", "cross_sell") and not o.get("is_closed") for o in _g(c, "opportunities", [])):
        return None
    ws = c.get("whitespace") or {}
    if ws.get("unowned_modules") or ws.get("unowned_business_units"):
        return "green, utilization ≥ 80%, whitespace present, no open expansion opp"
    if _gate_hits(c) >= 3 or _g(c, "usage.seat_utilization", 0) >= 1.0:
        return "green, feature-gate hits or over-deployment"
    return None


@dataclass(frozen=True)
class PlaybookSpec:
    playbook_id: str
    name: str
    priority: str                # P0..P3 (also the precedence rank)
    cooldown_days: int
    prompt_chain: Tuple[str, ...]
    trigger: Predicate
    trigger_summary: str
    primary_artifact: str

    @property
    def priority_rank(self) -> int:
        return int(self.priority[1])


PLAYBOOKS: List[PlaybookSpec] = [
    PlaybookSpec("PB-RET-01", "Enterprise at-risk turnaround", "P0", 14, ("retention.churn_risk_rca", "retention.renewal_defense_playbook"), trig_ret_01,
                 "health red; drop ≥ 15 pts in 30d; champion departed, no successor; P1 open > 5d; renewal ≤ 120d and health < 65; ECRI ≥ 60",
                 "RCA + 30-day save plan + exec outreach draft"),
    PlaybookSpec("PB-RET-02", "Renewal defense (standard)", "P0", 30, ("retention.renewal_defense_playbook",), trig_ret_02,
                 "renewal ≤ 120d and (yellow, or utilization < 50%, or contraction in 90d)", "renewal plan + kickoff draft"),
    PlaybookSpec("PB-ADP-01", "TTV acceleration", "P1", 7, ("adoption.ttv_acceleration",), trig_adp_01,
                 "onboarding past segment p75 TTV with no value milestone", "unblock plan + check-in draft"),
    PlaybookSpec("PB-ADP-02", "Feature depth remediation", "P1", 21, ("adoption.feature_depth_audit",), trig_adp_02,
                 "depth ≤ green median − 0.15, or utilization drift ≤ −10 pts; not red; renewal > 120d", "feature audit + enablement plan"),
    PlaybookSpec("PB-CAD-01", "QBR / EBR automation", "P2", 60, ("adoption.feature_depth_audit", "expansion.executive_ebr_generator"), trig_cad_01,
                 "EBR due ≤ 30d; or renewal ≤ 180d with no EBR in 2 quarters", "narrative + slide script + ROI table + pre-read"),
    PlaybookSpec("PB-EXP-01", "Low-touch digital expansion", "P3", 30, ("expansion.whitespace_expansion_finder",), trig_exp_01,
                 "smb/digital; utilization ≥ 85%, gate hits ≥ 3, PQL ≥ 70, or DAU/MAU ≥ 0.35; not red", "expansion brief + nudge + handoff"),
    PlaybookSpec("PB-EXP-02", "Enterprise whitespace discovery", "P3", 45, ("expansion.whitespace_expansion_finder", "expansion.executive_ebr_generator"), trig_exp_02,
                 "enterprise/mid-market; green; utilization ≥ 80%; whitespace; no open expansion opp; renewal > 60d", "whitespace brief + expansion EBR"),
]
BY_ID: Dict[str, PlaybookSpec] = {p.playbook_id: p for p in PLAYBOOKS}


@dataclass(frozen=True)
class Fired:
    spec: PlaybookSpec
    reason: str
    signal_update_for: Optional[str] = None     # open action id when inside cooldown


def evaluate_triggers(c360: Dict[str, Any], only: Optional[str] = None, today: Optional[date] = None) -> List[Fired]:
    today = today or parse_iso_date(c360.get("as_of_date")) or date.today()
    opt_out = set(_g(c360, "account.cse_opt_out_playbooks", []))
    fired: List[Fired] = []
    for spec in PLAYBOOKS:
        if only and spec.playbook_id != only:
            continue
        if spec.playbook_id in opt_out:
            continue
        reason = spec.trigger(c360) or ("manual run" if only else None)
        if reason:
            fired.append(Fired(spec, reason))
    fired.sort(key=lambda f: f.spec.priority_rank)
    if any(f.spec.priority_rank == 0 for f in fired):
        fired = [f for f in fired if f.spec.priority_rank != 3]          # P0 suppresses expansion
    if any(f.spec.playbook_id == "PB-RET-01" for f in fired):
        fired = [f for f in fired if f.spec.playbook_id != "PB-RET-02"]   # RET-01 includes the renewal plan
    out: List[Fired] = []
    for f in fired:
        open_id = None if only else cooldown_active(f.spec.playbook_id, c360.get("actions_last_30d") or [], today)
        out.append(Fired(f.spec, f.reason, open_id))
    return out


def registry_table() -> str:
    """Markdown table of the registry for the orchestrator system prompt (generated, never hand-edited)."""
    rows = ["| id | name | priority | cooldown | trigger (any) | prompt chain | primary artifact |", "|---|---|---|---|---|---|---|"]
    for p in PLAYBOOKS:
        rows.append(f"| {p.playbook_id} | {p.name} | {p.priority} | {p.cooldown_days}d | {p.trigger_summary} | {' → '.join(p.prompt_chain)} | {p.primary_artifact} |")
    rows.append("| ADHOC | Ad hoc analysis | none | none | user request | any | as requested |")
    return "\n".join(rows)
