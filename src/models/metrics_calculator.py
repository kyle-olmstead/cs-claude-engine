"""
Retention, adoption, sentiment, and capacity metrics — the Python mirror of
docs/02_METRICS_TAXONOMY.md.

Every function is pure, typed, and stdlib-only so it can run inside the orchestrator,
a notebook, a dbt Python model, or a unit test with no dependencies.

Sections
--------
A. Retention & revenue (lagging): cohort NRR/GRR, logo vs dollar churn, pipeline velocity
B. Adoption (leading): DAU/MAU, feature depth/breadth, utilization + drift, time to value
C. Sentiment & alignment: NPS, CSAT, Executive Champion Risk Index, multithreading depth
D. Capacity & efficiency: ARR per CSM + balance, CRC, LTV:CAC, QBR completion velocity

    python -m src.models.metrics_calculator --demo
"""

from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timedelta
from statistics import median, pstdev, mean
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


# ======================================================================================
# A. Retention & revenue
# ======================================================================================

@dataclass(frozen=True)
class ARRSnapshot:
    """ARR for one account at one point in time. ARR of 0 at t1 means churned."""
    account_id: str
    arr: float
    segment: str = "all"


@dataclass
class RetentionResult:
    period_start: str
    period_end: str
    segment: str
    cohort_logos: int
    start_arr: float
    end_arr_cohort: float
    expansion_arr: float
    contraction_arr: float
    churn_arr: float
    churned_logos: int
    new_logo_arr: float
    new_logos: int
    nrr: Optional[float]
    grr: Optional[float]
    logo_churn_rate: Optional[float]
    dollar_churn_rate: Optional[float]
    net_dollar_churn: Optional[float]
    churn_concentration: Optional[float]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _safe_div(n: float, d: float) -> Optional[float]:
    return (n / d) if d else None


def net_revenue_retention(start_arr: float, expansion: float, contraction: float, churn: float) -> Optional[float]:
    """NRR = (start + expansion − contraction − churn) / start."""
    return _safe_div(start_arr + expansion - contraction - churn, start_arr)


def gross_revenue_retention(start_arr: float, contraction: float, churn: float) -> Optional[float]:
    """GRR = (start − contraction − churn) / start, capped at 1.0."""
    v = _safe_div(start_arr - contraction - churn, start_arr)
    return None if v is None else min(v, 1.0)


def logo_churn_rate(churned_logos: int, cohort_logos: int) -> Optional[float]:
    return _safe_div(churned_logos, cohort_logos)


def dollar_churn_rate(churn_arr: float, start_arr: float) -> Optional[float]:
    return _safe_div(churn_arr, start_arr)


def net_dollar_churn(churn_arr: float, contraction_arr: float, expansion_arr: float, start_arr: float) -> Optional[float]:
    """= 1 − NRR."""
    return _safe_div(churn_arr + contraction_arr - expansion_arr, start_arr)


def cohort_retention(
    t0: Iterable[ARRSnapshot],
    t1: Iterable[ARRSnapshot],
    period_start: str,
    period_end: str,
    segment: str = "all",
) -> RetentionResult:
    """
    Compute the full retention decomposition for the cohort of accounts with ARR > 0 at t0.

    Accounts present at t1 but absent (or 0) at t0 are new logos — reported but excluded
    from NRR/GRR per the taxonomy. Accounts in the cohort absent from t1 are treated as churned.
    """
    start = {s.account_id: s.arr for s in t0 if s.arr > 0}
    end = {s.account_id: s.arr for s in t1}

    start_arr = sum(start.values())
    end_arr_cohort = expansion = contraction = churn = 0.0
    churned_logos = 0
    for acct, a0 in start.items():
        a1 = end.get(acct, 0.0)
        end_arr_cohort += a1
        if a1 <= 0:
            churn += a0
            churned_logos += 1
        elif a1 > a0:
            expansion += a1 - a0
        elif a1 < a0:
            contraction += a0 - a1

    new_logo_arr = sum(a1 for acct, a1 in end.items() if acct not in start and a1 > 0)
    new_logos = sum(1 for acct, a1 in end.items() if acct not in start and a1 > 0)

    nrr = net_revenue_retention(start_arr, expansion, contraction, churn)
    grr = gross_revenue_retention(start_arr, contraction, churn)
    lcr = logo_churn_rate(churned_logos, len(start))
    dcr = dollar_churn_rate(churn, start_arr)
    ndc = net_dollar_churn(churn, contraction, expansion, start_arr)
    concentration = _safe_div(dcr, lcr) if (dcr is not None and lcr) else None

    return RetentionResult(
        period_start=period_start, period_end=period_end, segment=segment,
        cohort_logos=len(start), start_arr=start_arr, end_arr_cohort=end_arr_cohort,
        expansion_arr=expansion, contraction_arr=contraction, churn_arr=churn,
        churned_logos=churned_logos, new_logo_arr=new_logo_arr, new_logos=new_logos,
        nrr=nrr, grr=grr, logo_churn_rate=lcr, dollar_churn_rate=dcr,
        net_dollar_churn=ndc, churn_concentration=concentration,
    )


def cohort_retention_by_segment(
    t0: Sequence[ARRSnapshot], t1: Sequence[ARRSnapshot], period_start: str, period_end: str
) -> List[RetentionResult]:
    """One RetentionResult per segment plus an 'all' roll-up."""
    segments = sorted({s.segment for s in t0} | {s.segment for s in t1})
    results = [cohort_retention(t0, t1, period_start, period_end, "all")]
    for seg in segments:
        results.append(cohort_retention(
            [s for s in t0 if s.segment == seg], [s for s in t1 if s.segment == seg],
            period_start, period_end, seg,
        ))
    return results


@dataclass(frozen=True)
class Opportunity:
    opportunity_id: str
    account_id: str
    type: str                 # new | renewal | expansion | upsell | cross_sell
    amount: float
    created_at: date
    close_date: Optional[date]
    is_closed: bool
    is_won: Optional[bool]
    segment: str = "all"


EXPANSION_TYPES = ("expansion", "upsell", "cross_sell")


@dataclass
class PipelineVelocity:
    open_opps: int
    open_pipeline_arr: float
    avg_deal_size: float
    win_rate: float
    avg_cycle_days: float
    velocity_per_day: float
    closed_sample_size: int
    low_confidence: bool
    coverage_ratio: Optional[float]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def expansion_pipeline_velocity(
    opportunities: Sequence[Opportunity],
    as_of: date,
    window_days: int = 180,
    remaining_quota: Optional[float] = None,
    fallback_win_rate: float = 0.30,
    fallback_cycle_days: float = 60.0,
    min_sample: int = 20,
) -> PipelineVelocity:
    """
    Velocity ($/day) = (N_open × avg_deal_size × win_rate) / avg_cycle_days.

    win_rate and avg_cycle_days come from closed expansion-type opps in the trailing window.
    Below `min_sample` closed opps, fall back to the supplied company-wide rates and flag.
    """
    exp = [o for o in opportunities if o.type in EXPANSION_TYPES]
    open_opps = [o for o in exp if not o.is_closed]
    window_start = as_of - timedelta(days=window_days)
    closed = [o for o in exp if o.is_closed and o.close_date and window_start <= o.close_date <= as_of]
    won = [o for o in closed if o.is_won]

    sample = len(closed)
    low_conf = sample < min_sample
    win_rate = (len(won) / sample) if (sample and not low_conf) else fallback_win_rate
    cycle = mean((o.close_date - o.created_at).days for o in won if o.close_date) if (won and not low_conf) else fallback_cycle_days
    cycle = max(cycle, 1.0)

    open_arr = sum(o.amount for o in open_opps)
    avg_deal = (open_arr / len(open_opps)) if open_opps else 0.0
    velocity = (len(open_opps) * avg_deal * win_rate) / cycle
    coverage = _safe_div(open_arr, remaining_quota) if remaining_quota else None

    return PipelineVelocity(
        open_opps=len(open_opps), open_pipeline_arr=open_arr, avg_deal_size=avg_deal,
        win_rate=win_rate, avg_cycle_days=cycle, velocity_per_day=velocity,
        closed_sample_size=sample, low_confidence=low_conf, coverage_ratio=coverage,
    )


# ======================================================================================
# B. Adoption
# ======================================================================================

def dau_mau_ratio(daily_active_users: Sequence[int], monthly_active_users: int, business_days_only: bool = False,
                  dates: Optional[Sequence[date]] = None) -> Optional[float]:
    """
    (mean DAU over the window) / MAU. With business_days_only, weekend days are dropped
    from the mean (dates required).
    """
    if monthly_active_users <= 0 or not daily_active_users:
        return None
    if business_days_only:
        if dates is None or len(dates) != len(daily_active_users):
            raise ValueError("dates must be supplied, one per DAU value, for business_days_only")
        pairs = [(d, v) for d, v in zip(dates, daily_active_users) if d.weekday() < 5]
        if not pairs:
            return None
        avg_dau = mean(v for _, v in pairs)
    else:
        avg_dau = mean(daily_active_users)
    return min(avg_dau / monthly_active_users, 1.0)


@dataclass
class FeatureAdoption:
    depth: float
    breadth: float
    power_user_ratio: Optional[float]
    core_used: List[str]
    core_unused: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def feature_depth(
    features_used: Iterable[str],
    core_features: Iterable[str],
    all_features: Iterable[str],
    users_core_feature_counts: Optional[Dict[str, int]] = None,
    mau: Optional[int] = None,
    power_user_threshold: int = 3,
) -> FeatureAdoption:
    """
    depth   = |core features used| / |core features|
    breadth = |all features used|  / |all features|
    power_user_ratio = |users using ≥ threshold core features| / MAU
    """
    used = set(features_used)
    core = set(core_features)
    allf = set(all_features) | core
    core_used = sorted(used & core)
    depth = len(core_used) / len(core) if core else 0.0
    breadth = len(used & allf) / len(allf) if allf else 0.0
    pur = None
    if users_core_feature_counts is not None and mau:
        pur = sum(1 for n in users_core_feature_counts.values() if n >= power_user_threshold) / mau
    return FeatureAdoption(depth=depth, breadth=breadth, power_user_ratio=pur,
                           core_used=core_used, core_unused=sorted(core - used))


def seat_utilization(active_seats_30d: int, seats_purchased: int) -> Optional[float]:
    """Not capped at 1.0: > 1.0 is over-deployment, an expansion signal."""
    return _safe_div(active_seats_30d, seats_purchased)


def utilization_drift(utilization_now: Optional[float], utilization_90d_ago: Optional[float]) -> Optional[float]:
    if utilization_now is None or utilization_90d_ago is None:
        return None
    return utilization_now - utilization_90d_ago


def classify_utilization(utilization: Optional[float], drift: Optional[float], arr: float, days_under_20pct: int = 0) -> str:
    """Maps the taxonomy §B5 table to a signal label."""
    if utilization is None:
        return "unknown"
    if utilization < 0.20 and days_under_20pct >= 60 and arr > 50_000:
        return "hard_gate_cap_55"
    if utilization >= 0.85:
        return "expansion_ready"
    if utilization < 0.50:
        return "contraction_risk"
    if drift is not None and drift >= 0.10:
        return "growing"
    if drift is not None and drift <= -0.10:
        return "adoption_erosion"
    return "stable"


@dataclass
class TimeToValue:
    ttv_days: Optional[int]
    milestone_key: Optional[str]
    reached: bool
    days_elapsed: int
    past_p50: bool
    past_p75: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def time_to_value(
    term_start: date,
    milestones_reached: Dict[str, date],
    primary_milestones: Sequence[str],
    as_of: date,
    segment_p50_days: int,
    segment_p75_days: int,
) -> TimeToValue:
    """TTV = earliest primary milestone date − term start. If none reached, report elapsed days vs. benchmarks."""
    reached = [(k, d) for k, d in milestones_reached.items() if k in primary_milestones]
    elapsed = (as_of - term_start).days
    if reached:
        k, d = min(reached, key=lambda kd: kd[1])
        ttv = (d - term_start).days
        return TimeToValue(ttv, k, True, elapsed, ttv > segment_p50_days, ttv > segment_p75_days)
    return TimeToValue(None, None, False, elapsed, elapsed > segment_p50_days, elapsed > segment_p75_days)


def ttv_distribution(ttv_days: Sequence[int]) -> Dict[str, Optional[float]]:
    if not ttv_days:
        return {"p50": None, "p75": None, "n": 0}
    s = sorted(ttv_days)
    def pct(p: float) -> float:
        idx = (len(s) - 1) * p
        lo, hi = math.floor(idx), math.ceil(idx)
        return s[lo] + (s[hi] - s[lo]) * (idx - lo)
    return {"p50": pct(0.5), "p75": pct(0.75), "n": len(s)}


# ======================================================================================
# C. Sentiment & alignment
# ======================================================================================

SENIORITY_WEIGHTS = {"c_level": 2.0, "vp": 2.0, "director": 1.5, "manager": 1.5, "individual_contributor": 1.0, "unknown": 1.0}


def nps_score(scores: Sequence[int], weights: Optional[Sequence[float]] = None) -> Optional[int]:
    """NPS = %promoters (9–10) − %detractors (0–6), optionally seniority-weighted. Returns an int −100..100."""
    if not scores:
        return None
    w = list(weights) if weights is not None else [1.0] * len(scores)
    if len(w) != len(scores):
        raise ValueError("weights must align with scores")
    total = sum(w)
    if total <= 0:
        return None
    promoters = sum(wi for s, wi in zip(scores, w) if s >= 9)
    detractors = sum(wi for s, wi in zip(scores, w) if s <= 6)
    return int(round((promoters - detractors) / total * 100))


def csat_rate(scores: Sequence[float], scale_max: int = 5) -> Optional[float]:
    """Share of responses at or above the satisfied threshold (4/5 or 8/10)."""
    if not scores:
        return None
    threshold = 4 if scale_max == 5 else 8
    return sum(1 for s in scores if s >= threshold) / len(scores)


@dataclass
class ChampionRiskIndex:
    ecri: float
    job_change: float
    disengagement: float
    single_thread: float
    no_exec_sponsor: float
    tenure: float
    champion_departed: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def champion_risk_index(
    champion_departed: bool,
    champion_title_changed_to_non_buyer: bool,
    days_since_champion_engaged: Optional[int],
    multithreading_depth: int,
    exec_sponsor_engaged_180d: bool,
    champion_tenure_months: Optional[int],
) -> ChampionRiskIndex:
    """
    ECRI = 100 × (0.35·JobChange + 0.20·Disengagement + 0.20·SingleThread + 0.15·NoExecSponsor + 0.10·Tenure)
    """
    job_change = 1.0 if champion_departed else (0.6 if champion_title_changed_to_non_buyer else 0.0)
    if days_since_champion_engaged is None:
        disengagement = 1.0
    elif days_since_champion_engaged <= 30:
        disengagement = 0.0
    else:
        disengagement = min(1.0, (days_since_champion_engaged - 30) / 90.0)
    single_thread = 1.0 if multithreading_depth <= 1 else (0.5 if multithreading_depth == 2 else 0.0)
    no_exec = 0.0 if exec_sponsor_engaged_180d else 1.0
    if champion_tenure_months is None:
        tenure = 0.5
    elif champion_tenure_months < 6:
        tenure = 1.0
    elif champion_tenure_months <= 18:
        tenure = 0.5
    else:
        tenure = 0.0
    ecri = 100.0 * (0.35 * job_change + 0.20 * disengagement + 0.20 * single_thread + 0.15 * no_exec + 0.10 * tenure)
    return ChampionRiskIndex(round(ecri, 1), job_change, disengagement, single_thread, no_exec, tenure, champion_departed)


def multithreading_depth(stakeholders: Sequence[Dict[str, Any]], window_days: int = 90, as_of: Optional[date] = None) -> int:
    """
    Count of contacts with ≥ 1 two-way activity in the window, counted only if they span
    ≥ 2 distinct functions OR ≥ 2 seniority levels; otherwise the thread counts as 1.
    """
    as_of = as_of or date.today()
    cutoff = as_of - timedelta(days=window_days)
    engaged = []
    for s in stakeholders:
        last = s.get("last_engaged_at")
        if not last:
            continue
        last_d = last if isinstance(last, date) else date.fromisoformat(str(last))
        if last_d >= cutoff and (s.get("engagements_90d") or 0) > 0 and s.get("last_engagement_direction") in ("two_way", None, "inbound"):
            engaged.append(s)
    if not engaged:
        return 0
    functions = {s.get("function") or s.get("persona") for s in engaged}
    seniorities = {s.get("seniority") for s in engaged}
    if len(functions) >= 2 or len(seniorities) >= 2:
        return len(engaged)
    return 1


# ======================================================================================
# D. Capacity & efficiency
# ======================================================================================

@dataclass
class BookSummary:
    csm_id: str
    accounts: int
    arr: float
    red_accounts: int
    segment_target_arr: Optional[float]
    pct_of_target: Optional[float]
    over_capacity_flag: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def arr_per_csm(
    accounts: Sequence[Dict[str, Any]],
    segment_targets: Optional[Dict[str, float]] = None,
    over_capacity_threshold: float = 1.15,
) -> Tuple[List[BookSummary], Optional[float]]:
    """
    accounts: dicts with csm_owner_id, arr, segment, health_band.
    Returns per-CSM summaries and the team balance index σ/μ (target ≤ 0.20).
    """
    books: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for a in accounts:
        books[a["csm_owner_id"]].append(a)
    summaries: List[BookSummary] = []
    for csm, accts in books.items():
        arr = sum(float(a.get("arr") or 0) for a in accts)
        reds = sum(1 for a in accts if a.get("health_band") == "red")
        seg_counts: Dict[str, float] = defaultdict(float)
        for a in accts:
            seg_counts[a.get("segment", "all")] += float(a.get("arr") or 0)
        primary_segment = max(seg_counts, key=seg_counts.get) if seg_counts else "all"
        target = (segment_targets or {}).get(primary_segment)
        pct = _safe_div(arr, target) if target else None
        over = bool(pct is not None and pct > over_capacity_threshold and reds >= 2)
        summaries.append(BookSummary(csm, len(accts), arr, reds, target, pct, over))
    arrs = [s.arr for s in summaries]
    balance = (pstdev(arrs) / mean(arrs)) if len(arrs) >= 2 and mean(arrs) > 0 else None
    return summaries, balance


@dataclass
class RetentionCost:
    crc_total: float
    crc_per_customer: Optional[float]
    crc_per_dollar_retained: Optional[float]
    crc_ratio: Optional[float]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def customer_retention_cost(total_cs_cost: float, customers: int, grr: Optional[float], start_arr: float) -> RetentionCost:
    retained = (grr * start_arr) if (grr is not None) else None
    return RetentionCost(
        crc_total=total_cs_cost,
        crc_per_customer=_safe_div(total_cs_cost, customers),
        crc_per_dollar_retained=_safe_div(total_cs_cost, retained) if retained else None,
        crc_ratio=_safe_div(total_cs_cost, start_arr),
    )


@dataclass
class LTVCAC:
    arpa: float
    gross_margin: float
    annual_dollar_churn_rate: float
    ltv: float
    cac: float
    ltv_cac: Optional[float]
    horizon_capped: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def ltv_cac(arpa: float, gross_margin: float, grr_ttm: float, cac: float, max_horizon_years: float = 10.0) -> LTVCAC:
    """
    LTV = (ARPA × gross_margin) / annual_dollar_churn_rate, where churn = 1 − GRR_ttm.
    Horizon capped at `max_horizon_years` when churn < 1/horizon.
    """
    churn = max(1.0 - grr_ttm, 0.0)
    capped = False
    if churn < (1.0 / max_horizon_years):
        ltv = arpa * gross_margin * max_horizon_years
        capped = True
    else:
        ltv = arpa * gross_margin / churn
    return LTVCAC(arpa, gross_margin, churn, ltv, cac, _safe_div(ltv, cac), capped)


@dataclass
class QBRVelocity:
    due: int
    completed_on_time: int
    completed_late: int
    velocity: Optional[float]
    median_lag_days: Optional[float]
    arr_coverage: Optional[float]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def qbr_completion_velocity(qbrs: Sequence[Dict[str, Any]], on_time_grace_days: int = 15) -> QBRVelocity:
    """
    qbrs: dicts with due_at (date), completed_at (date|None), arr (float).
    velocity = on-time completions / due; arr_coverage = ARR with any completion / ARR due.
    """
    due = len(qbrs)
    on_time = late = 0
    lags: List[int] = []
    arr_due = sum(float(q.get("arr") or 0) for q in qbrs)
    arr_done = 0.0
    for q in qbrs:
        d, c = q.get("due_at"), q.get("completed_at")
        if not c:
            continue
        lag = (c - d).days
        lags.append(lag)
        arr_done += float(q.get("arr") or 0)
        if lag <= on_time_grace_days:
            on_time += 1
        else:
            late += 1
    return QBRVelocity(due, on_time, late, _safe_div(on_time, due), median(lags) if lags else None, _safe_div(arr_done, arr_due))


# ======================================================================================
# Demo
# ======================================================================================

def _demo() -> Dict[str, Any]:
    t0 = [
        ARRSnapshot("a1", 120_000, "enterprise"), ARRSnapshot("a2", 60_000, "mid_market"),
        ARRSnapshot("a3", 30_000, "mid_market"), ARRSnapshot("a4", 8_000, "smb"),
        ARRSnapshot("a5", 5_000, "smb"), ARRSnapshot("a6", 240_000, "enterprise"),
    ]
    t1 = [
        ARRSnapshot("a1", 150_000, "enterprise"), ARRSnapshot("a2", 45_000, "mid_market"),
        ARRSnapshot("a3", 30_000, "mid_market"), ARRSnapshot("a4", 0, "smb"),
        ARRSnapshot("a5", 5_000, "smb"), ARRSnapshot("a6", 240_000, "enterprise"),
        ARRSnapshot("a7", 20_000, "mid_market"),
    ]
    retention = [r.to_dict() for r in cohort_retention_by_segment(t0, t1, "2026-08-31", "2026-09-30")]

    as_of = date(2026, 10, 15)
    opps = [
        Opportunity("o1", "a1", "expansion", 30_000, date(2026, 8, 1), None, False, None),
        Opportunity("o2", "a6", "upsell", 50_000, date(2026, 9, 1), None, False, None),
        Opportunity("o3", "a2", "cross_sell", 12_000, date(2026, 9, 20), None, False, None),
    ] + [
        Opportunity(f"c{i}", "a1", "expansion", 20_000, date(2026, 5, 1), date(2026, 7, 1) + timedelta(days=i), True, i % 3 != 0)
        for i in range(24)
    ]
    velocity = expansion_pipeline_velocity(opps, as_of, remaining_quota=250_000).to_dict()

    fa = feature_depth(["dashboards", "alerts", "export"], ["dashboards", "alerts", "workflow_automation", "api_access"],
                       ["dashboards", "alerts", "workflow_automation", "api_access", "export", "audit_log"],
                       {"u1": 3, "u2": 1, "u3": 2}, mau=3).to_dict()
    ttv = time_to_value(date(2026, 9, 1), {}, ["first_production_workflow"], as_of, 21, 35).to_dict()
    ecri = champion_risk_index(True, False, 74, 2, False, 14).to_dict()
    nps = nps_score([9, 7, 10, 4, 8], [2.0, 1.0, 1.5, 1.0, 1.0])
    books, balance = arr_per_csm(
        [{"csm_owner_id": "csm_1", "arr": 4_200_000, "segment": "mid_market", "health_band": "red"},
         {"csm_owner_id": "csm_1", "arr": 900_000, "segment": "mid_market", "health_band": "red"},
         {"csm_owner_id": "csm_2", "arr": 2_600_000, "segment": "mid_market", "health_band": "green"}],
        {"mid_market": 3_000_000},
    )
    crc = customer_retention_cost(1_850_000, 180, 0.90, 24_000_000).to_dict()
    lc = ltv_cac(arpa=65_000, gross_margin=0.78, grr_ttm=0.90, cac=42_000).to_dict()
    qbr = qbr_completion_velocity([
        {"due_at": date(2026, 9, 1), "completed_at": date(2026, 9, 10), "arr": 120_000},
        {"due_at": date(2026, 9, 1), "completed_at": date(2026, 9, 30), "arr": 60_000},
        {"due_at": date(2026, 9, 1), "completed_at": None, "arr": 30_000},
    ]).to_dict()

    return {
        "retention_by_segment": retention,
        "expansion_pipeline_velocity": velocity,
        "feature_adoption": fa,
        "time_to_value": ttv,
        "champion_risk_index": ecri,
        "weighted_nps": nps,
        "books": [b.to_dict() for b in books],
        "book_balance_index": balance,
        "customer_retention_cost": crc,
        "ltv_cac": lc,
        "qbr_velocity": qbr,
    }


if __name__ == "__main__":
    if "--demo" in sys.argv:
        print(json.dumps(_demo(), indent=2, default=str))
    else:
        print("usage: python -m src.models.metrics_calculator --demo", file=sys.stderr)
        sys.exit(2)
