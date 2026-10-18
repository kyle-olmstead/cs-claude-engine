"""
SQL ↔ Python health-score parity check (docs/01_ARCHITECTURE.md §3.3).

Reads the latest row per account from `mart_customer_health_daily`, rebuilds the minimal
Customer 360 inputs the Python scorer needs from those columns, recomputes the score with
src/models/health_score.py, and fails if any account differs by more than the tolerance.

    python3 scripts/check_parity.py                       # DuckDB at dbt/dev.duckdb (local dev)
    python3 scripts/check_parity.py --duckdb path.duckdb
    python3 scripts/check_parity.py --jsonl mart_rows.jsonl   # rows exported from any warehouse

Exit 0 when every account matches, 1 otherwise. Run it in CI after `dbt build`, and in
production after the nightly mart build — it catches normalizer drift the day it happens.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.models.health_score import HealthWeights, compute_health_score  # noqa: E402

COLUMNS = [
    "account_id", "account_name", "as_of_date", "arr", "seats_purchased", "days_to_renewal", "payment_days_past_due", "contraction_flag_90d",
    "dau_mau_30d", "feature_depth_30d", "seat_utilization", "seat_utilization_90d_ago", "days_since_last_login", "engaged_contacts_90d",
    "multithreading_depth", "exec_sponsor_engaged_180d", "days_since_last_csm_touch", "champion_status", "replacement_identified",
    "open_p1_p2", "oldest_open_p1_age_days", "tickets_per_100_seats_30d", "avg_csat_90d", "median_first_response_hours_90d",
    "latest_nps", "nps_trend", "transcript_sentiment_30d", "raw_weighted_sum", "raw_weighted_sum_30d_ago", "health_score_30d_ago",
    "health_score", "health_band", "trend_adjustment", "health_coverage", "support_observed",
]


def row_to_c360(r: Dict[str, Any]) -> Dict[str, Any]:
    """The subset of the Customer 360 the scorer reads, reconstructed from one mart row."""
    engaged = int(r.get("engaged_contacts_90d") or 0)
    stakeholders = [{"contact_id": f"ct_{i}", "engagements_90d": 1} for i in range(engaged)]
    open_tickets: Optional[List[Dict[str, Any]]] = []
    p1p2 = int(r.get("open_p1_p2") or 0)
    p1_age = r.get("oldest_open_p1_age_days")
    for i in range(p1p2):
        # the mart only keeps the count and the oldest P1 age; one P1 carries the age, the rest are P2
        open_tickets.append({"priority": "P1" if (i == 0 and p1_age is not None) else "P2", "age_days": int(p1_age or 0) if i == 0 else 0})
    if r.get("support_observed") is False:
        open_tickets = None            # the desk produced nothing for this account: the component is unobserved, not "100"
    return {
        "usage": {"dau_mau_30d": r.get("dau_mau_30d"), "feature_depth_30d": r.get("feature_depth_30d"), "seat_utilization": r.get("seat_utilization"),
                  "seat_utilization_90d_ago": r.get("seat_utilization_90d_ago"), "days_since_last_login": r.get("days_since_last_login")},
        "relationship": {"stakeholders": stakeholders, "exec_sponsor_engaged_180d": bool(r.get("exec_sponsor_engaged_180d")),
                         "champion": {"status": r.get("champion_status") or "none", "replacement_identified": bool(r.get("replacement_identified"))},
                         "multithreading_depth": r.get("multithreading_depth"), "days_since_last_csm_touch": r.get("days_since_last_csm_touch")},
        "support": {"open_tickets": open_tickets, "tickets_per_100_seats_30d": r.get("tickets_per_100_seats_30d"), "avg_csat_90d": r.get("avg_csat_90d"),
                    "median_first_response_hours_90d": r.get("median_first_response_hours_90d")},
        "sentiment": {"latest_nps": r.get("latest_nps"), "nps_trend": r.get("nps_trend"), "transcript_sentiment_30d": r.get("transcript_sentiment_30d")},
        "contract": {"arr": r.get("arr"), "days_to_renewal": r.get("days_to_renewal"), "payment_days_past_due": r.get("payment_days_past_due") or 0,
                     "contraction_flag_90d": bool(r.get("contraction_flag_90d"))},
        "health": {"score_30d_ago": r.get("health_score_30d_ago"), "raw_weighted_sum_30d_ago": r.get("raw_weighted_sum_30d_ago")},
    }


def latest_rows_duckdb(path: Path) -> Iterable[Dict[str, Any]]:
    import duckdb
    con = duckdb.connect(str(path), read_only=True)
    cols = ", ".join(COLUMNS)
    rows = con.execute(f"select {cols} from mart_customer_health_daily where as_of_date = (select max(as_of_date) from mart_customer_health_daily) order by account_id").fetchall()
    for row in rows:
        yield dict(zip(COLUMNS, row))


def rows_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--duckdb", default=str(ROOT / "dbt" / "dev.duckdb"))
    ap.add_argument("--jsonl", default=None)
    ap.add_argument("--tolerance", type=float, default=0.5)
    args = ap.parse_args(argv)

    rows = list(rows_jsonl(Path(args.jsonl))) if args.jsonl else list(latest_rows_duckdb(Path(args.duckdb)))
    weights = HealthWeights.load()
    worst = 0.0
    failures = 0
    print(f"{'account':24} {'mart':>7} {'python':>7} {'delta':>6}  band   components(py)")
    for r in rows:
        res = compute_health_score(row_to_c360(r), weights)
        delta = abs(res.score - float(r["health_score"]))
        worst = max(worst, delta)
        ok = delta <= args.tolerance and res.band == r["health_band"] and abs(res.coverage - float(r.get("health_coverage") or 1.0)) < 1e-6
        failures += 0 if ok else 1
        comps = " ".join(f"{c.name[:3]}={c.normalized:.0f}" for c in res.components)
        print(f"{r['account_name'][:24]:24} {float(r['health_score']):7.2f} {res.score:7.2f} {delta:6.2f}  {'OK ' if ok else 'FAIL'} {r['health_band']:6} {comps}")
    print(f"\n{len(rows)} account(s) · worst delta {worst:.3f} · tolerance {args.tolerance} · {'PARITY OK' if not failures else str(failures) + ' MISMATCH(ES)'}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
