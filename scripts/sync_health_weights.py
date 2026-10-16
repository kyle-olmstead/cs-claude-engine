"""
Keep the health-score weights identical in both places that use them.

  config/health_weights.json   → read by src/models/health_score.py (Python, plugin mode, parity check)
  dbt/dbt_project.yml  vars    → read by dbt/models/marts/mart_customer_health_daily.sql

The JSON file is the source of truth.

    python3 scripts/sync_health_weights.py --check   # exit 1 if they differ (CI)
    python3 scripts/sync_health_weights.py --write   # copy JSON → dbt_project.yml vars
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
JSON_PATH = ROOT / "config" / "health_weights.json"
DBT_PROJECT = ROOT / "dbt" / "dbt_project.yml"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)

    weights = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    total = sum(weights.values())
    if abs(total - 1.0) > 1e-6:
        print(f"config/health_weights.json weights sum to {total:.6f}, not 1.0")
        return 1
    project = yaml.safe_load(DBT_PROJECT.read_text(encoding="utf-8"))
    current = (project.get("vars") or {}).get("health_weights") or {}

    if args.check:
        diff = {k: (current.get(k), v) for k, v in weights.items() if current.get(k) != v}
        if diff or set(current) != set(weights):
            print("health weights differ between config/health_weights.json and dbt/dbt_project.yml:")
            for k, (dbt_v, json_v) in diff.items():
                print(f"  {k}: dbt={dbt_v} json={json_v}")
            print("run: python3 scripts/sync_health_weights.py --write")
            return 1
        print("health weights in sync:", weights)
        return 0

    project.setdefault("vars", {})["health_weights"] = {k: float(v) for k, v in weights.items()}
    DBT_PROJECT.write_text(yaml.safe_dump(project, sort_keys=False, default_flow_style=False), encoding="utf-8")
    print("wrote dbt/dbt_project.yml vars.health_weights =", weights)
    return 0


if __name__ == "__main__":
    sys.exit(main())
