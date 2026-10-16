"""
Weighted multi-variable Customer Health Score.

Implements docs/02_METRICS_TAXONOMY.md §B1 exactly. The same formula is implemented in
sql/dbt_marts/mart_customer_health_daily.sql; the orchestrator asserts the two agree
within 0.5 points (see `assert_no_drift`).

Design principles
-----------------
* Linear and additive: every point of the final score is attributable to exactly one
  component. `HealthScoreResult.components` carries the contribution of each so Claude
  can explain the score without re-deriving it.
* Hard-gate overrides cap the score; they never floor it.
* Missing inputs re-normalize within a component rather than silently scoring zero.
* No I/O except in the CLI entry point.

Usage
-----
    from src.models.health_score import compute_health_score
    result = compute_health_score(customer_360_dict)
    result.score, result.band, result.components, result.overrides_applied

    python -m src.models.health_score examples/sample_customer_360.json
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


# --------------------------------------------------------------------------------------
# Weights
# --------------------------------------------------------------------------------------

DEFAULT_WEIGHTS: Dict[str, float] = {
    "adoption": 0.25,
    "engagement": 0.15,
    "support": 0.15,
    "sentiment": 0.15,
    "relationship": 0.15,
    "commercial": 0.15,
}

BAND_GREEN_MIN = 75.0
BAND_YELLOW_MIN = 50.0

TREND_COEFFICIENT = 0.25
TREND_CLAMP = 8.0


class HealthScoreDriftError(RuntimeError):
    """Raised when the Python score disagrees with the warehouse mart beyond tolerance."""


@dataclass
class HealthWeights:
    adoption: float = DEFAULT_WEIGHTS["adoption"]
    engagement: float = DEFAULT_WEIGHTS["engagement"]
    support: float = DEFAULT_WEIGHTS["support"]
    sentiment: float = DEFAULT_WEIGHTS["sentiment"]
    relationship: float = DEFAULT_WEIGHTS["relationship"]
    commercial: float = DEFAULT_WEIGHTS["commercial"]

    def as_dict(self) -> Dict[str, float]:
        return asdict(self)

    def validate(self) -> None:
        total = sum(self.as_dict().values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"Health weights must sum to 1.0; got {total:.6f}")
        for k, v in self.as_dict().items():
            if v < 0:
                raise ValueError(f"Weight {k} must be non-negative; got {v}")

    @classmethod
    def from_dict(cls, d: Dict[str, float]) -> "HealthWeights":
        w = cls(**{k: float(d.get(k, DEFAULT_WEIGHTS[k])) for k in DEFAULT_WEIGHTS})
        w.validate()
        return w

    @classmethod
    def load(cls, path: Optional[str] = None) -> "HealthWeights":
        """Load weights exported from dbt (config/health_weights.json); fall back to defaults."""
        if path is None:
            path = str(Path(__file__).resolve().parents[2] / "config" / "health_weights.json")
        p = Path(path)
        if p.exists():
            with p.open() as fh:
                return cls.from_dict(json.load(fh))
        return cls()


# --------------------------------------------------------------------------------------
# Normalizers (all return 0..100)
# --------------------------------------------------------------------------------------

def clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def linear(x: Optional[float], x0: float, x1: float, y0: float = 0.0, y1: float = 100.0) -> Optional[float]:
    """Linear map x0→y0, x1→y1, clamped to [min(y0,y1), max(y0,y1)]. None in → None out."""
    if x is None:
        return None
    if x1 == x0:
        return y1
    y = y0 + (float(x) - x0) * (y1 - y0) / (x1 - x0)
    return clamp(y, min(y0, y1), max(y0, y1))


def piecewise(x: Optional[float], points: Sequence[Tuple[float, float]]) -> Optional[float]:
    """Piecewise-linear interpolation through sorted (x, y) points; flat beyond the ends."""
    if x is None:
        return None
    x = float(x)
    if x <= points[0][0]:
        return float(points[0][1])
    if x >= points[-1][0]:
        return float(points[-1][1])
    for (xa, ya), (xb, yb) in zip(points, points[1:]):
        if xa <= x <= xb:
            if xb == xa:
                return float(yb)
            return ya + (x - xa) * (yb - ya) / (xb - xa)
    return float(points[-1][1])


def weighted_mean(pairs: Sequence[Tuple[Optional[float], float]]) -> Optional[float]:
    """Weighted mean that re-normalizes over non-None values. Returns None if all are None."""
    num, den = 0.0, 0.0
    for value, weight in pairs:
        if value is None:
            continue
        num += value * weight
        den += weight
    return num / den if den > 0 else None


def mean_available(values: Sequence[Optional[float]]) -> Optional[float]:
    present = [v for v in values if v is not None]
    return sum(present) / len(present) if present else None


# --------------------------------------------------------------------------------------
# Component scorers
# --------------------------------------------------------------------------------------

@dataclass
class ComponentScore:
    name: str
    normalized: float            # 0..100 (0 if no inputs at all, flagged in explanation)
    weight: float
    contribution: float          # normalized * weight
    raw_inputs: Dict[str, Any] = field(default_factory=dict)
    sub_scores: Dict[str, Optional[float]] = field(default_factory=dict)
    explanation: str = ""
    inputs_missing: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "normalized": round(self.normalized, 2),
            "weight": self.weight,
            "contribution": round(self.contribution, 2),
            "raw_inputs": self.raw_inputs,
            "explanation": self.explanation,
        }


def _get(d: Dict[str, Any], *path: str, default: Any = None) -> Any:
    cur: Any = d
    for key in path:
        if not isinstance(cur, dict) or key not in cur or cur[key] is None:
            return default
        cur = cur[key]
    return cur


def score_adoption(c360: Dict[str, Any], weight: float) -> ComponentScore:
    usage = c360.get("usage", {})
    dau_mau = _get(usage, "dau_mau_30d")
    depth = _get(usage, "feature_depth_30d")
    util = _get(usage, "seat_utilization")

    s_dau = linear(dau_mau, 0.05, 0.40)
    s_depth = None if depth is None else clamp(float(depth) * 100.0)
    s_util = linear(util, 0.30, 0.90)  # capped at 100 by linear(); over-utilization is an expansion signal

    normalized = mean_available([s_dau, s_depth, s_util])
    missing = [k for k, v in (("dau_mau_30d", dau_mau), ("feature_depth_30d", depth), ("seat_utilization", util)) if v is None]
    expl = (
        f"DAU/MAU {dau_mau} → {None if s_dau is None else round(s_dau)}; "
        f"feature depth {depth} → {None if s_depth is None else round(s_depth)}; "
        f"seat utilization {util} → {None if s_util is None else round(s_util)}; mean of available."
    )
    n = normalized if normalized is not None else 0.0
    return ComponentScore("adoption", n, weight, n * weight,
                          {"dau_mau_30d": dau_mau, "feature_depth_30d": depth, "seat_utilization": util},
                          {"dau_mau": s_dau, "depth": s_depth, "utilization": s_util}, expl, missing)


def score_engagement(c360: Dict[str, Any], weight: float) -> ComponentScore:
    usage = c360.get("usage", {})
    rel = c360.get("relationship", {})
    days_login = _get(usage, "days_since_last_login")
    engaged_contacts = None
    stakeholders = rel.get("stakeholders") or []
    if stakeholders:
        engaged_contacts = sum(1 for s in stakeholders if (s.get("engagements_90d") or 0) > 0)
    exec_engaged = _get(rel, "exec_sponsor_engaged_180d")

    s_login = piecewise(days_login, [(0, 100), (14, 50), (30, 0)])
    s_contacts = piecewise(engaged_contacts, [(0, 0), (1, 20), (2, 50), (3, 75), (4, 100)])
    s_exec = None if exec_engaged is None else (100.0 if exec_engaged else 0.0)

    normalized = weighted_mean([(s_login, 0.4), (s_contacts, 0.3), (s_exec, 0.3)])
    missing = [k for k, v in (("days_since_last_login", days_login), ("engaged_contacts_90d", engaged_contacts), ("exec_sponsor_engaged_180d", exec_engaged)) if v is None]
    expl = (
        f"Last login {days_login}d → {None if s_login is None else round(s_login)} (w .4); "
        f"engaged contacts {engaged_contacts} → {None if s_contacts is None else round(s_contacts)} (w .3); "
        f"exec engaged {exec_engaged} → {None if s_exec is None else round(s_exec)} (w .3)."
    )
    n = normalized if normalized is not None else 0.0
    return ComponentScore("engagement", n, weight, n * weight,
                          {"days_since_last_login": days_login, "engaged_contacts_90d": engaged_contacts, "exec_sponsor_engaged_180d": exec_engaged},
                          {"login": s_login, "contacts": s_contacts, "exec": s_exec}, expl, missing)


def score_support(c360: Dict[str, Any], weight: float) -> ComponentScore:
    sup = c360.get("support", {})
    open_tickets = sup.get("open_tickets") or []
    p1p2_open = sum(1 for t in open_tickets if t.get("priority") in ("P1", "P2"))
    per_100 = _get(sup, "tickets_per_100_seats_30d")
    csat = _get(sup, "avg_csat_90d")
    frt = _get(sup, "median_first_response_hours_90d")

    s_p1p2 = piecewise(p1p2_open, [(0, 100), (1, 60), (2, 20)])
    s_volume = linear(per_100, 2.0, 10.0, 100.0, 0.0)
    s_csat = None if csat is None else clamp((float(csat) - 1.0) / 4.0 * 100.0)
    s_frt = linear(frt, 4.0, 48.0, 100.0, 0.0)

    normalized = mean_available([s_p1p2, s_volume, s_csat, s_frt])
    missing = [k for k, v in (("tickets_per_100_seats_30d", per_100), ("avg_csat_90d", csat), ("median_first_response_hours_90d", frt)) if v is None]
    expl = (
        f"Open P1/P2 {p1p2_open} → {round(s_p1p2)}; tickets/100 seats {per_100} → {None if s_volume is None else round(s_volume)}; "
        f"CSAT {csat} → {None if s_csat is None else round(s_csat)}; first response {frt}h → {None if s_frt is None else round(s_frt)}; mean of available."
    )
    n = normalized if normalized is not None else 0.0
    return ComponentScore("support", n, weight, n * weight,
                          {"open_p1_p2": p1p2_open, "tickets_per_100_seats_30d": per_100, "avg_csat_90d": csat, "median_first_response_hours_90d": frt},
                          {"p1p2": s_p1p2, "volume": s_volume, "csat": s_csat, "first_response": s_frt}, expl, missing)


def score_sentiment(c360: Dict[str, Any], weight: float) -> ComponentScore:
    sent = c360.get("sentiment", {})
    nps = _get(sent, "latest_nps")
    trend = _get(sent, "nps_trend")
    transcript = _get(sent, "transcript_sentiment_30d")

    s_nps = None if nps is None else clamp((float(nps) + 100.0) / 2.0)
    trend_adj = {"improving": 10.0, "worsening": -10.0}.get(trend, 0.0) if trend is not None else None
    s_trend = None if trend_adj is None else clamp(50.0 + trend_adj * 5.0)  # expressed on 0..100 for the weighted mean: 50 neutral, 100 improving, 0 worsening
    s_transcript = None if transcript is None else clamp((float(transcript) + 1.0) / 2.0 * 100.0)

    normalized = weighted_mean([(s_nps, 0.5), (s_trend, 0.1), (s_transcript, 0.4)])
    missing = [k for k, v in (("latest_nps", nps), ("nps_trend", trend), ("transcript_sentiment_30d", transcript)) if v is None]
    expl = (
        f"NPS {nps} → {None if s_nps is None else round(s_nps)} (w .5); trend {trend} → {None if s_trend is None else round(s_trend)} (w .1); "
        f"transcript sentiment {transcript} → {None if s_transcript is None else round(s_transcript)} (w .4); weights re-normalized over available inputs."
    )
    n = normalized if normalized is not None else 0.0
    return ComponentScore("sentiment", n, weight, n * weight,
                          {"latest_nps": nps, "nps_trend": trend, "transcript_sentiment_30d": transcript},
                          {"nps": s_nps, "trend": s_trend, "transcript": s_transcript}, expl, missing)


def score_relationship(c360: Dict[str, Any], weight: float) -> ComponentScore:
    rel = c360.get("relationship", {})
    champion_status = _get(rel, "champion", "status")
    depth = _get(rel, "multithreading_depth")
    days_touch = _get(rel, "days_since_last_csm_touch")

    s_champion = {"active": 100.0, "at_risk": 50.0, "none": 30.0, "departed": 0.0}.get(champion_status) if champion_status else None
    s_depth = piecewise(depth, [(0, 0), (1, 20), (2, 50), (3, 75), (4, 100)])
    s_touch = linear(days_touch, 14.0, 45.0, 100.0, 0.0)

    normalized = weighted_mean([(s_champion, 0.5), (s_depth, 0.3), (s_touch, 0.2)])
    missing = [k for k, v in (("champion.status", champion_status), ("multithreading_depth", depth), ("days_since_last_csm_touch", days_touch)) if v is None]
    expl = (
        f"Champion {champion_status} → {None if s_champion is None else round(s_champion)} (w .5); depth {depth} → {None if s_depth is None else round(s_depth)} (w .3); "
        f"CSM touch {days_touch}d → {None if s_touch is None else round(s_touch)} (w .2)."
    )
    n = normalized if normalized is not None else 0.0
    return ComponentScore("relationship", n, weight, n * weight,
                          {"champion_status": champion_status, "multithreading_depth": depth, "days_since_last_csm_touch": days_touch},
                          {"champion": s_champion, "depth": s_depth, "csm_touch": s_touch}, expl, missing)


def score_commercial(c360: Dict[str, Any], weight: float) -> ComponentScore:
    con = c360.get("contract", {})
    days_renewal = _get(con, "days_to_renewal")
    past_due = _get(con, "payment_days_past_due", default=0)
    contraction = bool(_get(con, "contraction_flag_90d", default=False))

    s_renewal = piecewise(days_renewal, [(0, 40), (30, 60), (90, 80), (180, 100)])
    s_past_due = piecewise(past_due, [(0, 100), (30, 60), (60, 0)])
    base = mean_available([s_renewal, s_past_due])
    normalized = None if base is None else clamp(base - (30.0 if contraction else 0.0))
    missing = [k for k, v in (("days_to_renewal", days_renewal),) if v is None]
    expl = (
        f"Days to renewal {days_renewal} → {None if s_renewal is None else round(s_renewal)}; payment past due {past_due}d → {None if s_past_due is None else round(s_past_due)}; "
        f"mean{' minus 30 for 90d contraction' if contraction else ''}."
    )
    n = normalized if normalized is not None else 0.0
    return ComponentScore("commercial", n, weight, n * weight,
                          {"days_to_renewal": days_renewal, "payment_days_past_due": past_due, "contraction_flag_90d": contraction},
                          {"renewal_proximity": s_renewal, "past_due": s_past_due}, expl, missing)


# --------------------------------------------------------------------------------------
# Overrides (caps)
# --------------------------------------------------------------------------------------

@dataclass
class Override:
    rule: str
    cap: float

    def to_dict(self) -> Dict[str, Any]:
        return {"rule": self.rule, "cap": self.cap}


def evaluate_overrides(c360: Dict[str, Any]) -> List[Override]:
    overrides: List[Override] = []
    rel = c360.get("relationship", {})
    con = c360.get("contract", {})
    sup = c360.get("support", {})
    usage = c360.get("usage", {})

    champ = rel.get("champion") or {}
    if champ.get("status") == "departed" and not champ.get("replacement_identified", False):
        overrides.append(Override("champion_departed_no_replacement", 60.0))

    if (con.get("payment_days_past_due") or 0) > 60:
        overrides.append(Override("payment_past_due_over_60d", 50.0))

    for t in sup.get("open_tickets") or []:
        if t.get("priority") == "P1" and (t.get("age_days") or 0) > 5:
            overrides.append(Override("open_p1_older_than_5d", 65.0))
            break

    util_now = usage.get("seat_utilization")
    util_90 = usage.get("seat_utilization_90d_ago")
    arr = con.get("arr") or 0
    if util_now is not None and util_90 is not None and util_now < 0.20 and util_90 < 0.20 and arr > 50_000:
        overrides.append(Override("utilization_under_20pct_60d_on_50k_plus", 55.0))

    return overrides


# --------------------------------------------------------------------------------------
# Result
# --------------------------------------------------------------------------------------

@dataclass
class HealthScoreResult:
    score: float
    band: str
    raw_weighted_sum: float
    trend_adjustment: float
    components: List[ComponentScore]
    overrides_applied: List[Override]
    score_30d_ago: Optional[float]
    inputs_missing: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "score": round(self.score, 2),
            "band": self.band,
            "raw_weighted_sum": round(self.raw_weighted_sum, 2),
            "trend_adjustment": round(self.trend_adjustment, 2),
            "components": [c.to_dict() for c in self.components],
            "overrides_applied": [o.to_dict() for o in self.overrides_applied],
            "score_30d_ago": self.score_30d_ago,
            "inputs_missing": self.inputs_missing,
        }

    def explain(self) -> str:
        lines = [f"Health score {self.score:.1f} ({self.band.upper()})"]
        if self.score_30d_ago is not None:
            lines.append(f"  30-day delta: {self.score - self.score_30d_ago:+.1f} (trend adjustment {self.trend_adjustment:+.1f})")
        for c in sorted(self.components, key=lambda c: c.contribution, reverse=True):
            lines.append(f"  {c.name:<13} {c.normalized:6.1f} × {c.weight:.2f} = {c.contribution:6.2f}   {c.explanation}")
        if self.overrides_applied:
            lines.append("  Overrides: " + ", ".join(f"{o.rule} (cap {o.cap:.0f})" for o in self.overrides_applied))
        if self.inputs_missing:
            lines.append("  Missing inputs: " + ", ".join(self.inputs_missing))
        return "\n".join(lines)


def band_for(score: float) -> str:
    if score >= BAND_GREEN_MIN:
        return "green"
    if score >= BAND_YELLOW_MIN:
        return "yellow"
    return "red"


def compute_health_score(c360: Dict[str, Any], weights: Optional[HealthWeights] = None) -> HealthScoreResult:
    """
    Compute the health score for one Customer 360 document.

    The 30-day trend uses `health.score_30d_ago` from the document (the mart's prior score),
    which is the best available proxy for the prior raw weighted sum; the orchestrator
    writes the raw sum back so future runs can use it directly if present
    (`health.raw_weighted_sum_30d_ago`).
    """
    w = weights or HealthWeights()
    w.validate()
    wd = w.as_dict()

    components = [
        score_adoption(c360, wd["adoption"]),
        score_engagement(c360, wd["engagement"]),
        score_support(c360, wd["support"]),
        score_sentiment(c360, wd["sentiment"]),
        score_relationship(c360, wd["relationship"]),
        score_commercial(c360, wd["commercial"]),
    ]
    raw = sum(c.contribution for c in components)

    health_block = c360.get("health") or {}
    prior_raw = health_block.get("raw_weighted_sum_30d_ago")
    prior_score = health_block.get("score_30d_ago")
    reference_prior = prior_raw if prior_raw is not None else prior_score
    trend_adj = 0.0
    if reference_prior is not None:
        trend_adj = clamp((raw - float(reference_prior)) * TREND_COEFFICIENT, -TREND_CLAMP, TREND_CLAMP)

    score = clamp(raw + trend_adj)
    overrides = evaluate_overrides(c360)
    for o in overrides:
        score = min(score, o.cap)

    missing = [f"{c.name}.{m}" for c in components for m in c.inputs_missing]
    return HealthScoreResult(
        score=score,
        band=band_for(score),
        raw_weighted_sum=raw,
        trend_adjustment=trend_adj,
        components=components,
        overrides_applied=overrides,
        score_30d_ago=prior_score,
        inputs_missing=missing,
    )


def assert_no_drift(result: HealthScoreResult, mart_score: Optional[float], tolerance: float = 0.5) -> None:
    """Raise HealthScoreDriftError if the Python score and the warehouse mart disagree."""
    if mart_score is None:
        return
    delta = abs(result.score - float(mart_score))
    if delta > tolerance:
        raise HealthScoreDriftError(
            f"Health score drift {delta:.2f} > {tolerance}: python={result.score:.2f} mart={mart_score:.2f}. "
            "Check dbt vars.health_weights vs config/health_weights.json and normalizer parity."
        )


def attach_to_customer_360(c360: Dict[str, Any], result: HealthScoreResult) -> Dict[str, Any]:
    """Return a copy of the document with `health` replaced by the recomputed result (mart score preserved)."""
    out = dict(c360)
    health = dict(out.get("health") or {})
    health.update({
        "score": round(result.score, 2),
        "band": result.band,
        "trend_adjustment": round(result.trend_adjustment, 2),
        "components": [c.to_dict() for c in result.components],
        "overrides_applied": [o.to_dict() for o in result.overrides_applied],
        # Persisted so the next run can use the uncapped prior sum for the trend (see docs/02 §B1).
        "raw_weighted_sum": round(result.raw_weighted_sum, 2),
    })
    health.setdefault("score_30d_ago", result.score_30d_ago)
    health.setdefault("score_90d_ago", None)
    out["health"] = health
    return out


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------

def _main(argv: List[str]) -> int:
    if len(argv) < 2:
        print("usage: python -m src.models.health_score <customer_360.json> [--weights config/health_weights.json] [--json]", file=sys.stderr)
        return 2
    path = Path(argv[1])
    weights_path = None
    as_json = "--json" in argv
    if "--weights" in argv:
        weights_path = argv[argv.index("--weights") + 1]
    with path.open() as fh:
        doc = json.load(fh)
    weights = HealthWeights.load(weights_path) if weights_path else HealthWeights.load()
    result = compute_health_score(doc, weights)
    try:
        assert_no_drift(result, (doc.get("health") or {}).get("mart_score"))
        drift_note = "drift check: OK"
    except HealthScoreDriftError as e:
        drift_note = f"drift check: FAILED — {e}"
    if as_json:
        out = result.to_dict()
        out["drift_check"] = drift_note
        print(json.dumps(out, indent=2))
    else:
        print(result.explain())
        print("  " + drift_note)
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
