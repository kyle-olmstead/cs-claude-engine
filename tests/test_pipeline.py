"""End-to-end checks that don't need an API key. Run with `pytest -q`."""
import json
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest

from src.claude_client import ClaudeEmitter, InvalidOutputError, schema_for
from src.models.health_score import assert_no_drift, compute_health_score
from src.orchestrator import load_schema, wrap_untrusted
from src.prompts import PromptRegistry
from src.testing import OfflineEmitter
from src.triggers import PLAYBOOKS, evaluate_triggers, registry_table
from src.validation import check_evidence, check_recipients, cooldown_active, enforce_policy, validate_action
from src.views import view_for
from tests.fakes import FakeClient, Resp

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = json.loads((ROOT / "examples/sample_customer_360.json").read_text())
BASE = load_schema("playbook_action.json")


@pytest.fixture
def reg():
    return PromptRegistry()


@pytest.fixture
def view():
    return wrap_untrusted(view_for("retention.churn_risk_rca", SAMPLE))


@pytest.fixture
def good_action(view):
    return OfflineEmitter(BASE).emit("retention.churn_risk_rca", {"playbook_id": "PB-RET-01"}, view, {}, "test").action


# ---- schemas & sample --------------------------------------------------------------

def test_schemas_are_valid_2020_12():
    for name in ("customer_360.json", "playbook_action.json"):
        jsonschema.Draft202012Validator.check_schema(load_schema(name))


def test_sample_validates():
    jsonschema.Draft202012Validator(load_schema("customer_360.json"), format_checker=jsonschema.FormatChecker()).validate(SAMPLE)


# ---- health score -----------------------------------------------------------------

def test_health_score_golden():
    r = compute_health_score(SAMPLE)
    assert round(r.score, 1) == 60.0 and r.band == "yellow"
    assert [o.rule for o in r.overrides_applied] == ["champion_departed_no_replacement"]
    assert_no_drift(r, SAMPLE["health"]["mart_score"])
    assert abs(sum(c.contribution for c in r.components) - r.raw_weighted_sum) < 1e-9


def test_health_score_renormalizes_missing_inputs():
    doc = json.loads(json.dumps(SAMPLE))
    doc["sentiment"]["latest_nps"] = None
    doc["sentiment"]["transcript_sentiment_30d"] = None
    r = compute_health_score(doc)
    sent = next(c for c in r.components if c.name == "sentiment")
    assert sent.normalized == 50.0  # only the "stable" trend input remains → 50


# ---- triggers ---------------------------------------------------------------------

def test_triggers_on_sample():
    fired = {f.spec.playbook_id for f in evaluate_triggers(SAMPLE)}
    assert "PB-RET-01" in fired and "PB-CAD-01" in fired
    assert not fired & {"PB-EXP-01", "PB-EXP-02", "PB-RET-02"}   # P0 suppresses P3; RET-01 subsumes RET-02


def test_cooldown_marks_signal_update():
    doc = json.loads(json.dumps(SAMPLE))
    doc["actions_last_30d"] = [{"action_id": "cse:x:PB-RET-01:2026-10-10", "playbook_id": "PB-RET-01", "status": "open", "emitted_at": "2026-10-10"}]
    fired = {f.spec.playbook_id: f for f in evaluate_triggers(doc)}
    assert fired["PB-RET-01"].signal_update_for == "cse:x:PB-RET-01:2026-10-10"
    assert cooldown_active("PB-RET-01", doc["actions_last_30d"], __import__("datetime").date(2026, 10, 30)) is None  # 20d > 14d window


def test_registry_table_lists_every_playbook():
    table = registry_table()
    for p in PLAYBOOKS:
        assert f"| {p.playbook_id} |" in table


# ---- prompts ----------------------------------------------------------------------

def test_every_prompt_renders(reg):
    assert len(reg) == 8
    for p in reg.prompts.values():
        assert "{{" not in p.render({v: "x" for v in p.inputs})


def test_system_prompt_embeds_generated_registry(reg):
    text = reg.get("core.system_csm_orchestrator").render(
        {"csm_name": "Priya", "today": "2026-10-15", "playbook_registry_table": registry_table(), "segment_benchmarks_json": {}})
    assert "| PB-RET-01 |" in text and "{{" not in text


def test_schema_slicing():
    rca, ebr = schema_for("retention.churn_risk_rca", BASE), schema_for("expansion.executive_ebr_generator", BASE)
    assert "ebr" not in rca["properties"] and "ebr" in ebr["properties"] and "renewal_plan" not in ebr["properties"]
    assert len(json.dumps(rca)) < 0.5 * len(json.dumps(BASE))


# ---- validation & policy ----------------------------------------------------------

def test_evidence_value_mismatch_is_caught(good_action, view):
    bad = json.loads(json.dumps(good_action))
    bad["evidence"][0]["value"] = 41.0
    errors, _ = check_evidence(bad, view)
    assert any("value mismatch at health.score" in e for e in errors)


def test_recipient_must_be_current_stakeholder(good_action, view):
    bad = json.loads(json.dumps(good_action))
    bad["communications"][0]["recipient_contact_id"] = "ct_01"   # the departed champion
    assert any("has left the account" in e for e in check_recipients(bad, view))
    bad["communications"][0]["recipient_contact_id"] = "ct_nobody"
    assert any("not in relationship.stakeholders" in e for e in check_recipients(bad, view))


def test_policy_floors_never_break_schema(good_action, view):
    a = json.loads(json.dumps(good_action))
    a["actions"][0]["crm_write"] = {"object": "opportunity", "field": "amount", "value": 1}
    a["confidence"] = 0.3
    changes = enforce_policy(a)
    assert a["actions"][0]["requires_human_approval"] is True and a["priority"] == "P3" and len(changes) == 2
    assert validate_action(a, view, schema_for("retention.churn_risk_rca", BASE)) == []


# ---- live client path (mocked SDK) -------------------------------------------------

def test_live_client_caches_slices_and_retries(reg, view, good_action):
    sysp = reg.get("core.system_csm_orchestrator").render(
        {"csm_name": "Priya", "today": "2026-10-15", "playbook_registry_table": registry_table(), "segment_benchmarks_json": {}})
    static = {"segment_benchmarks_json": {}, "today": "2026-10-15"}
    bad = json.loads(json.dumps(good_action)); bad["evidence"][0]["value"] = 41.0
    em = ClaudeEmitter(reg, BASE, sysp, client=FakeClient([Resp({"playbook_id": "PB-RET-01"}, stop="max_tokens"), Resp(bad), Resp(good_action)]))
    res = em.emit("retention.churn_risk_rca", static, view, {}, "Run PB-RET-01")
    calls = em.client.messages.calls
    assert len(calls) == 3 and res.retries == 2
    assert calls[0]["system"][1].get("cache_control") == {"type": "ephemeral"}          # body cached
    assert "ebr" not in calls[0]["tools"][0]["input_schema"]["properties"]              # sliced schema
    assert calls[1]["max_tokens"] == int(calls[0]["max_tokens"] * 1.5)                 # truncation headroom
    assert "value mismatch at health.score" in calls[2]["messages"][2]["content"][0]["content"]


def test_live_client_raises_after_second_failure(reg, view, good_action):
    sysp = "system"
    bad = json.loads(json.dumps(good_action)); bad["communications"][0]["recipient_contact_id"] = "ct_01"
    em = ClaudeEmitter(reg, BASE, sysp, client=FakeClient([Resp(bad), Resp(bad)]))
    with pytest.raises(InvalidOutputError) as ei:
        em.emit("retention.churn_risk_rca", {"segment_benchmarks_json": {}, "today": "x"}, view, {}, "x")
    assert len(ei.value.attempts) == 2


# ---- CLI runs -----------------------------------------------------------------------

def test_offline_pipeline(tmp_path):
    out = subprocess.run([sys.executable, "-m", "src.orchestrator", "--input", "examples/sample_customer_360.json", "--offline", "--out", str(tmp_path)],
                         cwd=ROOT, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    summary = json.loads((tmp_path / "run_summary.json").read_text())
    assert {a["playbook_id"] for a in summary["actions"]} == {"PB-RET-01", "PB-CAD-01"} and not summary["errors"]


def test_triggers_only_cli(tmp_path):
    out = subprocess.run([sys.executable, str(ROOT / "src/orchestrator.py"), "--input", str(ROOT / "examples/sample_customer_360.json"), "--triggers-only", "--out", str(tmp_path)],
                         cwd=tmp_path, capture_output=True, text=True)
    assert out.returncode == 0 and (tmp_path / "triggers.json").exists()


def test_validate_cli_repairs_floors(tmp_path):
    f = tmp_path / "a.json"
    view = wrap_untrusted(view_for("retention.churn_risk_rca", SAMPLE))
    action = OfflineEmitter(BASE).emit("retention.churn_risk_rca", {"playbook_id": "PB-RET-01"}, view, {}, "t").action
    action["communications"][0]["requires_human_approval"] = False
    f.write_text(json.dumps(action))
    out = subprocess.run([sys.executable, str(ROOT / "src/validate.py"), "action", str(f), "--c360", str(ROOT / "examples/sample_customer_360.json")],
                         capture_output=True, text=True)
    assert out.returncode == 1 and "requires_human_approval → true" in out.stdout
    assert json.loads(f.read_text())["communications"][0]["requires_human_approval"] is True


def test_roi_model_reproduces_the_memo():
    from scripts.roi_model import Assumptions, model
    m = model(Assumptions())
    assert round(m["per_csm"]["steady_state_loaded"]) == 165_978
    assert round(m["option_b_engine"]["year_1_net"]) == 272_170
    assert round(m["option_b_engine"]["steady_state_net"]) == 318_555
    o = m["open_seat"]                                   # Part 8: one open seat
    assert round(o["unspent_comp_per_month"]) == 13_831
    assert round(o["vacancy_cost_per_departure"]) == 73_463
    assert round(o["engine_cost_over_gap"]) == 16_583
    assert round(o["net_vs_plan"]) == 52_574
    assert 0.54 < o["engine_vs_coverage_risk"] < 0.56
    two = model(Assumptions(open_seats=2))["open_seat"]
    assert round(two["unspent_comp_over_gap"]) == 2 * round(o["unspent_comp_over_gap"]) or abs(two["unspent_comp_over_gap"] - 2 * o["unspent_comp_over_gap"]) < 1e-6
    assert two["engine_cost_over_gap"] == o["engine_cost_over_gap"]   # the engine does not cost more for a second seat
