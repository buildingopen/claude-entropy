import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from generate_wrapped import (
    fmt_number, fmt_compact, hour_label, censor_word,
    compute_aggregates, compute_rules, compute_archetype, get_proj_dir_name,
    compute_percentile, compute_percentiles,
)


class TestFmtNumber:
    def test_small(self):
        assert fmt_number(42) == "42"

    def test_thousands(self):
        assert fmt_number(1234) == "1,234"

    def test_millions(self):
        assert fmt_number(1234567) == "1,234,567"


class TestFmtCompact:
    def test_small(self):
        assert fmt_compact(42) == "42"

    def test_thousands(self):
        assert fmt_compact(1500) == "2K"

    def test_millions(self):
        assert fmt_compact(1_500_000) == "1.5M"

    def test_billions(self):
        assert fmt_compact(11_300_000_000) == "11.3B"


class TestHourLabel:
    def test_midnight(self):
        assert hour_label(0) == "12am"

    def test_noon(self):
        assert hour_label(12) == "12pm"

    def test_morning(self):
        assert hour_label(9) == "9am"

    def test_evening(self):
        assert hour_label(18) == "6pm"


class TestCensorWord:
    def test_known(self):
        assert censor_word("fuck") == "f**k"
        assert censor_word("shit") == "sh*t"

    def test_unknown(self):
        assert censor_word("darn") == "darn"


class TestGetProjDirName:
    def test_standard_path(self):
        p = Path("/root/.claude/projects/my-project/session.jsonl")
        assert get_proj_dir_name(p) == "my-project"

    def test_no_projects_dir(self):
        p = Path("/tmp/session.jsonl")
        assert get_proj_dir_name(p) == "unknown"


class TestComputeAggregates:
    """Test compute_aggregates with minimal synthetic data."""

    def _make_data(self, **overrides):
        base = {
            "outcomes": [],
            "tones": [],
            "misuses": [],
            "scoring_instances": [],
            "error_sessions": [],
            "loop_findings": [],
            "project_sessions": [],
            "all_user_texts": [],
            "session_word_counts": {},
            "session_count": 0,
        }
        base.update(overrides)
        return base

    def test_empty_data(self):
        d = compute_aggregates(self._make_data())
        assert d["sessions"] == 0
        assert d["hours"] == 0
        assert d["loc"] == 0
        assert d["success_pct"] == 0
        assert d["total_errors"] == 0

    def test_session_count(self):
        d = compute_aggregates(self._make_data(session_count=42))
        assert d["sessions"] == 42

    def test_prompting_stats(self):
        texts = ["fix it", "yes", "do the thing please", "a longer prompt with more words in it"]
        d = compute_aggregates(self._make_data(all_user_texts=texts))
        assert d["median_words"] > 0
        assert 0 <= d["pct_short"] <= 100

    def test_outcome_success(self):
        outcomes = [
            {"outcome": "SUCCESS", "start": datetime(2026, 1, 1), "end": datetime(2026, 1, 2),
             "duration_min": 60, "loc_changed": 100, "commits": 1, "deployments": 0,
             "bash_commands": 5, "files_edited": 3, "total_tool_uses": 10, "error_rate": 0.1},
            {"outcome": "FAILURE", "start": datetime(2026, 1, 2), "end": datetime(2026, 1, 3),
             "duration_min": 30, "loc_changed": 0, "commits": 0, "deployments": 0,
             "bash_commands": 2, "files_edited": 0, "total_tool_uses": 5, "error_rate": 0.5},
        ]
        d = compute_aggregates(self._make_data(outcomes=outcomes, session_count=2))
        assert d["success_pct"] == 50
        assert d["loc"] == 100
        assert d["commits"] == 1

    def test_niceness_defaults_without_tones(self):
        d = compute_aggregates(self._make_data())
        assert d["niceness_score"] == 5.0
        assert d["user_swears_total"] == 0

    def test_tokens(self):
        sessions = [
            {"input_tokens": 1000, "output_tokens": 500, "cache_read_tokens": 200,
             "cache_creation_tokens": 100, "message_count": 10, "project_name": "Test",
             "model": "claude-sonnet-4-20250514"}
        ]
        d = compute_aggregates(self._make_data(project_sessions=sessions))
        assert d["total_tokens"] == 1800
        assert d["total_messages"] == 10


class TestComputeRules:
    def test_fallback_rules(self):
        d = {"median_words": 20, "pct_perfect": 0, "switch_rate": 50,
             "sessions": 10, "sessions_with_loops": 0, "misuse_total": 0,
             "short_prompt_errors": 0, "long_prompt_errors": 0, "error_ratio": "N/A"}
        rules = compute_rules(d)
        assert len(rules) == 3
        # Should be fallback rules
        assert "Run tests" in rules[0][0]

    def test_short_prompts_rule(self):
        d = {"median_words": 5, "pct_perfect": 0, "switch_rate": 50,
             "sessions": 10, "sessions_with_loops": 0, "misuse_total": 0,
             "short_prompt_errors": 0, "long_prompt_errors": 0, "error_ratio": "N/A"}
        rules = compute_rules(d)
        assert any("longer prompts" in r[0] for r in rules)

    def test_misuse_rule(self):
        d = {"median_words": 20, "pct_perfect": 0, "switch_rate": 50,
             "sessions": 10, "sessions_with_loops": 0, "misuse_total": 500,
             "short_prompt_errors": 0, "long_prompt_errors": 0, "error_ratio": "N/A"}
        rules = compute_rules(d)
        assert any("right tool" in r[0] for r in rules)

    def test_max_three_rules(self):
        d = {"median_words": 3, "pct_perfect": 50, "switch_rate": 2,
             "sessions": 100, "sessions_with_loops": 50, "misuse_total": 1000,
             "short_prompt_errors": 10, "long_prompt_errors": 5, "error_ratio": "2.0x"}
        rules = compute_rules(d)
        assert len(rules) == 3


class TestComputeArchetype:
    """Test archetype computation."""

    def _base_metrics(self, **overrides):
        base = {
            "sessions": 100, "session_categories": {"BUILD": 40, "FIX": 30, "EXPLORE": 20, "MIXED": 10},
            "success_pct": 70, "median_words": 15, "deployments": 10,
            "pct_perfect": 20, "sessions_with_loops": 10, "bugs_after_high": 3,
            "niceness_score": 5.0, "please_count": 50, "pct_short": 40,
            "retried_pct": 30, "switched_pct": 15, "gave_up_pct": 10,
        }
        base.update(overrides)
        return base

    def test_returns_tuple(self):
        d = self._base_metrics()
        result = compute_archetype(d)
        assert len(result) == 5
        key, name, line, share, stats_html = result
        assert key in ("firefighter", "architect", "speedrunner", "perfectionist", "whisperer", "commander")
        assert name.startswith("THE ")
        assert len(line) > 0
        assert len(share) > 0

    def test_firefighter(self):
        d = self._base_metrics(
            session_categories={"FIX": 60, "BUILD": 20, "EXPLORE": 10, "MIXED": 10},
            success_pct=30,
        )
        key, name, *_ = compute_archetype(d)
        assert key == "firefighter"
        assert name == "THE FIREFIGHTER"

    def test_architect(self):
        d = self._base_metrics(
            session_categories={"BUILD": 70, "FIX": 10, "EXPLORE": 10, "MIXED": 10},
            median_words=35, success_pct=85,
        )
        key, name, *_ = compute_archetype(d)
        assert key == "architect"

    def test_commander(self):
        d = self._base_metrics(
            median_words=3, niceness_score=2.0, pct_short=90,
            session_categories={"BUILD": 25, "FIX": 25, "EXPLORE": 25, "MIXED": 25},
        )
        key, name, *_ = compute_archetype(d)
        assert key == "commander"

    def test_whisperer(self):
        d = self._base_metrics(
            niceness_score=9.0, success_pct=85, please_count=200,
            session_categories={"BUILD": 25, "FIX": 25, "EXPLORE": 25, "MIXED": 25},
            median_words=15,
        )
        key, name, *_ = compute_archetype(d)
        assert key == "whisperer"

    def test_perfectionist(self):
        d = self._base_metrics(
            pct_perfect=60, sessions_with_loops=40,
            session_categories={"BUILD": 25, "FIX": 25, "EXPLORE": 25, "MIXED": 25},
            niceness_score=5.0, median_words=15, success_pct=50,
        )
        key, name, *_ = compute_archetype(d)
        assert key == "perfectionist"

    def test_stats_html_not_empty(self):
        d = self._base_metrics()
        _, _, _, _, stats_html = compute_archetype(d)
        assert "div" in stats_html

    def test_empty_data(self):
        d = {"sessions": 0, "session_categories": {}, "success_pct": 0,
             "median_words": 0, "deployments": 0, "pct_perfect": 0,
             "sessions_with_loops": 0, "niceness_score": 5.0, "please_count": 0,
             "pct_short": 0, "retried_pct": 0, "switched_pct": 0,
             "gave_up_pct": 0, "bugs_after_high": 0}
        result = compute_archetype(d)
        assert len(result) == 5


class TestNewAggregations:
    """Test that new aggregation fields are computed."""

    def _make_data(self, **overrides):
        base = {
            "outcomes": [], "tones": [], "misuses": [],
            "scoring_instances": [], "error_sessions": [],
            "loop_findings": [], "project_sessions": [],
            "all_user_texts": [], "session_word_counts": {},
            "session_count": 0,
        }
        base.update(overrides)
        return base

    def test_session_categories(self):
        outcomes = [
            {"outcome": "SUCCESS", "category": "BUILD",
             "start": datetime(2026, 1, 1), "end": datetime(2026, 1, 2),
             "duration_min": 60, "loc_changed": 100, "loc_added": 80, "loc_removed": 20,
             "commits": 2, "deployments": 1, "bash_commands": 5, "files_edited": 3,
             "total_tool_uses": 10, "error_rate": 0.1},
            {"outcome": "SUCCESS", "category": "FIX",
             "start": datetime(2026, 1, 2), "end": datetime(2026, 1, 3),
             "duration_min": 30, "loc_changed": 50, "loc_added": 30, "loc_removed": 20,
             "commits": 1, "deployments": 0, "bash_commands": 3, "files_edited": 2,
             "total_tool_uses": 8, "error_rate": 0.2},
        ]
        d = compute_aggregates(self._make_data(outcomes=outcomes, session_count=2))
        assert d["session_categories"]["BUILD"] == 1
        assert d["session_categories"]["FIX"] == 1
        assert d["loc_added"] == 110
        assert d["loc_removed"] == 40
        assert d["commits_per_deploy"] == 3  # 3 commits / 1 deploy

    def test_abandoned_count(self):
        outcomes = [
            {"outcome": "SUCCESS", "category": "BUILD", "abandoned": False,
             "start": datetime(2026, 1, 1), "end": datetime(2026, 1, 2),
             "duration_min": 60, "loc_changed": 100, "loc_added": 80, "loc_removed": 20,
             "commits": 1, "deployments": 0, "bash_commands": 5, "files_edited": 3,
             "total_tool_uses": 10, "error_rate": 0.1},
            {"outcome": "FAILURE", "category": "FIX", "abandoned": True,
             "start": datetime(2026, 1, 2), "end": datetime(2026, 1, 3),
             "duration_min": 30, "loc_changed": 10, "loc_added": 5, "loc_removed": 5,
             "commits": 0, "deployments": 0, "bash_commands": 2, "files_edited": 1,
             "total_tool_uses": 5, "error_rate": 0.5},
        ]
        d = compute_aggregates(self._make_data(outcomes=outcomes, session_count=2))
        assert d["abandoned_count"] == 1

    def test_error_action_pcts(self):
        """switched_pct, retried_pct, gave_up_pct are computed from error post-actions."""
        outcomes = [
            {"outcome": "SUCCESS", "start": datetime(2026, 1, 1), "end": datetime(2026, 1, 2),
             "duration_min": 60, "loc_changed": 100, "commits": 1, "deployments": 0,
             "bash_commands": 5, "files_edited": 3, "total_tool_uses": 10, "error_rate": 0.1},
        ]
        d = compute_aggregates(self._make_data(outcomes=outcomes, session_count=1))
        # With no error_sessions, all pcts default to 0
        assert d["switched_pct"] == 0
        assert d["retried_pct"] == 0
        assert d["gave_up_pct"] == 0

    def test_prompt_success_pcts_default(self):
        """short/long_prompt_success_pct default to 0 with no data."""
        outcomes = [
            {"outcome": "SUCCESS", "start": datetime(2026, 1, 1), "end": datetime(2026, 1, 2),
             "duration_min": 60, "loc_changed": 100, "commits": 1, "deployments": 0,
             "bash_commands": 5, "files_edited": 3, "total_tool_uses": 10, "error_rate": 0.1},
        ]
        d = compute_aggregates(self._make_data(outcomes=outcomes, session_count=1))
        assert d["short_prompt_success_pct"] == 0
        assert d["long_prompt_success_pct"] == 0

    def test_wasted_cost(self):
        outcomes = [
            {"outcome": "SUCCESS", "start": datetime(2026, 1, 1), "end": datetime(2026, 1, 2),
             "duration_min": 60, "loc_changed": 100, "commits": 1, "deployments": 0,
             "bash_commands": 5, "files_edited": 3, "total_tool_uses": 10, "error_rate": 0.1},
        ]
        sessions = [
            {"input_tokens": 500000, "output_tokens": 200000, "cache_read_tokens": 100000,
             "cache_creation_tokens": 50000, "message_count": 50, "project_name": "Test",
             "model": "claude-sonnet-4-20250514"}
        ]
        loops = [{"estimated_tokens": 50000, "session_slug": "s1", "tool": "Edit", "count": 5}]
        d = compute_aggregates(self._make_data(
            outcomes=outcomes, session_count=1,
            project_sessions=sessions, loop_findings=loops
        ))
        assert d["wasted_tokens"] == 50000
        # wasted_cost depends on total_cost being > 0
        assert "wasted_cost" in d


class TestComputePercentile:
    """Test percentile interpolation from benchmark tables."""

    def test_zero_value(self):
        assert compute_percentile(0, "sessions_monthly") == 0

    def test_below_p25(self):
        # 4 sessions/month: halfway to p25 threshold of 8
        p = compute_percentile(4, "sessions_monthly")
        assert 1 <= p <= 25

    def test_exact_p25(self):
        p = compute_percentile(8, "sessions_monthly")
        assert p == 25

    def test_exact_p50(self):
        p = compute_percentile(20, "sessions_monthly")
        assert p == 50

    def test_exact_p99(self):
        p = compute_percentile(400, "sessions_monthly")
        assert p == 99

    def test_above_p99(self):
        p = compute_percentile(1000, "sessions_monthly")
        assert p == 99

    def test_interpolation_midpoint(self):
        # Midpoint between p25=8 and p50=20 -> should be ~37
        p = compute_percentile(14, "sessions_monthly")
        assert 30 <= p <= 45

    def test_high_tokens(self):
        # 10B tokens: between p95=5B and p99=15B
        p = compute_percentile(10e9, "tokens")
        assert 95 <= p <= 99

    def test_success_pct(self):
        # 80% success: between p90=75 and p95=85
        p = compute_percentile(80, "success_pct")
        assert 90 <= p <= 95

    def test_all_benchmark_keys(self):
        """Every benchmark key works without error."""
        from generate_wrapped import BENCHMARKS
        for key in BENCHMARKS:
            p = compute_percentile(100, key)
            assert 0 <= p <= 99


class TestComputePercentiles:
    """Test the full percentiles computation from metrics dict."""

    def test_returns_all_keys(self):
        d = {
            "days": 30, "sessions": 100, "hours": 200, "loc": 10000,
            "total_tokens": 1e9, "total_cost": 500, "success_pct": 70,
            "deployments": 50,
        }
        pcts = compute_percentiles(d)
        assert "sessions" in pcts
        assert "hours" in pcts
        assert "loc" in pcts
        assert "tokens" in pcts
        assert "cost" in pcts
        assert "success" in pcts
        assert "deployments" in pcts
        assert "overall" in pcts

    def test_overall_is_weighted_average(self):
        d = {
            "days": 30, "sessions": 0, "hours": 0, "loc": 0,
            "total_tokens": 0, "total_cost": 0, "success_pct": 0,
            "deployments": 0,
        }
        pcts = compute_percentiles(d)
        assert pcts["overall"] == 0

    def test_high_usage(self):
        d = {
            "days": 30, "sessions": 300, "hours": 2000, "loc": 200000,
            "total_tokens": 10e9, "total_cost": 10000, "success_pct": 90,
            "deployments": 3000,
        }
        pcts = compute_percentiles(d)
        assert pcts["overall"] >= 90
        for key in ("sessions", "hours", "loc", "tokens"):
            assert pcts[key] >= 90

    def test_normalizes_to_monthly(self):
        # 60 days with 100 sessions = 50/month, which is p75
        d = {
            "days": 60, "sessions": 100, "hours": 0, "loc": 0,
            "total_tokens": 0, "total_cost": 0, "success_pct": 0,
            "deployments": 0,
        }
        pcts = compute_percentiles(d)
        assert pcts["sessions"] == 75
