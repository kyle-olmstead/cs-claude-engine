"""
Generate the dbt seeds (dbt/seeds/*.csv) — a deterministic, synthetic history for the sample
account in examples/sample_customer_360.json plus two smaller accounts, so `dbt build` runs on
DuckDB with no warehouse and the marts produce rows the Python scorer can be checked against.

    python3 scripts/make_seeds.py            # writes dbt/seeds/*.csv
    python3 scripts/make_seeds.py --as-of 2026-10-15

Everything here is invented. The point is shape and parity, not realism.
"""

from __future__ import annotations

import argparse
import csv
import random
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEEDS = ROOT / "dbt" / "seeds"
HISTORY_DAYS = 300      # ARR snapshots (the retention mart wants months of history)
USAGE_DAYS = 160        # usage/feature events (the health mart needs 120 days + a buffer); keeps the seeds small


def write(name: str, rows: list[dict]) -> None:
    SEEDS.mkdir(parents=True, exist_ok=True)
    path = SEEDS / f"{name}.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"  {path.relative_to(ROOT)}: {len(rows)} rows")


def main(as_of: date) -> None:
    rnd = random.Random(42)
    start = as_of - timedelta(days=HISTORY_DAYS)

    # --- accounts -------------------------------------------------------------------
    accounts = [
        # id, name, segment, owner, industry, created, arr, seats, term_start, term_end
        ("acc_01HZXK3V8Q", "Contoso Logistics", "enterprise", "csm_017", "Transportation & Logistics", "2024-01-18", 240000, 500, "2025-01-18", "2027-01-18"),
        ("acc_02FABRIKAM", "Fabrikam Health", "mid_market", "csm_017", "Healthcare", "2024-06-03", 84000, 200, "2025-06-01", "2026-12-15"),
        ("acc_03BRIGHTL", "Brightline Studio", "digital", "csm_022", "Media", "2026-02-10", 9600, 20, "2026-02-10", "2027-02-10"),
        # CRM-only account: no product analytics, no support desk, no surveys, no calls. Exercises the coverage
        # re-normalization and the insufficient_data band on both the SQL and Python side (check_parity.py).
        ("acc_04NORTHWD", "Northwind Traders", "mid_market", "csm_017", "Wholesale", "2025-09-01", 96000, 120, "2025-10-01", "2026-09-30"),
    ]
    write("crm_companies", [dict(id=a[0], name=a[1], segment=a[2], owner_id=a[3], industry=a[4], created_at=a[5]) for a in accounts])

    # --- contacts (Contoso mirrors the sample Customer 360) --------------------------
    contacts = [
        # id, company, email, title, seniority, persona, function, champ, exec, left, enriched_employer, tenure
        ("ct_01", "acc_01HZXK3V8Q", "jordan.reyes@contoso.example", "Director, Operations Systems", "director", "champion", "operations", True, False, "", "Northwind Traders", 14),
        ("ct_02", "acc_01HZXK3V8Q", "elena.vasquez@contoso.example", "SVP Finance Operations", "vp", "executive_sponsor", "finance", False, True, "", "Contoso Logistics", 48),
        ("ct_03", "acc_01HZXK3V8Q", "sam.okafor@contoso.example", "Finance Systems Admin", "individual_contributor", "admin", "finance", False, False, "", "Contoso Logistics", 30),
        ("ct_04", "acc_01HZXK3V8Q", "tasha.l@contoso.example", "Fleet Operations Manager", "manager", "ops_manager", "fleet", False, False, "", "", 22),
        ("ct_05", "acc_01HZXK3V8Q", "raj.mehta@contoso.example", "VP Procurement", "vp", "procurement", "procurement", False, False, "", "", 60),
        ("ct_11", "acc_02FABRIKAM", "dana.k@fabrikam.example", "Head of Revenue Ops", "director", "champion", "operations", True, False, "", "Fabrikam Health", 20),
        ("ct_12", "acc_02FABRIKAM", "omar.s@fabrikam.example", "CFO", "c_level", "economic_buyer", "finance", False, True, "", "Fabrikam Health", 70),
        ("ct_21", "acc_03BRIGHTL", "lee@brightline.example", "Studio Manager", "manager", "admin", "operations", True, False, "", "", 8),
        ("ct_31", "acc_04NORTHWD", "priya.n@northwind.example", "Director of Finance", "director", "champion", "finance", True, False, "", "Northwind Traders", 11),
    ]
    write("crm_contacts", [dict(id=c[0], company_id=c[1], email=c[2], title=c[3], seniority=c[4], persona=c[5], function=c[6],
                                is_champion=c[7], is_exec_sponsor=c[8], left_company_at=c[9], enriched_employer=c[10], tenure_months=c[11]) for c in contacts])

    # --- activities -----------------------------------------------------------------
    acts = []
    n = 0
    def act(company, contact, kind, direction, days_ago, owner="csm_017"):
        nonlocal n
        n += 1
        acts.append(dict(id=f"act_{n:05d}", company_id=company, contact_id=contact, activity_type=kind, direction=direction,
                         occurred_at=(as_of - timedelta(days=days_ago)).isoformat(), owner_id=owner))
    # Contoso: champion went quiet 38d ago; exec sponsor 40d; admin very active; fleet manager once; CSM touch 9d ago
    for d in (38, 52, 75, 110, 150):
        act("acc_01HZXK3V8Q", "ct_01", "email", "inbound" if d % 2 else "outbound", d)
    act("acc_01HZXK3V8Q", "ct_02", "meeting", "inbound", 40); act("acc_01HZXK3V8Q", "ct_02", "email", "outbound", 41); act("acc_01HZXK3V8Q", "ct_02", "meeting", "inbound", 148)
    for d in (2, 9, 16, 23, 30, 44, 61, 80):
        act("acc_01HZXK3V8Q", "ct_03", "email", "inbound" if d % 3 else "outbound", d)
    act("acc_01HZXK3V8Q", "ct_04", "email", "inbound", 33)
    act("acc_01HZXK3V8Q", "ct_05", "email", "inbound", 309)
    # Fabrikam: healthy multithreading
    for d in (3, 12, 25, 40, 66):
        act("acc_02FABRIKAM", "ct_11", "meeting" if d % 2 else "email", "inbound" if d % 3 else "outbound", d)
    for d in (20, 95):
        act("acc_02FABRIKAM", "ct_12", "meeting", "inbound", d)
    # Brightline: digital, light touch
    act("acc_03BRIGHTL", "ct_21", "email", "inbound", 2, owner="csm_022")
    # Northwind: CRM activity only
    act("acc_04NORTHWD", "ct_31", "meeting", "inbound", 6); act("acc_04NORTHWD", "ct_31", "email", "outbound", 20)
    write("crm_activities", acts)

    # --- opportunities --------------------------------------------------------------
    write("crm_opportunities", [
        dict(id="opp_7781", company_id="acc_01HZXK3V8Q", type="renewal", stage="Discovery", amount=240000, created_at=(as_of - timedelta(days=44)).isoformat(), close_date="2027-01-18", is_closed=False, is_won=""),
        dict(id="opp_7700", company_id="acc_02FABRIKAM", type="expansion", stage="Closed Won", amount=12000, created_at=(as_of - timedelta(days=120)).isoformat(), close_date=(as_of - timedelta(days=70)).isoformat(), is_closed=True, is_won=True),
        dict(id="opp_7790", company_id="acc_02FABRIKAM", type="renewal", stage="Proposal", amount=96000, created_at=(as_of - timedelta(days=30)).isoformat(), close_date="2026-12-15", is_closed=False, is_won=""),
    ])

    # --- billing ---------------------------------------------------------------------
    write("billing_subscriptions", [
        dict(id=f"sub_{a[0]}", company_id=a[0], product_sku="core", seats_purchased=a[7], mrr=round(a[6] / 12, 2), term_start=a[8], term_end=a[9], status="active") for a in accounts
    ])
    arr_rows = []
    for a in accounts:
        for i in range(HISTORY_DAYS + 1):
            d = start + timedelta(days=i)
            if d < date.fromisoformat(a[8]):
                continue
            arr, seats, reason = a[6], a[7], ""
            if a[0] == "acc_02FABRIKAM" and d >= as_of - timedelta(days=70):   # expansion 70 days ago
                arr, seats, reason = 96000, 230, "expansion"
            arr_rows.append(dict(company_id=a[0], snapshot_date=d.isoformat(), arr=arr, seats_purchased=seats, term_start=a[8], term_end=a[9],
                                 payment_days_past_due=0, arr_change_reason=reason))
    write("billing_arr_daily", arr_rows)

    # --- product usage: deterministic cohorts of users --------------------------------
    usage, feat = [], []
    profiles = {  # company: (user_count, daily_active_prob, seats, core_features_used, other_features)
        "acc_01HZXK3V8Q": (405, 0.36, 500, ["dashboards", "alerts"], ["export", "scheduled_reports"]),
        "acc_02FABRIKAM": (150, 0.30, 230, ["dashboards", "alerts", "workflow_automation"], ["export"]),
        "acc_03BRIGHTL": (23, 0.40, 20, ["dashboards", "alerts", "api_access"], ["export"]),
    }
    for company, (users, p_active, _, core, other) in profiles.items():
        usage_start = as_of - timedelta(days=USAGE_DAYS)
        for u in range(users):
            email = f"user{u:04d}@{company.lower()}.example"
            for i in range(USAGE_DAYS + 1):
                d = usage_start + timedelta(days=i)
                if d < date.fromisoformat(next(a[8] for a in accounts if a[0] == company)):
                    continue
                active_today = rnd.random() < p_active
                if active_today:
                    usage.append(dict(company_id=company, user_email=email, usage_date=d.isoformat(), sessions=1 + rnd.randint(0, 2), events=rnd.randint(5, 60), minutes_active=round(rnd.uniform(5, 90), 1)))
                    if rnd.random() < 0.5:
                        fk = rnd.choice(core)
                        feat.append(dict(company_id=company, user_email=email, feature_key=fk, is_core_feature=True, event_at=d.isoformat()))
                    if rnd.random() < 0.08 and d < as_of - timedelta(days=61):   # 'scheduled_reports' fades for Contoso
                        fk = rnd.choice(other)
                        feat.append(dict(company_id=company, user_email=email, feature_key=fk, is_core_feature=False, event_at=d.isoformat()))
    write("product_daily_usage", usage)
    write("product_feature_events", feat)
    write("product_value_milestones", [
        dict(company_id="acc_01HZXK3V8Q", milestone_key="integration_connected", reached_at="2025-02-10"),
        dict(company_id="acc_01HZXK3V8Q", milestone_key="first_production_workflow", reached_at="2025-02-28"),
        dict(company_id="acc_01HZXK3V8Q", milestone_key="five_active_users", reached_at="2025-03-04"),
        dict(company_id="acc_02FABRIKAM", milestone_key="first_production_workflow", reached_at="2025-06-20"),
    ])

    # --- support ---------------------------------------------------------------------
    tickets, k = [], 0
    def ticket(company, prio, status, created_days_ago, first_h, resolved_days_ago, csat):
        nonlocal k
        k += 1
        created = datetime.combine(as_of - timedelta(days=created_days_ago), datetime.min.time()) + timedelta(hours=9)
        tickets.append(dict(id=f"tk_{k:05d}", company_id=company, priority=prio, status=status, created_at=created.isoformat(sep=" "),
                            first_response_at=(created + timedelta(hours=first_h)).isoformat(sep=" ") if first_h is not None else "",
                            resolved_at=(datetime.combine(as_of - timedelta(days=resolved_days_ago), datetime.min.time()) + timedelta(hours=15)).isoformat(sep=" ") if resolved_days_ago is not None else "",
                            csat_score=csat if csat is not None else ""))
    ticket("acc_01HZXK3V8Q", "P2", "open", 3, 2.5, None, None)
    for i, (d, h, c) in enumerate([(6, 3.0, 5), (11, 4.5, 4), (15, 2.0, 5), (20, 3.1, 4), (27, 6.0, 4), (45, 1.5, 5), (70, 3.0, 4), (85, 2.2, 4), (130, 5.0, 3)]):
        ticket("acc_01HZXK3V8Q", "P3", "solved", d, h, d - 1 if d > 1 else 0, c)
    ticket("acc_02FABRIKAM", "P1", "open", 8, 1.0, None, None)
    for d, h, c in [(14, 7.0, 2), (31, 9.0, 3), (50, 3.0, 3)]:
        ticket("acc_02FABRIKAM", "P3", "solved", d, h, d - 2, c)
    write("support_tickets", tickets)

    # --- surveys ---------------------------------------------------------------------
    write("survey_responses", [
        dict(id="nps_88213", company_id="acc_01HZXK3V8Q", contact_id="ct_03", survey_type="nps", score=9, verbatim="Finance Ops lives in this now. The EU export hiccup is annoying but support has been quick.", responded_at=(as_of - timedelta(days=33)).isoformat()),
        dict(id="nps_88214", company_id="acc_01HZXK3V8Q", contact_id="ct_04", survey_type="nps", score=6, verbatim="Fleet hasn't really adopted it. We were told Jordan would drive that and now Jordan's gone.", responded_at=(as_of - timedelta(days=33)).isoformat()),
        dict(id="nps_87001", company_id="acc_01HZXK3V8Q", contact_id="ct_01", survey_type="nps", score=9, verbatim="Great platform, team loves the dashboards.", responded_at=(as_of - timedelta(days=130)).isoformat()),
        dict(id="nps_87002", company_id="acc_01HZXK3V8Q", contact_id="ct_03", survey_type="nps", score=8, verbatim="", responded_at=(as_of - timedelta(days=131)).isoformat()),
        dict(id="nps_87101", company_id="acc_02FABRIKAM", contact_id="ct_11", survey_type="nps", score=4, verbatim="Still waiting on the data sync fix. Hard to recommend until that's sorted.", responded_at=(as_of - timedelta(days=12)).isoformat()),
        dict(id="nps_87102", company_id="acc_02FABRIKAM", contact_id="ct_12", survey_type="nps", score=7, verbatim="", responded_at=(as_of - timedelta(days=12)).isoformat()),
        dict(id="nps_87201", company_id="acc_03BRIGHTL", contact_id="ct_21", survey_type="nps", score=9, verbatim="Love it; we need more seats.", responded_at=(as_of - timedelta(days=5)).isoformat()),
    ])

    # --- calls + transcript sentiment ---------------------------------------------------
    write("conversation_calls", [
        dict(id="call_20260826", company_id="acc_01HZXK3V8Q", occurred_at=(as_of - timedelta(days=50)).isoformat(), duration_sec=2700, transcript_uri="", participants_json='["ct_02","ct_03"]'),
        dict(id="call_20260930", company_id="acc_01HZXK3V8Q", occurred_at=(as_of - timedelta(days=15)).isoformat(), duration_sec=1800, transcript_uri="", participants_json='["ct_03"]'),
        dict(id="call_fab_01", company_id="acc_02FABRIKAM", occurred_at=(as_of - timedelta(days=9)).isoformat(), duration_sec=2400, transcript_uri="", participants_json='["ct_11"]'),
    ])
    write("transcript_sentiment", [
        dict(call_id="call_20260826", company_id="acc_01HZXK3V8Q", occurred_at=(as_of - timedelta(days=50)).isoformat(), sentiment=0.6),
        dict(call_id="call_20260930", company_id="acc_01HZXK3V8Q", occurred_at=(as_of - timedelta(days=15)).isoformat(), sentiment=0.3),
        dict(call_id="call_fab_01", company_id="acc_02FABRIKAM", occurred_at=(as_of - timedelta(days=9)).isoformat(), sentiment=-0.4),
    ])

    # --- CSM cost --------------------------------------------------------------------
    write("csm_cost", [dict(owner_id=o, month=(date(as_of.year, as_of.month, 1) - timedelta(days=30 * i)).replace(day=1).isoformat(), fully_loaded_cost=cost)
                       for o, cost in (("csm_017", 15400), ("csm_022", 12100)) for i in range(12)])
    print("seeds written for as_of", as_of)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--as-of", default="2026-10-15")
    args = ap.parse_args()
    main(date.fromisoformat(args.as_of))
