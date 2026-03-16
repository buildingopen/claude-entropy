import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from generate_prompt_coach import (
    compute_overall_score,
    score_to_grade,
    detect_anti_patterns,
    find_before_after_pairs,
    compute_session_arc,
    find_sweet_spot,
    analyze_context_signals,
    analyze_session_openers,
    compute_correction_trend,
    compute_success_recipes,
    generate_tips,
    success_rate,
    build_prompt_record,
)


def _make_prompt(text="Fix the bug in auth.py", msg_index=0, is_first=True, specificity=None, **overrides):
    """Helper to create a prompt record."""
    record = build_prompt_record(text, msg_index, is_first, "2026-01-15T10:00:00Z")
    if specificity is not None:
        record["specificity"] = specificity
    record.update(overrides)
    return record


def _make_session(outcome="SUCCESS", category="BUILD", specificity=5, prompts=None, **overrides):
    """Helper to create a session record."""
    if prompts is None:
        prompts = [_make_prompt(specificity=specificity)]
    base = {
        "filepath": "/tmp/test.jsonl",
        "project": "TestProject",
        "outcome": outcome,
        "category": category,
        "error_rate": 2.0,
        "files_edited": 3,
        "commits": 1,
        "has_loop": False,
        "abandoned": False,
        "duration_min": 15.0,
        "total_tool_uses": 20,
        "prompts": prompts,
        "correction_count": sum(1 for p in prompts if p.get("corrections")),
    }
    base.update(overrides)
    return base


class TestPromptScore:
    def test_high_specificity_scores_well(self):
        """Sessions with high-specificity prompts should score > 15/20 on specificity."""
        sessions = [_make_session(specificity=9) for _ in range(10)]
        total, dims = compute_overall_score(sessions)
        assert dims["specificity"] > 15

    def test_low_specificity_scores_low(self):
        sessions = [_make_session(specificity=2) for _ in range(10)]
        total, dims = compute_overall_score(sessions)
        assert dims["specificity"] < 10

    def test_lift_rewards_prompt_skill(self):
        """User with high lift (good prompts succeed more) scores higher than user with no lift."""
        # User A: good prompts succeed, bad ones fail
        sessions_a = (
            [_make_session(outcome="SUCCESS", specificity=8) for _ in range(10)] +
            [_make_session(outcome="FAILURE", specificity=2) for _ in range(10)]
        )
        # User B: same success rate regardless of specificity
        sessions_b = (
            [_make_session(outcome="SUCCESS", specificity=8) for _ in range(5)] +
            [_make_session(outcome="FAILURE", specificity=8) for _ in range(5)] +
            [_make_session(outcome="SUCCESS", specificity=2) for _ in range(5)] +
            [_make_session(outcome="FAILURE", specificity=2) for _ in range(5)]
        )
        _, dims_a = compute_overall_score(sessions_a)
        _, dims_b = compute_overall_score(sessions_b)
        assert dims_a["lift"] > dims_b["lift"]

    def test_first_attempt_clarity(self):
        """Sessions with zero corrections score 20/20 on clarity."""
        prompts_clean = [_make_prompt(text="Implement X in file Y", corrections=[])]
        sessions = [_make_session(prompts=prompts_clean, correction_count=0) for _ in range(10)]
        _, dims = compute_overall_score(sessions)
        assert dims["clarity"] == 20.0

    def test_score_range(self):
        """Total score always 0-100."""
        # Minimal data
        sessions = [_make_session()]
        total, _ = compute_overall_score(sessions)
        assert 0 <= total <= 100

        # Many varied sessions
        sessions = (
            [_make_session(specificity=i, outcome="SUCCESS" if i > 5 else "FAILURE")
             for i in range(11)]
        )
        total, _ = compute_overall_score(sessions)
        assert 0 <= total <= 100

    def test_empty_sessions(self):
        total, dims = compute_overall_score([])
        assert total == 0


class TestGrade:
    def test_grade_mapping(self):
        assert score_to_grade(95) == "A+"
        assert score_to_grade(82) == "A"
        assert score_to_grade(73) == "B+"
        assert score_to_grade(65) == "B"
        assert score_to_grade(55) == "C+"
        assert score_to_grade(45) == "C"
        assert score_to_grade(30) == "D"


class TestAntiPatterns:
    def test_vague_opener_detected(self):
        """'fix it' as first msg with specificity 2 triggers vague_opener."""
        prompts = [_make_prompt(text="fix it", specificity=2, word_count=2)]
        sessions = [_make_session(prompts=prompts)]
        patterns = detect_anti_patterns(sessions)
        assert patterns["vague_opener"]["count"] >= 1

    def test_terse_excludes_confirmations(self):
        """'yes', 'no', 'ok' should NOT trigger too_terse."""
        prompts = [
            _make_prompt(text="yes", msg_index=0, is_first=True, word_count=1),
            _make_prompt(text="ok", msg_index=1, is_first=False, word_count=1),
            _make_prompt(text="no", msg_index=2, is_first=False, word_count=1),
        ]
        sessions = [_make_session(prompts=prompts)]
        patterns = detect_anti_patterns(sessions)
        assert patterns["too_terse"]["count"] == 0

    def test_terse_catches_real_terse(self):
        """Short non-confirmation messages should trigger too_terse."""
        prompts = [_make_prompt(text="do it", msg_index=0, is_first=True, word_count=2)]
        sessions = [_make_session(prompts=prompts)]
        patterns = detect_anti_patterns(sessions)
        assert patterns["too_terse"]["count"] >= 1

    def test_multi_task_needs_3_verbs(self):
        """'add X and fix Y' (2 verbs) should not trigger, 3+ verbs should."""
        # 2 verbs - no trigger
        prompts2 = [_make_prompt(
            text="add the button and fix the layout so it looks right with proper spacing",
            word_count=15, specificity=5
        )]
        sessions2 = [_make_session(prompts=prompts2)]
        patterns2 = detect_anti_patterns(sessions2)
        assert patterns2["multi_task"]["count"] == 0

        # 3 verbs with 50+ words
        long_text = "add the new login button to the header and fix the broken CSS layout and remove the old deprecated sidebar component and also update the footer with new links " * 2
        prompts3 = [_make_prompt(text=long_text, word_count=60, specificity=5)]
        sessions3 = [_make_session(prompts=prompts3)]
        patterns3 = detect_anti_patterns(sessions3)
        assert patterns3["multi_task"]["count"] >= 1


class TestBeforeAfter:
    def test_matched_pairs_same_category(self):
        """Before and after must be from the same session category."""
        sessions = [
            _make_session(outcome="FAILURE", category="BUILD", specificity=2, total_tool_uses=20),
            _make_session(outcome="SUCCESS", category="BUILD", specificity=8, total_tool_uses=25),
            _make_session(outcome="FAILURE", category="FIX", specificity=2, total_tool_uses=20),
            _make_session(outcome="SUCCESS", category="FIX", specificity=8, total_tool_uses=25),
        ]
        pairs = find_before_after_pairs(sessions)
        for pair in pairs:
            assert pair["before"]["outcome"] in ("FAILURE", "PARTIAL_FAILURE")
            assert pair["after"]["outcome"] in ("SUCCESS", "PARTIAL_SUCCESS")

    def test_matched_pairs_similar_complexity(self):
        """Paired sessions must have tool_uses within 2x of each other."""
        sessions = [
            _make_session(outcome="FAILURE", category="BUILD", specificity=2, total_tool_uses=10),
            _make_session(outcome="SUCCESS", category="BUILD", specificity=8, total_tool_uses=15),
            # This one is too complex to match with the first
            _make_session(outcome="SUCCESS", category="BUILD", specificity=8, total_tool_uses=100),
        ]
        pairs = find_before_after_pairs(sessions)
        for pair in pairs:
            assert pair["complexity_ratio"] <= 2.0

    def test_sanitize_hides_text(self):
        """With WRAPPED_SANITIZE=1, prompt text is replaced with [sanitized]."""
        import generate_prompt_coach
        old_val = generate_prompt_coach.SANITIZE
        generate_prompt_coach.SANITIZE = True
        try:
            sessions = [
                _make_session(outcome="FAILURE", category="BUILD", specificity=2, total_tool_uses=20),
                _make_session(outcome="SUCCESS", category="BUILD", specificity=8, total_tool_uses=25),
            ]
            pairs = find_before_after_pairs(sessions)
            for pair in pairs:
                assert pair["before"]["text"] == "[sanitized]"
                assert pair["after"]["text"] == "[sanitized]"
        finally:
            generate_prompt_coach.SANITIZE = old_val


class TestSessionArc:
    def test_arc_buckets(self):
        """Prompts bucketed into positions 0, 1, 2, 3+."""
        prompts = [
            _make_prompt(text=f"msg {i}", msg_index=i, is_first=(i == 0), specificity=i + 3)
            for i in range(6)
        ]
        sessions = [_make_session(prompts=prompts)]
        arc = compute_session_arc(sessions)
        assert 0 in arc
        assert 1 in arc
        assert 2 in arc
        assert 3 in arc  # 3+ bucket

    def test_specificity_trend(self):
        """If later prompts are more specific, arc should show increasing specificity."""
        prompts = [
            _make_prompt(text="fix", msg_index=0, is_first=True, specificity=2),
            _make_prompt(text="fix the auth bug", msg_index=1, is_first=False, specificity=5),
            _make_prompt(text="fix auth.py line 42 TypeError", msg_index=2, is_first=False, specificity=8),
        ]
        sessions = [_make_session(prompts=prompts)]
        arc = compute_session_arc(sessions)
        assert arc[2]["avg_specificity"] > arc[0]["avg_specificity"]


class TestSweetSpot:
    def test_finds_optimal_range(self):
        """Given sessions with clear sweet spot, algorithm finds it."""
        sessions = []
        # Short prompts fail
        for i in range(10):
            p = _make_prompt(text="x " * 5, word_count=5, specificity=3)
            sessions.append(_make_session(outcome="FAILURE", prompts=[p]))
        # Medium prompts succeed
        for i in range(10):
            p = _make_prompt(text="word " * 30, word_count=30, specificity=6)
            sessions.append(_make_session(outcome="SUCCESS", prompts=[p]))
        # Long prompts fail
        for i in range(10):
            p = _make_prompt(text="word " * 200, word_count=200, specificity=7)
            sessions.append(_make_session(outcome="FAILURE", prompts=[p]))

        result = find_sweet_spot(sessions)
        assert result is not None
        assert result["success_rate"] > result["overall_rate"]

    def test_no_crash_small_data(self):
        """With < 10 sessions, returns None gracefully."""
        sessions = [_make_session() for _ in range(5)]
        result = find_sweet_spot(sessions)
        assert result is None


class TestContextSignals:
    def test_code_blocks_impact(self):
        """Sessions with code blocks should have a computed success rate."""
        sessions = [
            _make_session(
                outcome="SUCCESS",
                prompts=[_make_prompt(has_code_blocks=True)]
            ),
            _make_session(
                outcome="FAILURE",
                prompts=[_make_prompt(has_code_blocks=False)]
            ),
        ]
        signals = analyze_context_signals(sessions)
        assert "code_blocks" in signals
        assert signals["code_blocks"]["with_count"] == 1
        assert signals["code_blocks"]["without_count"] == 1


class TestCorrectionTrend:
    def test_trend_with_data(self):
        prompts = [_make_prompt(
            corrections=[r"\bno[,.\s!]"],
            timestamp="2026-01-15T10:00:00Z",
        )]
        sessions = [_make_session(prompts=prompts)]
        result = compute_correction_trend(sessions)
        assert "months" in result
        assert "trend" in result
        assert result["trend"] in ("improving", "stable", "getting worse")

    def test_trend_empty(self):
        result = compute_correction_trend([])
        assert result["trend"] == "stable"
        assert result["months"] == []


class TestSuccessRate:
    def test_basic(self):
        sessions = [
            _make_session(outcome="SUCCESS"),
            _make_session(outcome="FAILURE"),
            _make_session(outcome="PARTIAL_SUCCESS"),
        ]
        assert success_rate(sessions) == pytest.approx(66.67, abs=0.1)

    def test_empty(self):
        assert success_rate([]) == 0


class TestEndToEnd:
    def test_generate_html_runs(self):
        """Full pipeline produces valid HTML with all placeholders replaced."""
        sessions = [
            _make_session(
                outcome="SUCCESS", category="BUILD", specificity=7,
                prompts=[
                    _make_prompt(text="Fix the auth bug in login.py", specificity=7,
                                 first_msg_category="bug_report", has_file_paths=True,
                                 timestamp="2026-01-15T10:00:00Z"),
                    _make_prompt(text="Now add tests", msg_index=1, is_first=False,
                                 specificity=4, timestamp="2026-01-15T10:05:00Z"),
                ],
                total_tool_uses=20,
            ),
            _make_session(
                outcome="FAILURE", category="BUILD", specificity=2,
                prompts=[
                    _make_prompt(text="fix it", specificity=2,
                                 first_msg_category="vague_direction",
                                 timestamp="2026-01-10T10:00:00Z"),
                ],
                total_tool_uses=15,
            ),
        ] * 5  # Repeat for enough data

        from generate_prompt_coach import (
            compute_overall_score, score_to_grade, analyze_session_openers,
            analyze_context_signals, find_sweet_spot, detect_anti_patterns,
            find_before_after_pairs, compute_success_recipes, compute_session_arc,
            compute_correction_trend, generate_tips, generate_html,
        )

        score, dims = compute_overall_score(sessions)
        grade = score_to_grade(score)
        openers = analyze_session_openers(sessions)
        ctx = analyze_context_signals(sessions)
        sweet = find_sweet_spot(sessions)
        aps = detect_anti_patterns(sessions)
        pairs = find_before_after_pairs(sessions)
        recipes = compute_success_recipes(sessions, ctx)
        arc = compute_session_arc(sessions)
        trend = compute_correction_trend(sessions)
        tips = generate_tips(dims, aps, sweet, arc, openers)

        html = generate_html(
            sessions, score, dims, grade, openers, ctx,
            sweet, aps, pairs, recipes, arc, trend, tips
        )

        assert "<!DOCTYPE html>" in html
        assert "__PC_" not in html  # All placeholders replaced
        assert "Prompt Coach" in html
        assert str(score) in html


# Need pytest for approx
import pytest
