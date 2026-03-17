import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from generate_portrait import (
    mine_signals,
    mine_personal_content,
    mine_identity_from_config,
    build_how_you_see_the_world,
    build_what_you_care_about,
    build_your_mission,
    build_your_vibe,
    build_what_you_love,
    build_what_you_cant_stand,
    build_how_you_connect,
    build_the_tension,
    generate_html,
)
from collections import Counter, defaultdict
from datetime import datetime


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
                "text": "Fix the auth bug in Berlin please. Tell Gourav about the marathon training app we're building with React.",
                "word_count": 17,
                "specificity": 6,
                "corrections": [],
                "frustration": {},
                "is_first": True,
                "first_msg_category": "bug_report",
                "timestamp": "2026-01-15T10:00:00Z",
            }
        ]
    if timestamps is None:
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
        sessions = [_make_session() for _ in range(25)]
    # Build texts from session prompts for realistic content mining
    all_texts = []
    for s in sessions:
        for p in s["prompts"]:
            all_texts.append(p["text"])
    if not all_texts:
        all_texts = ["Fix the auth bug please"] * len(sessions)
    # Build word counter from actual texts
    wc = Counter()
    for t in all_texts:
        for w in t.lower().split():
            wc[w] += 1
    base = {
        "sessions": sessions,
        "all_user_texts": all_texts,
        "word_counter": wc,
        "bigram_counter": Counter({("fix", "auth"): 25}),
        "hour_counts": defaultdict(int, {10: len(sessions)}),
        "day_hour_counts": defaultdict(int, {(2, 10): len(sessions)}),
        "monthly_data": defaultdict(
            lambda: {"niceness": [], "specificity": [], "success": []},
            {"2026-01": {"niceness": [6.0] * len(sessions), "specificity": [6.0] * len(sessions), "success": [1] * len(sessions)}},
        ),
    }
    base.update(overrides)
    return base


def _make_personal():
    """Create a minimal personal content dict for narrative tests."""
    return {
        "people": [
            {"name": "Gourav", "count": 50, "contexts": ["Tell Gourav about the project"]},
            {"name": "Jannik", "count": 20, "contexts": ["Meeting with Jannik"]},
        ],
        "locations": {"Berlin": 30, "Bangalore": 10},
        "location_contexts": {"Berlin": ["working from Berlin"], "Bangalore": ["Gourav in Bangalore"]},
        "interests": {
            "fitness": {"total": 15, "terms": {"marathon": 8, "running": 7}},
            "music": {"total": 10, "terms": {"techno": 5, "rave": 5}},
        },
        "ventures": [
            {"name": "OpenPaper", "sessions": 100, "text_mentions": 50, "dominant_category": "BUILD", "success_rate": 75.0},
            {"name": "Rocketlist", "sessions": 40, "text_mentions": 20, "dominant_category": "FIX", "success_rate": 80.0},
            {"name": "SignalDash", "sessions": 20, "text_mentions": 10, "dominant_category": "BUILD", "success_rate": 65.0},
        ],
        "values": Counter({"quality_obsession": 25, "shipping_velocity": 18, "systematic_thinking": 12, "autonomy": 15}),
        "self_references": ["building tools for researchers", "a founder"],
        "goals": ["build the best research paper platform", "ship the MVP by March"],
    }


class TestMineSignals:
    def test_returns_all_keys(self):
        data = _make_data()
        signals = mine_signals(data)
        expected = {
            "sessions_analyzed", "total_prompts", "total_hours", "avg_duration",
            "avg_niceness", "niceness_stddev", "min_niceness", "max_niceness",
            "gave_up_pct", "switched_pct", "retried_pct", "total_errors",
            "frustration_count", "frustration_per_session", "all_caps_count",
            "question_ratio", "numbered_steps_pct", "unique_projects",
            "top_projects", "build_pct", "fix_pct", "explore_pct",
            "mixed_pct", "deploy_pct", "dominant_category", "generic_session_pct",
            "success_pct", "abandoned_pct", "correction_rate", "correction_total",
            "total_commits", "deploy_count", "avg_words_per_prompt",
            "prompts_per_session", "avg_spec", "guiraud", "unique_words",
            "nice_word_count", "please_count", "thanks_count", "total_swears",
            "swear_rate", "swear_peak_hour", "positive_ending_pct",
            "night_session_pct", "morning_session_pct", "afternoon_session_pct",
            "peak_start", "weekend_pct", "morning_success", "evening_success",
            "lang_count", "languages", "avg_first_msg_ratio", "monthly_niceness",
            "months_sorted", "month_count", "top_words", "goal_phrases",
            "dominant_goal_phrase", "total_goal_phrases",
            "guiraud_frustrated", "guiraud_calm", "duration_cv", "max_streak",
            "all_timestamps", "swear_words_counter",
        }
        assert expected.issubset(set(signals.keys()))

    def test_session_count(self):
        data = _make_data()
        signals = mine_signals(data)
        assert signals["sessions_analyzed"] == 25

    def test_empty_sessions(self):
        data = _make_data([])
        signals = mine_signals(data)
        assert signals == {}

    def test_success_pct_all_success(self):
        sessions = [_make_session(outcome="SUCCESS") for _ in range(10)]
        data = _make_data(sessions)
        signals = mine_signals(data)
        assert signals["success_pct"] == 100.0

    def test_success_pct_all_failure(self):
        sessions = [_make_session(outcome="FAILURE") for _ in range(10)]
        data = _make_data(sessions)
        signals = mine_signals(data)
        assert signals["success_pct"] == 0.0


class TestMinePersonalContent:
    def test_returns_all_keys(self):
        data = _make_data()
        personal = mine_personal_content(data)
        expected = {"people", "locations", "location_contexts", "interests",
                    "ventures", "values", "self_references", "goals"}
        assert expected == set(personal.keys())

    def test_discovers_locations_from_text(self):
        data = _make_data()
        personal = mine_personal_content(data)
        assert "Berlin" in personal["locations"]

    def test_discovers_ventures_from_sessions(self):
        data = _make_data()
        personal = mine_personal_content(data)
        assert len(personal["ventures"]) > 0
        assert personal["ventures"][0]["name"] == "TestProject"

    def test_discovers_people_from_text(self):
        """Gourav appears in relational context ('Tell Gourav') and should be discovered."""
        data = _make_data()
        personal = mine_personal_content(data)
        names = [p["name"] for p in personal["people"]]
        assert "Gourav" in names

    def test_filters_tech_terms(self):
        """React appears in texts but should be filtered out as tech term."""
        data = _make_data()
        personal = mine_personal_content(data)
        names = [p["name"] for p in personal["people"]]
        assert "React" not in names

    def test_empty_data(self):
        data = _make_data([])
        personal = mine_personal_content(data)
        assert personal["people"] == []
        assert personal["locations"] == {}
        assert personal["ventures"] == []

    def test_interest_detection(self):
        data = _make_data()
        personal = mine_personal_content(data)
        # "marathon" and "training" appear in default prompt text
        if "fitness" in personal["interests"]:
            assert personal["interests"]["fitness"]["total"] > 0


class TestNarratives:
    def _get_signals(self, **overrides):
        data = _make_data()
        signals = mine_signals(data)
        signals.update(overrides)
        return signals

    def _get_personal(self):
        return _make_personal()

    def test_how_you_see_the_world_not_empty(self):
        s = self._get_signals()
        p = self._get_personal()
        text = build_how_you_see_the_world(s, p)
        assert len(text) > 50

    def test_what_you_care_about_not_empty(self):
        s = self._get_signals()
        p = self._get_personal()
        text = build_what_you_care_about(s, p)
        assert len(text) > 50

    def test_your_mission_not_empty(self):
        s = self._get_signals()
        p = self._get_personal()
        text = build_your_mission(s, p)
        assert len(text) > 50

    def test_your_vibe_not_empty(self):
        s = self._get_signals()
        p = self._get_personal()
        text = build_your_vibe(s, p)
        assert len(text) > 50

    def test_what_you_love_not_empty(self):
        s = self._get_signals()
        p = self._get_personal()
        text = build_what_you_love(s, p)
        assert len(text) > 50

    def test_what_you_cant_stand_not_empty(self):
        s = self._get_signals()
        p = self._get_personal()
        text = build_what_you_cant_stand(s, p)
        assert len(text) > 50

    def test_how_you_connect_not_empty(self):
        s = self._get_signals()
        p = self._get_personal()
        text = build_how_you_connect(s, p)
        assert len(text) > 50

    def test_how_you_connect_mentions_people(self):
        s = self._get_signals()
        p = self._get_personal()
        text = build_how_you_connect(s, p)
        assert "Gourav" in text or "Person" in text

    def test_the_tension_not_empty(self):
        s = self._get_signals()
        p = self._get_personal()
        text = build_the_tension(s, p)
        assert len(text) > 50

    def test_what_you_care_about_mentions_values(self):
        s = self._get_signals()
        p = self._get_personal()
        text = build_what_you_care_about(s, p)
        # Should mention values, interests, or projects
        assert "values" in text.lower() or "interest" in text.lower() or "project" in text.lower() or "thread" in text.lower()

    def test_how_you_see_the_world_mentions_philosophy(self):
        s = self._get_signals()
        p = self._get_personal()
        text = build_how_you_see_the_world(s, p)
        # Should express worldview / beliefs
        assert "believe" in text.lower() or "independence" in text.lower() or "worldview" in text.lower() or "principle" in text.lower() or "systems" in text.lower()


def _make_identity():
    """Create a minimal identity dict for tests (avoids reading real config files)."""
    return {
        "principles": [
            {"name": "KISS", "description": "Keep it simple. Simplest solution that works."},
            {"name": "Engine, not template", "description": "Fix the engine, not the example."},
            {"name": "Root cause, not quick fix", "description": "Diagnose and fix the underlying problem."},
            {"name": "Fail fast", "description": "Surface errors early."},
        ],
        "communication_style": [
            {"rule": "Just do it", "detail": "No preambles, no parroting back"},
            {"rule": "Be direct", "detail": "No I believe, I think, It appears"},
            {"rule": "Be concise", "detail": "No over-explaining, no filler phrases"},
        ],
        "design_values": [
            {"rule": "No emojis in UI", "detail": "Use proper SVG icons or plain text"},
            {"rule": "No colored left borders on cards", "detail": "AI slop"},
            {"rule": "No gradient backgrounds on every element", "detail": "One subtle gradient max"},
        ],
        "pet_peeves": [
            {"rule": "NEVER say should", "detail": "BANNED. Verify instead."},
            {"rule": "No em dashes", "detail": "Use commas, semicolons, colons instead"},
        ],
        "infrastructure": ["All dev servers, heavy compute → AX41"],
        "work_methodology": ["The ratio: 80% reading, 20% writing."],
        "quality_bar": ["Do NOT return until genuinely 10/10."],
        "projects_described": [
            {"name": "Rocketlist", "description": "Website Scoring, Scoring System"},
            {"name": "OpenPaper", "description": "codex session, E2E Testing Issues"},
        ],
        "raw_sections": {},
    }


class TestMineIdentity:
    def test_returns_all_keys(self):
        identity = mine_identity_from_config()
        expected = {"principles", "communication_style", "design_values",
                    "pet_peeves", "infrastructure", "work_methodology",
                    "quality_bar", "projects_described", "raw_sections"}
        assert expected == set(identity.keys())

    def test_empty_when_sanitized(self):
        import generate_portrait
        old = generate_portrait.SANITIZE
        generate_portrait.SANITIZE = True
        try:
            identity = mine_identity_from_config()
            assert identity["principles"] == []
            assert identity["communication_style"] == []
        finally:
            generate_portrait.SANITIZE = old


class TestEndToEnd:
    def test_generate_html_runs(self):
        """Full pipeline produces valid HTML with all placeholders replaced."""
        data = _make_data()
        signals = mine_signals(data)
        html = generate_html(data, signals, identity=_make_identity())

        assert "<!DOCTYPE html>" in html
        assert "__PT_" not in html, f"Unreplaced placeholder found in HTML"
        assert "How AI Sees You" in html
        assert "How You See the World" in html
        assert "What You Care About" in html
        assert "Your Mission" in html
        assert "Your Vibe" in html
        assert "What You Love" in html
        assert "What You Can't Stand" in html  # note: apostrophe in HTML
        assert "How You Connect" in html
        assert "The Tension" in html

    def test_html_no_stat_boxes(self):
        """No metric cards in the output."""
        data = _make_data()
        signals = mine_signals(data)
        html = generate_html(data, signals, identity=_make_identity())
        assert "metric-card" not in html
        assert "Sessions Observed" not in html
        assert "Hours Together" not in html

    def test_html_no_heatmap(self):
        """No heatmap in the output."""
        data = _make_data()
        signals = mine_signals(data)
        html = generate_html(data, signals, identity=_make_identity())
        assert "heatmapContainer" not in html
        assert "heatmap-cell" not in html

    def test_html_dark_mode_support(self):
        data = _make_data()
        signals = mine_signals(data)
        html = generate_html(data, signals, identity=_make_identity())
        assert "prefers-color-scheme: dark" in html
        assert "toggleTheme" in html

    def test_html_pdf_support(self):
        data = _make_data()
        signals = mine_signals(data)
        html = generate_html(data, signals, identity=_make_identity())
        assert "window.print()" in html
        assert "@media print" in html

    def test_html_contains_personal_content(self):
        """Generated HTML should contain personal entities from the data."""
        data = _make_data()
        signals = mine_signals(data)
        html = generate_html(data, signals, identity=_make_identity())
        # Berlin appears in test data texts, should be discoverable
        assert "Berlin" in html or "location" in html.lower()

    def test_html_with_identity_data(self):
        """Generated HTML should contain identity-derived content."""
        data = _make_data()
        signals = mine_signals(data)
        identity = _make_identity()
        html = generate_html(data, signals, identity=identity)
        # Should contain references to principles or config-derived content
        assert "KISS" in html or "engine" in html.lower() or "codified" in html.lower() or "philosophy" in html.lower()
