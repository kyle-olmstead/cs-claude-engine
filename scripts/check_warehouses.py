"""
Prove the dbt project builds the same marts on Snowflake, BigQuery and Databricks as on DuckDB,
without a warehouse account.

For each warehouse:
  1. compile the project with that warehouse's real dbt adapter, offline (the CI-only macros in
     dbt/ci/offline_macros stop the adapters from connecting);
  2. parse every compiled model in that warehouse's SQL dialect (sqlglot);
  3. translate each model to DuckDB, run them in dependency order on the bundled seeds, and require
     both marts to match the native DuckDB build row for row (computed_at excluded).

Step 3 is strong evidence, not proof: it tests the SQL the adapter generated, through a translator,
on DuckDB. A function that exists in the translation but behaves differently in the real warehouse
can still slip through, and nothing here runs on a live Snowflake, BigQuery or Databricks account.

    pip install dbt-duckdb dbt-snowflake dbt-bigquery dbt-databricks sqlglot
    python3 scripts/check_warehouses.py            # exit 0 when every warehouse matches

Exit 1 on any compile, parse, execution or comparison failure.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[1]
DBT = ROOT / "dbt"
WAREHOUSES = {"snowflake": "snowflake", "bigquery": "bigquery", "databricks": "databricks"}
MARTS = {
    "mart_customer_health_daily": ["account_id", "as_of_date"],
    "mart_retention_nrr_grr": ["period_month", "window_type", "segment"],
}


def _fake_service_account(path: Path) -> None:
    """A throwaway key: the BigQuery adapter builds credentials at start-up but never uses them offline."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    path.write_text(json.dumps({
        "type": "service_account", "project_id": "offline-project", "private_key_id": "offline",
        "private_key": pem, "client_email": "offline@offline-project.iam.gserviceaccount.com",
        "client_id": "0", "token_uri": "https://oauth2.googleapis.com/token"}))


def _profiles(workdir: Path) -> Path:
    sa = workdir / "offline_service_account.json"
    _fake_service_account(sa)
    prof = workdir / "profiles"
    prof.mkdir()
    (prof / "profiles.yml").write_text(f"""cs_claude_engine:
  target: duckdb
  outputs:
    duckdb: {{type: duckdb, path: native.duckdb, threads: 4}}
    snowflake: {{type: snowflake, account: offline, user: offline, password: offline, role: offline, warehouse: offline, database: ANALYTICS, schema: cs_engine, threads: 1}}
    bigquery: {{type: bigquery, method: service-account, keyfile: {sa}, project: offline-project, dataset: cs_engine, threads: 1}}
    databricks: {{type: databricks, host: offline.cloud.databricks.com, http_path: /sql/1.0/warehouses/offline, token: offline, catalog: main, schema: cs_engine, threads: 1}}
""")
    return prof


def _dbt(project: Path, prof: Path, *args: str) -> None:
    env = {**os.environ, "DO_NOT_TRACK": "1", "DBT_SEND_ANONYMOUS_USAGE_STATS": "false"}
    cmd = [sys.executable, "-m", "dbt.cli.main", *args, "--profiles-dir", str(prof), "--quiet"]
    r = subprocess.run(cmd, cwd=project, env=env, capture_output=True, text=True, check=False)
    if r.returncode != 0:
        raise RuntimeError(f"dbt {' '.join(args)} failed:\n{(r.stdout + r.stderr)[-3000:]}")


def _models_in_order(manifest: Dict) -> List[Dict]:
    nodes = {k: v for k, v in manifest["nodes"].items() if v["resource_type"] == "model"}
    done, out = set(), []

    def visit(k: str) -> None:
        if k in done:
            return
        for dep in nodes[k]["depends_on"]["nodes"]:
            if dep in nodes:
                visit(dep)
        done.add(k)
        out.append(nodes[k])

    for k in sorted(nodes):
        visit(k)
    return out


def check(warehouse: str, project: Path, native: Path) -> List[str]:
    import duckdb
    import sqlglot
    from sqlglot import exp

    dialect = WAREHOUSES[warehouse]
    tdir = project / f"target-{warehouse}"
    manifest = json.loads((tdir / "manifest.json").read_text())
    con = duckdb.connect()
    con.execute(f"ATTACH '{native}' AS native (READ_ONLY)")
    con.execute("CREATE SCHEMA cs_engine")
    seeds = [n for n in manifest["nodes"].values() if n["resource_type"] == "seed"]
    for seed in seeds:
        con.execute(f'CREATE TABLE cs_engine."{seed["name"]}" AS SELECT * FROM native.main."{seed["name"]}"')
    problems: List[str] = []
    for node in _models_in_order(manifest):
        sql = (tdir / "compiled" / "cs_claude_engine" / node["original_file_path"]).read_text()
        try:
            tree = sqlglot.parse_one(sql, read=dialect)
        except Exception as e:  # noqa: BLE001
            problems.append(f"{node['name']}: does not parse as {dialect}: {str(e)[:300]}")
            continue
        for table in tree.find_all(exp.Table):
            table.set("catalog", None)
            if table.args.get("db"):
                table.set("db", exp.to_identifier("cs_engine"))
        try:
            con.execute(f'CREATE TABLE cs_engine."{node["name"]}" AS {tree.sql(dialect="duckdb")}')
        except Exception as e:  # noqa: BLE001
            problems.append(f"{node['name']}: translated SQL fails on DuckDB: {str(e)[:300]}")
    for mart, keys in MARTS.items():
        cols = [c for (c,) in con.execute(
            "select column_name from information_schema.columns where table_catalog = 'native' "
            f"and table_schema = 'main' and table_name = '{mart}' and column_name <> 'computed_at' "
            "order by ordinal_position").fetchall()]
        sel = ", ".join(f'"{c}"' for c in cols)
        try:
            only_native = con.execute(f'select count(*) from (select {sel} from native.main."{mart}" '
                                      f'except all select {sel} from cs_engine."{mart}")').fetchone()[0]
            only_wh = con.execute(f'select count(*) from (select {sel} from cs_engine."{mart}" '
                                  f'except all select {sel} from native.main."{mart}")').fetchone()[0]
        except Exception as e:  # noqa: BLE001
            problems.append(f"{mart}: comparison failed: {str(e)[:300]}")
            continue
        rows = con.execute(f'select count(*) from native.main."{mart}"').fetchone()[0]
        status = "match" if only_native == only_wh == 0 else f"{only_native} rows differ"
        print(f"  {warehouse:<10} {mart:<28} {rows:>5} rows  {status}")
        if only_native or only_wh:
            on = " and ".join(f'a."{k}" is not distinct from b."{k}"' for k in keys)
            bad = [c for c in cols if c not in keys and con.execute(
                f'select count(*) from native.main."{mart}" a join cs_engine."{mart}" b on {on} '
                f'where a."{c}" is distinct from b."{c}"').fetchone()[0]]
            problems.append(f"{mart}: {only_native} native rows and {only_wh} {warehouse} rows differ; columns: {bad}")
    return problems


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--warehouse", choices=sorted(WAREHOUSES), action="append",
                    help="check only this warehouse (repeatable); default all three")
    ap.add_argument("--keep", action="store_true", help="keep the scratch project for inspection")
    args = ap.parse_args(argv)
    targets = args.warehouse or list(WAREHOUSES)

    workdir = Path(tempfile.mkdtemp(prefix="cse_wh_"))
    project = workdir / "dbt"
    shutil.copytree(DBT, project, ignore=shutil.ignore_patterns("target", "logs", "*.duckdb", "ci"))
    for macro in (DBT / "ci" / "offline_macros").glob("*.sql"):
        shutil.copy(macro, project / "macros" / macro.name)
    prof = _profiles(workdir)
    failures: List[str] = []
    try:
        print("native DuckDB build from the bundled seeds")
        _dbt(project, prof, "seed", "--target", "duckdb")
        _dbt(project, prof, "run", "--target", "duckdb")
        native = project / "native.duckdb"
        for wh in targets:
            print(f"{wh}: compiling offline with the real adapter")
            try:
                _dbt(project, prof, "compile", "--target", wh, "--no-introspect", "--no-populate-cache",
                     "--vars", "{cse_offline_compile: true}", "--target-path", f"target-{wh}")
            except RuntimeError as e:
                failures.append(f"{wh}: {e}")
                continue
            failures += [f"{wh}: {p}" for p in check(wh, project, native)]
    finally:
        if not args.keep:
            shutil.rmtree(workdir, ignore_errors=True)
        else:
            print(f"scratch project kept at {workdir}")
    for f in failures:
        print(f"FAIL {f}")
    print("WAREHOUSES OK" if not failures else f"{len(failures)} problem(s)")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
