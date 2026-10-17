"""
The ROI model behind docs/04_ROI_MEMO.md. Every number in the memo comes from here.

Run it with the defaults to reproduce the memo, or change any assumption:

    python3 scripts/roi_model.py
    python3 scripts/roi_model.py --base 125000 --ote 150000 --turnover 0.25 --arr-per-csm 4000000
    python3 scripts/roi_model.py --json

No external data; pure arithmetic. The defaults and their sources are explained in the memo.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, asdict, field
from typing import Dict, List


@dataclass
class Assumptions:
    # team and book
    team_size: int = 10
    underperformers: int = 2
    arr_per_csm: float = 3_000_000
    productive_hours: int = 1_800
    gross_margin: float = 0.80
    # compensation (per CSM)
    base: float = 115_000
    ote: float = 135_000
    fica_rate: float = 0.0765
    health: float = 11_000
    k401_rate: float = 0.03
    other_benefits: float = 1_600
    tech_stack: float = 2_500
    equipment: float = 1_500
    # turnover
    turnover: float = 0.20
    recruiting_pct_of_base: float = 0.20
    ramp_days: int = 90
    ramp_productivity: float = 0.50
    coverage_gap_churn_pts: float = 0.01       # share of the vacated book at risk during vacancy + ramp
    severance_weeks: int = 8
    # underperformance drag
    under_grr_gap: float = 0.03
    under_expansion_gap: float = 0.05
    # engine cost
    seats: int = 10
    seat_price_month: float = 30.0
    api_annual: float = 5_000
    csops_annual: float = 4_800
    implementation_once: float = 11_000
    # time returned per CSM per year: (count, hours before, hours after)
    time_model: Dict[str, List[float]] = field(default_factory=lambda: {
        "Executive business review prep": [80, 5.0, 2.0],
        "Weekly book review and triage": [48, 3.0, 0.75],
        "Renewal planning": [60, 3.0, 1.0],
        "Red-account root cause and save plan": [12, 4.0, 1.5],
        "CRM hygiene, tasks, notes": [48, 2.0, 1.0],
    })
    # retention scenarios: name -> (grr change, net expansion change)
    scenarios: Dict[str, List[float]] = field(default_factory=lambda: {
        "Downside: thinner coverage costs half a point": [-0.005, 0.0],
        "Conservative: retention flat": [0.0, 0.0],
        "Base: risk caught earlier": [0.005, 0.0],
        "Upside: earlier risk detection plus surfaced expansion": [0.01, 0.01],
    })
    # one open seat (Part 8): how long the book is under-covered while a seat is open
    open_seats: int = 1
    time_to_fill_days: int = 50       # mid-level CS roles commonly take 45 to 60 days to fill
    gap_months: float = 5.0           # time to fill plus the 90-day ramp at half productivity, rounded to the month


def model(a: Assumptions) -> Dict:
    fica = a.ote * a.fica_rate
    k401 = a.ote * a.k401_rate
    fringe = fica + a.health + k401 + a.other_benefits
    steady = a.ote + fringe + a.tech_stack + a.equipment

    recruit = a.recruiting_pct_of_base * a.base
    ramp = a.ramp_productivity * (a.ramp_days / 365) * steady
    gap = a.coverage_gap_churn_pts * a.arr_per_csm
    per_event = recruit + ramp + gap
    amort = a.turnover * per_event
    loaded = steady + amort

    book = a.team_size * a.arr_per_csm
    n = a.underperformers
    under_book = n * a.arr_per_csm
    carry = n * steady
    carry_adj = n * loaded
    drag = under_book * (a.under_grr_gap + a.under_expansion_gap)

    severance = n * a.base * a.severance_weeks / 52
    replace_once = {"severance": severance, "recruiting": n * recruit, "ramp": n * ramp, "coverage_gap": n * gap}

    engine_run = a.seats * a.seat_price_month * 12 + a.api_annual + a.csops_annual
    engine_once = a.implementation_once
    y1 = carry - severance - engine_once - engine_run
    ss = carry - engine_run
    ss_adj = carry_adj - engine_run

    remaining = a.team_size - n
    book_increase = (a.team_size / remaining) - 1
    saved = {k: v[0] * (v[1] - v[2]) for k, v in a.time_model.items()}
    saved_total = sum(saved.values())
    saved_share = saved_total / a.productive_hours

    breakeven_grr = engine_run / book
    scen = {}
    for name, (grr, nrr) in a.scenarios.items():
        arr = book * (grr + nrr)
        ebitda = ss + arr * a.gross_margin
        scen[name] = {"grr_change": grr, "expansion_change": nrr, "arr_effect": arr, "ebitda_effect": ebitda, "ebitda_margin_pts": ebitda / book * 100}

    # Part 8: one open seat. The unit is a seat for a month, which is how the budget line reads.
    seats = a.open_seats
    unspent_month = steady / 12
    unspent_gap = unspent_month * a.gap_months * seats
    engine_gap = engine_once + engine_run * a.gap_months / 12
    gap_risk = gap * seats
    remaining_after_vacancy = a.team_size - seats
    load_increase_vacancy = (a.team_size / remaining_after_vacancy) - 1 if remaining_after_vacancy > 0 else float("inf")
    open_seat = {
        "seats": seats, "gap_months": a.gap_months, "time_to_fill_days": a.time_to_fill_days,
        "unspent_comp_per_month": unspent_month, "unspent_comp_over_gap": unspent_gap,
        "vacancy_cost_per_departure": per_event, "coverage_gap_risk": gap_risk,
        "engine_cost_over_gap": engine_gap, "engine_vs_coverage_risk": engine_gap / gap_risk if gap_risk else None,
        "net_vs_plan": unspent_gap - engine_gap,
        "remaining_csms": remaining_after_vacancy, "load_increase": load_increase_vacancy,
        "hours_returned_share": saved_share, "cushion": saved_share - load_increase_vacancy,
    }

    return {
        "per_csm": {"fica": fica, "k401": k401, "fringe": fringe, "fringe_pct_of_ote": fringe / a.ote, "steady_state_loaded": steady,
                    "recruit_per_event": recruit, "ramp_per_event": ramp, "coverage_gap_per_event": gap, "turnover_event_total": per_event,
                    "turnover_amortized": amort, "turnover_adjusted_loaded": loaded},
        "team": {"steady_state": a.team_size * steady, "turnover_adjusted": a.team_size * loaded, "book_arr": book},
        "underperformers": {"direct_cost": carry, "direct_cost_turnover_adjusted": carry_adj, "book": under_book, "revenue_drag_arr": drag},
        "option_a_replace": {"one_time": replace_once, "one_time_total": sum(replace_once.values()), "ongoing": carry},
        "engine": {"run_rate": engine_run, "one_time": engine_once, "seats": a.seats * a.seat_price_month * 12, "api": a.api_annual, "csops": a.csops_annual},
        "option_b_engine": {"year_1_net": y1, "steady_state_net": ss, "steady_state_net_turnover_adjusted": ss_adj, "severance": severance},
        "capacity": {"book_increase_needed": book_increase, "hours_saved": saved, "hours_saved_total": saved_total, "share_of_productive_hours": saved_share,
                     "margin_vs_needed": saved_share - book_increase},
        "retention": {"breakeven_grr_lift": breakeven_grr, "scenarios": scen},
        "open_seat": open_seat,
    }


def fmt(x: float) -> str:
    return f"${x:,.0f}"


def print_report(a: Assumptions, m: Dict) -> None:
    p, t, u, A, e, B, c, r = (m[k] for k in ("per_csm", "team", "underperformers", "option_a_replace", "engine", "option_b_engine", "capacity", "retention"))
    print("WHAT ONE CSM COSTS")
    print(f"  OTE {fmt(a.ote)} + fringe {fmt(p['fringe'])} ({p['fringe_pct_of_ote']:.1%}) + tech {fmt(a.tech_stack)} + equipment {fmt(a.equipment)}")
    print(f"  = {fmt(p['steady_state_loaded'])} steady state; {fmt(p['turnover_adjusted_loaded'])} with turnover ({a.turnover:.0%}/yr, {fmt(p['turnover_event_total'])} per departure)")
    print(f"  Team of {a.team_size}: {fmt(t['steady_state'])} / {fmt(t['turnover_adjusted'])}; book {fmt(t['book_arr'])}\n")
    print(f"CARRYING {a.underperformers} UNDERPERFORMERS")
    print(f"  Direct {fmt(u['direct_cost'])}/yr ({fmt(u['direct_cost_turnover_adjusted'])} turnover-adjusted); revenue drag {fmt(u['revenue_drag_arr'])} ARR/yr on {fmt(u['book'])}\n")
    print("OPTION A: REPLACE THEM")
    print(f"  One-time {fmt(A['one_time_total'])} ({', '.join(f'{k} {fmt(v)}' for k, v in A['one_time'].items())}); ongoing {fmt(A['ongoing'])}/yr\n")
    print("OPTION B: DON'T BACKFILL, GIVE THE OTHERS THE ENGINE")
    print(f"  Engine {fmt(e['run_rate'])}/yr (+{fmt(e['one_time'])} once); severance {fmt(B['severance'])}")
    print(f"  Year 1 net {fmt(B['year_1_net'])}; steady state {fmt(B['steady_state_net'])}/yr ({fmt(B['steady_state_net_turnover_adjusted'])} turnover-adjusted)")
    print(f"  Capacity: each remaining CSM takes +{c['book_increase_needed']:.0%}; engine returns {c['hours_saved_total']:.0f} h = {c['share_of_productive_hours']:.0%} of {a.productive_hours} h (margin {c['margin_vs_needed']:+.0%})\n")
    print("WHAT THE ENGINE HAS TO DELIVER")
    print(f"  Break-even: {r['breakeven_grr_lift']:.3%} of gross retention = one {fmt(e['run_rate'])} renewal a year")
    for name, s in r["scenarios"].items():
        print(f"  {name:58} GRR {s['grr_change']:+.1%}  exp {s['expansion_change']:+.1%}  ARR {s['arr_effect']:+,.0f}  EBITDA {s['ebitda_effect']:+,.0f} ({s['ebitda_margin_pts']:+.2f} pts)")
    o = m["open_seat"]
    print()
    print(f"ONE OPEN SEAT (Part 8)" if o["seats"] == 1 else f"{o['seats']} OPEN SEATS (Part 8)")
    print(f"  Unspent comp while the seat is open   {fmt(o['unspent_comp_per_month'])} / month / seat; {fmt(o['unspent_comp_over_gap'])} over a {o['gap_months']:.0f}-month gap")
    print(f"  Cost of the vacancy                   {fmt(o['vacancy_cost_per_departure'])} per departure; coverage-gap risk {fmt(o['coverage_gap_risk'])}")
    print(f"  Engine over the gap                   {fmt(o['engine_cost_over_gap'])} (setup + {o['gap_months']:.0f} months of run cost) = {o['engine_vs_coverage_risk']:.2f}x the coverage-gap risk")
    print(f"  Net against plan while covered        {fmt(o['net_vs_plan'])} under budget")
    print(f"  The team that stayed                  {o['remaining_csms']} CSMs take +{o['load_increase']:.0%} each; engine returns ~{o['hours_returned_share']:.0%} of hours; cushion {o['cushion']:+.0%}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="CS-Claude Engine ROI model (docs/04_ROI_MEMO.md)")
    d = Assumptions()
    for name, value in asdict(d).items():
        if isinstance(value, dict):
            continue
        flag = "--" + name.replace("_", "-")
        ap.add_argument(flag, type=type(value), default=value, help=f"default {value}")
    ap.add_argument("--json", action="store_true", help="print the full model as JSON")
    args = ap.parse_args(argv)
    a = Assumptions(**{k: getattr(args, k) for k in asdict(d) if not isinstance(asdict(d)[k], dict)})
    m = model(a)
    if args.json:
        print(json.dumps({"assumptions": asdict(a), "model": m}, indent=2))
    else:
        print_report(a, m)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
