import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from generate_portrait import (
    mine_signals,
    build_first_impression,
    build_what_you_care_about,
    build_how_you_treat_others,
    build_your_drive,
    build_temperament,
    build_your_mind,
    build_your_habits,
    build_what_id_tell_you,
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
                "text": "Fix the auth bug please",
                "word_count": 5,
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
    base = {
        "sessions": sessions,
        "all_user_texts": ["Fix the auth bug please"] * len(sessions),
        "word_counter": Counter({"fix": 25, "auth": 25, "bug": 25, "please": 25}),
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


class TestNarratives:
    def _get_signals(self, **overrides):
        data = _make_data()
        signals = mine_signals(data)
        signals.update(overrides)
        return signals

    def test_first_impression_not_empty(self):
        s = self._get_signals()
        text = build_first_impression(s)
        assert len(text) > 50
        assert str(s["sessions_analyzed"]) in text

    def test_what_you_care_about_not_empty(self):
        s = self._get_signals()
        text = build_what_you_care_about(s)
        assert len(text) > 50

    def test_how_you_treat_others_not_empty(self):
        s = self._get_signals()
        text = build_how_you_treat_others(s)
        assert len(text) > 50
        assert "/10" in text  # niceness score

    def test_your_drive_not_empty(self):
        s = self._get_signals()
        text = build_your_drive(s)
        assert len(text) > 50

    def test_temperament_not_empty(self):
        s = self._get_signals()
        text = build_temperament(s)
        assert len(text) > 50

    def test_your_mind_not_empty(self):
        s = self._get_signals()
        text = build_your_mind(s)
        assert len(text) > 50

    def test_your_habits_not_empty(self):
        s = self._get_signals()
        text = build_your_habits(s)
        assert len(text) > 50

    def test_what_id_tell_you_not_empty(self):
        s = self._get_signals()
        text = build_what_id_tell_you(s)
        assert len(text) > 50


class TestEndToEnd:
    def test_generate_html_runs(self):
        """Full pipeline produces valid HTML with all placeholders replaced."""
        data = _make_data()
        signals = mine_signals(data)
        html = generate_html(data, signals)

        assert "<!DOCTYPE html>" in html
        assert "__PT_" not in html, f"Unreplaced placeholder found in HTML"
        assert "How AI Sees You" in html
        assert "First Impression" in html
        assert "What You Care About" in html
        assert "How You Treat Others" in html
        assert "Your Drive" in html
        assert "Your Temperament" in html
        assert "Your Mind" in html
        assert "Your Habits" in html

    def test_html_dark_mode_support(self):
        data = _make_data()
        signals = mine_signals(data)
        html = generate_html(data, signals)
        assert "prefers-color-scheme: dark" in html
        assert "toggleTheme" in html

    def test_html_pdf_support(self):
        data = _make_data()
        signals = mine_signals(data)
        html = generate_html(data, signals)
        assert "window.print()" in html
        assert "@media print" in html
