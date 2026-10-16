"""
Default catalogs the prompts need when the deployment hasn't supplied its own.
Replace from the warehouse / CS Ops quarterly; every value here is a placeholder, not a benchmark
you should quote to a customer. Resolved by `catalog:<name>` in prompt headers.
"""

from __future__ import annotations

from typing import Any, Dict

# Segment medians (docs/02_METRICS_TAXONOMY.md Part E)
DEFAULT_BENCHMARKS: Dict[str, Dict[str, Any]] = {
    "enterprise": {"grr_ttm": 0.92, "nrr_ttm": 1.18, "health_green_median": 82, "dau_mau": 0.38, "feature_depth_green_median": 0.62, "seat_utilization": 0.78, "ttv_p50_days": 45, "ttv_p75_days": 70, "multithread_depth": 4, "ecri_median": 28, "arr_per_csm_target": 6_500_000, "power_user_ratio_green_median": 0.30},
    "mid_market": {"grr_ttm": 0.88, "nrr_ttm": 1.10, "health_green_median": 80, "dau_mau": 0.32, "feature_depth_green_median": 0.55, "seat_utilization": 0.74, "ttv_p50_days": 21, "ttv_p75_days": 35, "multithread_depth": 3, "ecri_median": 32, "arr_per_csm_target": 3_000_000, "power_user_ratio_green_median": 0.25},
    "smb": {"grr_ttm": 0.80, "nrr_ttm": 1.02, "health_green_median": 78, "dau_mau": 0.28, "feature_depth_green_median": 0.48, "seat_utilization": 0.70, "ttv_p50_days": 10, "ttv_p75_days": 18, "multithread_depth": 2, "ecri_median": 38, "arr_per_csm_target": 4_500_000, "power_user_ratio_green_median": 0.20},
    "digital": {"grr_ttm": 0.75, "nrr_ttm": 1.00, "health_green_median": 76, "dau_mau": 0.22, "feature_depth_green_median": 0.40, "seat_utilization": 0.65, "ttv_p50_days": 7, "ttv_p75_days": 14, "multithread_depth": 1, "ecri_median": 45, "arr_per_csm_target": 10_000_000, "power_user_ratio_green_median": 0.15},
}

DEFAULT_VALUE_MILESTONES: Dict[str, Any] = {
    "primary": ["first_production_workflow", "integration_connected", "five_active_users"],
    "definitions": {
        "first_production_workflow": {"prerequisites": ["integration_connected", "admin_assigned"], "description": "A workflow executed against production data"},
        "integration_connected": {"prerequisites": ["admin_assigned"], "description": "At least one source system connected"},
        "five_active_users": {"prerequisites": ["training_delivered"], "description": "Five distinct users with ≥ 3 sessions in a week"},
        "first_report_shared": {"prerequisites": ["first_production_workflow"], "description": "A report shared outside the admin team"},
    },
}

DEFAULT_FEATURE_CATALOG = [
    {"feature_key": "dashboards", "is_core": True, "retention_lift": 0.06, "prerequisites": [], "target_personas": ["end_user", "ops_manager"], "enablement_assets": [{"id": "EA-101", "type": "video", "duration_min": 6}], "typical_time_to_adopt_days": 7, "module": "core", "green_peer_adoption": 0.92},
    {"feature_key": "alerts", "is_core": True, "retention_lift": 0.08, "prerequisites": ["dashboards"], "target_personas": ["ops_manager"], "enablement_assets": [{"id": "EA-102", "type": "doc", "duration_min": 10}], "typical_time_to_adopt_days": 10, "module": "core", "green_peer_adoption": 0.81},
    {"feature_key": "workflow_automation", "is_core": True, "retention_lift": 0.14, "prerequisites": ["integration_connected:crm"], "target_personas": ["ops_manager", "admin"], "enablement_assets": [{"id": "EA-201", "type": "live_session", "duration_min": 45}], "typical_time_to_adopt_days": 21, "module": "core", "green_peer_adoption": 0.68},
    {"feature_key": "api_access", "is_core": True, "retention_lift": 0.09, "prerequisites": [], "target_personas": ["developer"], "enablement_assets": [{"id": "EA-301", "type": "doc", "duration_min": 20}], "typical_time_to_adopt_days": 14, "module": "core", "green_peer_adoption": 0.44},
    {"feature_key": "scheduled_reports", "is_core": False, "retention_lift": 0.03, "prerequisites": ["dashboards"], "target_personas": ["end_user"], "enablement_assets": [{"id": "EA-103", "type": "video", "duration_min": 4}], "typical_time_to_adopt_days": 5, "module": "core", "green_peer_adoption": 0.58},
    {"feature_key": "audit_log", "is_core": False, "retention_lift": 0.04, "prerequisites": [], "target_personas": ["it_security"], "enablement_assets": [{"id": "EA-401", "type": "doc", "duration_min": 8}], "typical_time_to_adopt_days": 7, "module": "security", "green_peer_adoption": 0.35},
    {"feature_key": "sso_scim", "is_core": False, "retention_lift": 0.11, "prerequisites": [], "target_personas": ["it_security", "admin"], "enablement_assets": [{"id": "EA-402", "type": "live_session", "duration_min": 30}], "typical_time_to_adopt_days": 14, "module": "security", "green_peer_adoption": 0.52},
    {"feature_key": "advanced_permissions", "is_core": False, "retention_lift": 0.07, "prerequisites": ["sso_scim"], "target_personas": ["admin"], "enablement_assets": [{"id": "EA-403", "type": "doc", "duration_min": 12}], "typical_time_to_adopt_days": 10, "module": "security", "green_peer_adoption": 0.40},
]

DEFAULT_PRICING_CATALOG: Dict[str, Any] = {
    "tiers": [
        {"tier": "team", "list_price_per_seat_annual": 480, "seat_pack": 5, "gated_features": []},
        {"tier": "business", "list_price_per_seat_annual": 840, "seat_pack": 10, "gated_features": ["audit_log", "api_access"]},
        {"tier": "enterprise", "list_price_per_seat_annual": 1200, "seat_pack": 25, "gated_features": ["workflow_automation"]},
        {"tier": "enterprise_plus", "list_price_per_seat_annual": 1560, "seat_pack": 25, "gated_features": ["sso_scim", "advanced_permissions"]},
    ],
    "modules": [
        {"module": "security", "list_price_per_seat_annual": 240, "target_personas": ["it_security", "admin"]},
        {"module": "analytics_plus", "list_price_per_seat_annual": 360, "target_personas": ["ops_manager", "economic_buyer"]},
    ],
    "sales_assist_threshold_arr": {"digital": 12_000, "smb": 20_000, "mid_market": 0, "enterprise": 0},
}

DEFAULT_ROI_INPUTS: Dict[str, Any] = {
    "loaded_hourly_rate": None,
    "loaded_hourly_rate_source": "not supplied — ask customer finance; do not assume",
    "notes": "Populate from CS Ops roi_inputs table per account before EBR generation.",
}

CATALOGS: Dict[str, Any] = {
    "benchmarks": DEFAULT_BENCHMARKS,
    "value_milestones": DEFAULT_VALUE_MILESTONES,
    "feature_catalog": DEFAULT_FEATURE_CATALOG,
    "pricing": DEFAULT_PRICING_CATALOG,
    "roi_inputs": DEFAULT_ROI_INPUTS,
}
