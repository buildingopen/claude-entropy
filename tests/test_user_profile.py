import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from generate_user_profile import (
    compute_dimensions,
    dimension_label,
    select_archetype,
    ARCHETYPES,
    analyze_builder_identity,
    analyze_error_personality,
    analyze_project_loyalty,
    compute_ai_relationship,
    compute_evolution,
    generate_html,
)
from collections import Counter, defaultdict


def _make_session(
    outcome="SUCCESS",
    category="BUILD",
    duration_min=20.0,
    abandoned=False,
    has_loop=False,
    error_rate=3.0,
    prompts=None,
    deployments=0,
    project="TestProject",
    timestamps=None,
    tone=None,
    error_sequences=None,
    **overrides,
):
    if prompts is None:
        prompts = [
            {
                "text": "Fix the auth bug",
                "word_count": 4,
                "specificity": 6,
                "corrections": [],
                "frustration": {},
                "is_first": True,
                "first_msg_category": "bug_report",
                "timestamp": "2026-01-15T10:00:00Z",
            }
        ]
    if timestamps is None:
        from datetime import datetime
        timestamps = [datetime(2026, 1, 15, 10, 0)]
    if tone is None:
        tone = {
            "niceness_score": 6.0,
            "user_swears": 0,
            "user_nice": 3,
            "user_harsh": 0,
            "user_msg_count": 5,
            "user_swear_words": {},
            "user_nice_words": {"please": 2, "thanks": 1},
            "user_harsh_words": {},
            "swears_by_hour": {},
            "nice_by_hour": {10: 3},
        }
    if error_sequences is None:
        error_sequences = []

    base = {
        "filepath": "/tmp/test.jsonl",
        "project": project,
        "outcome": outcome,
        "category": category,
        "error_rate": error_rate,
        "files_edited": 3,
        "commits": 1,
        "deployments": deployments,
        "has_loop": has_loop,
        "abandoned": abandoned,
        "duration_min": duration_min,
        "total_tool_uses": 20,
        "prompts": prompts,
        "correction_count": sum(1 for p in prompts if p.get("corrections")),
        "frustration_count": sum(1 for p in prompts if p.get("frustration")),
        "timestamps": timestamps,
        "tone": tone,
        "error_sequences": error_sequences,
        "proj_data": None,
    }
    base.update(overrides)
    return base


def _make_data(sessions=None, **overrides):
    if sessions is None:
        sessions = [_make_session() for _ in range(10)]
    base = {
        "sessions": sessions,
        "all_user_texts": ["Fix the auth bug"] * len(sessions),
        "word_counter": Counter({"fix": 10, "auth": 10, "bug": 10}),
        "bigram_counter": Counter({("fix", "auth"): 10}),
        "hour_counts": defaultdict(int, {10: len(sessions)}),
        "day_hour_counts": defaultdict(int, {(2, 10): len(sessions)}),
        "monthly_data": defaultdict(
            lambda: {"niceness": [], "specificity": [], "success": []},
            {"2026-01": {"niceness": [6.0] * len(sessions), "specificity": [6.0] * len(sessions), "success": [1] * len(sessions)}},
        ),
    }
    base.update(overrides)
    return base


class TestDimensions:
    def test_all_dimensions_present(self):
        data = _make_data()
        dims = compute_dimensions(data)
        expected_keys = {"patience", "precision", "warmth", "ambition", "persistence", "autonomy", "night_owl"}
        assert set(dims.keys()) == expected_keys

    def test_dimensions_in_range(self):
        data = _make_data()
        dims = compute_dimensions(data)
        for name, val in dims.items():
            assert 0 <= val <= 100, f"{name} = {val} out of range"

    def test_patience_low_for_abandoned(self):
        sessions = [_make_session(abandoned=True, duration_min=5) for _ in range(10)]
        data = _make_data(sessions)
        dims = compute_dimensions(data)
        assert dims["patience"] < 50

    def test_patience_high_for_long_sessions(self):
        sessions = [_make_session(abandoned=False, duration_min=45) for _ in range(10)]
        data = _make_data(sessions)
        dims = compute_dimensions(data)
        assert dims["patience"] > 50

    def test_warmth_reflects_niceness(self):
        warm_tone = {
            "niceness_score": 9.0,
            "user_swears": 0, "user_nice": 10, "user_harsh": 0, "user_msg_count": 5,
            "user_swear_words": {}, "user_nice_words": {"please": 5, "thanks": 5},
            "user_harsh_words": {}, "swears_by_hour": {}, "nice_by_hour": {},
        }
        cold_tone = {
            "niceness_score": 1.0,
            "user_swears": 5, "user_nice": 0, "user_harsh": 3, "user_msg_count": 5,
            "user_swear_words": {"damn": 5}, "user_nice_words": {},
            "user_harsh_words": {"stupid": 3}, "swears_by_hour": {}, "nice_by_hour": {},
        }
        warm_sessions = [_make_session(tone=warm_tone) for _ in range(10)]
        cold_sessions = [_make_session(tone=cold_tone) for _ in range(10)]
        warm_dims = compute_dimensions(_make_data(warm_sessions))
        cold_dims = compute_dimensions(_make_data(cold_sessions))
        assert warm_dims["warmth"] > cold_dims["warmth"]

    def test_ambition_high_for_builders(self):
        sessions = [_make_session(category="BUILD", deployments=1) for _ in range(10)]
        data = _make_data(sessions)
        dims = compute_dimensions(data)
        assert dims["ambition"] >= 60

    def test_ambition_low_for_fixers(self):
        sessions = [_make_session(category="FIX", deployments=0) for _ in range(10)]
        data = _make_data(sessions)
        dims = compute_dimensions(data)
        assert dims["ambition"] < 60

    def test_empty_sessions(self):
        data = _make_data([])
        dims = compute_dimensions(data)
        for val in dims.values():
            assert val == 50


class TestDimensionLabel:
    def test_labels(self):
        assert dimension_label("patience", 10) == "Impatient Sprinter"
        assert dimension_label("patience", 50) == "Measured Pacer"
        assert dimension_label("patience", 90) == "Zen Master"
        assert dimension_label("warmth", 10) == "Ice Cold"
        assert dimension_label("warmth", 90) == "Sunshine"


class TestArchetype:
    def test_architect_for_precise_patient_ambitious(self):
        dims = {"patience": 80, "precision": 85, "warmth": 50, "ambition": 70, "persistence": 60, "autonomy": 50, "night_owl": 50}
        arch = select_archetype(dims)
        assert arch in ARCHETYPES

    def test_commander_for_cold_ambitious_autonomous(self):
        dims = {"patience": 50, "precision": 50, "warmth": 15, "ambition": 85, "persistence": 50, "autonomy": 85, "night_owl": 50}
        arch = select_archetype(dims)
        assert arch == "The Commander"

    def test_whisperer_for_warm_patient_precise(self):
        dims = {"patience": 80, "precision": 80, "warmth": 90, "ambition": 50, "persistence": 50, "autonomy": 50, "night_owl": 50}
        arch = select_archetype(dims)
        assert arch == "The Whisperer"

    def test_all_50_returns_valid(self):
        dims = {d: 50 for d in ["patience", "precision", "warmth", "ambition", "persistence", "autonomy", "night_owl"]}
        arch = select_archetype(dims)
        assert arch in ARCHETYPES


class TestBuilderIdentity:
    def test_builder_dominated(self):
        sessions = [_make_session(category="BUILD") for _ in range(8)] + [_make_session(category="FIX") for _ in range(2)]
        result = analyze_builder_identity(_make_data(sessions))
        assert result["identity"] == "Builder"
        assert result["build_pct"] > 50

    def test_firefighter_dominated(self):
        sessions = [_make_session(category="FIX") for _ in range(8)] + [_make_session(category="BUILD") for _ in range(2)]
        result = analyze_builder_identity(_make_data(sessions))
        assert result["identity"] == "Firefighter"


class TestErrorPersonality:
    def test_bulldozer(self):
        seqs = [{"post_action": "retried_same_tool"} for _ in range(6)] + [{"post_action": "switched_approach"}]
        sessions = [_make_session(error_sequences=seqs)]
        result = analyze_error_personality(_make_data(sessions))
        assert result["label"] == "The Bulldozer"

    def test_adapter(self):
        seqs = [{"post_action": "switched_approach"} for _ in range(6)] + [{"post_action": "retried_same_tool"}]
        sessions = [_make_session(error_sequences=seqs)]
        result = analyze_error_personality(_make_data(sessions))
        assert result["label"] == "The Adapter"

    def test_no_errors(self):
        sessions = [_make_session(error_sequences=[])]
        result = analyze_error_personality(_make_data(sessions))
        assert result["label"] == "The Balanced"


class TestProjectLoyalty:
    def test_monogamous(self):
        sessions = [_make_session(project="MainProject") for _ in range(10)]
        result = analyze_project_loyalty(_make_data(sessions))
        assert result["loyalty_label"] == "Monogamous"

    def test_polyamorous(self):
        sessions = [_make_session(project=f"Project{i}") for i in range(10)]
        result = analyze_project_loyalty(_make_data(sessions))
        assert result["loyalty_label"] == "Polyamorous"


class TestAIRelationship:
    def test_best_friends(self):
        dims = {"warmth": 80, "patience": 75, "autonomy": 50, "precision": 50}
        rel = compute_ai_relationship(dims)
        assert rel["type"] == "Best Friends"

    def test_boss_employee(self):
        dims = {"warmth": 20, "patience": 50, "autonomy": 80, "precision": 50}
        rel = compute_ai_relationship(dims)
        assert rel["type"] == "Boss & Employee"


class TestEvolution:
    def test_with_data(self):
        data = _make_data()
        result = compute_evolution(data)
        assert "months" in result
        assert "trend" in result
        assert result["trend"] in ("improving", "declining", "stable")

    def test_empty(self):
        data = _make_data([])
        data["monthly_data"] = defaultdict(lambda: {"niceness": [], "specificity": [], "success": []})
        result = compute_evolution(data)
        assert result["trend"] == "stable"
        assert result["months"] == []


class TestEndToEnd:
    def test_generate_html_runs(self):
        """Full pipeline produces valid HTML with all placeholders replaced."""
        data = _make_data()
        dimensions = compute_dimensions(data)
        archetype = select_archetype(dimensions)
        html = generate_html(data, dimensions, archetype)

        assert "<!DOCTYPE html>" in html
        assert "__UP_" not in html, f"Unreplaced placeholder found in HTML"
        assert "User Profile" in html
        assert archetype in html
