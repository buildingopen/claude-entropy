#!/usr/bin/env python3
"""
Generate a self-contained prompt_coach.html report from Claude Code session data.

Analyzes per-prompt quality, correlates with session outcomes, detects anti-patterns,
and generates personalized coaching tips. Same architecture as generate_wrapped.py:
single-pass JSONL iteration, pattern analyzers, __PLACEHOLDER__ HTML template.

Outputs dist/prompt_coach.html.
"""

import json
import math
import os
import re
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

# Ensure patterns/ is importable
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from patterns.config import CLAUDE_PROJECTS_DIRS, resolve_project_name
from patterns.session_outcomes import analyze_session as analyze_outcome
from patterns.prompting_style import (
    extract_user_text,
    classify_first_message,
    analyze_prompt_specificity,
    detect_corrections,
    detect_frustration,
    strip_code_and_pasted_content,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
TEMPLATE_PATH = SCRIPT_DIR / "prompt_coach.html"
OUTPUT_DIR = SCRIPT_DIR / "dist"
OUTPUT_PATH = OUTPUT_DIR / "prompt_coach.html"

SANITIZE = os.environ.get("WRAPPED_SANITIZE", "") == "1"
AUTHOR_NAME = os.environ.get("WRAPPED_AUTHOR", "")


# ---------------------------------------------------------------------------
# Data Collection
# ---------------------------------------------------------------------------
def find_all_sessions():
    """Find all JSONL session files across all configured directories."""
    seen = set()
    sessions = []
    for projects_dir in CLAUDE_PROJECTS_DIRS:
        if not projects_dir.exists():
            continue
        for jsonl in projects_dir.rglob("*.jsonl"):
            if "subagent" in str(jsonl):
                continue
            try:
                resolved = jsonl.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                stat = jsonl.stat()
                if stat.st_size >= 10 * 1024:  # 10KB min
                    sessions.append(jsonl)
            except OSError:
                continue
    return sorted(sessions)


def get_proj_dir_name(filepath):
    """Extract project directory name from a session filepath."""
    parts = filepath.parts
    for i, p in enumerate(parts):
        if p == "projects" and i + 1 < len(parts):
            return parts[i + 1]
    return "unknown"


def build_prompt_record(text, msg_index, is_first, timestamp):
    """Build a per-prompt record with all metrics."""
    specificity = analyze_prompt_specificity(text)
    word_count = len(text.split())
    char_count = len(text)

    has_code_blocks = "```" in text
    has_file_paths = bool(re.search(r"[/~][\w.-]+/[\w.-]+", text))
    has_error_paste = bool(re.search(
        r"(Error:|TypeError:|SyntaxError:|ReferenceError:|stack trace|traceback|at \w+\.\w+ \(|ENOENT|EPERM|exit code [1-9])",
        text, re.IGNORECASE
    ))
    has_numbered_steps = bool(re.search(r"^\s*\d+[.)]\s", text, re.MULTILINE))
    has_bullet_points = bool(re.search(r"^\s*[-*]\s", text, re.MULTILINE))

    first_msg_category = classify_first_message(text) if is_first else None
    corrections = detect_corrections(text)
    frustration = detect_frustration(text)

    return {
        "msg_index": msg_index,
        "is_first_msg": is_first,
        "text": text,
        "word_count": word_count,
        "char_count": char_count,
        "specificity": specificity,
        "has_code_blocks": has_code_blocks,
        "has_file_paths": has_file_paths,
        "has_error_paste": has_error_paste,
        "has_numbered_steps": has_numbered_steps,
        "has_bullet_points": has_bullet_points,
        "first_msg_category": first_msg_category,
        "corrections": corrections,
        "frustration": frustration,
        "timestamp": timestamp,
    }


def collect_data():
    """Single pass over all sessions, collecting prompt and outcome data."""
    session_files = find_all_sessions()
    print(f"Found {len(session_files)} session files")

    session_records = []

    for i, filepath in enumerate(session_files):
        if (i + 1) % 100 == 0:
            print(f"  Processing {i + 1}/{len(session_files)}...")

        # Get session outcome
        try:
            outcome_data = analyze_outcome(filepath)
        except Exception:
            outcome_data = None

        if not outcome_data:
            continue

        # Parse JSONL for user messages
        prompts = []
        msg_idx = 0
        try:
            with open(filepath) as f:
                for line in f:
                    try:
                        obj = json.loads(line)
                    except (ValueError, json.JSONDecodeError):
                        continue
                    if obj.get("type") != "user":
                        continue
                    text = extract_user_text(obj)
                    if not text:
                        continue
                    # Skip synthetic markers
                    if text.startswith("[continuation") or text == "Implement the following plan":
                        msg_idx += 1
                        continue
                    if text.startswith("pls read [pasted"):
                        msg_idx += 1
                        continue

                    ts = obj.get("timestamp", "")
                    record = build_prompt_record(text, msg_idx, msg_idx == 0, ts)
                    prompts.append(record)
                    msg_idx += 1
        except Exception:
            continue

        if not prompts:
            continue

        proj_dir = get_proj_dir_name(filepath)
        project = resolve_project_name(proj_dir)

        correction_count = sum(1 for p in prompts if p["corrections"])

        session_records.append({
            "filepath": str(filepath),
            "project": project,
            "outcome": outcome_data["outcome"],
            "category": outcome_data["category"],
            "error_rate": outcome_data["error_rate"],
            "files_edited": outcome_data["files_edited"],
            "commits": outcome_data["commits"],
            "has_loop": outcome_data["has_loop"],
            "abandoned": outcome_data["abandoned"],
            "duration_min": outcome_data["duration_min"],
            "total_tool_uses": outcome_data["total_tool_uses"],
            "prompts": prompts,
            "correction_count": correction_count,
        })

    print(f"Collected {len(session_records)} sessions with prompts")
    return session_records


# ---------------------------------------------------------------------------
# Analysis Algorithms
# ---------------------------------------------------------------------------

def success_rate(sessions):
    """Compute success rate (% SUCCESS or PARTIAL_SUCCESS)."""
    if not sessions:
        return 0
    good = sum(1 for s in sessions if s["outcome"] in ("SUCCESS", "PARTIAL_SUCCESS"))
    return good / len(sessions) * 100


def compute_overall_score(sessions):
    """
    Compute overall prompt score 0-100 across 5 dimensions x 20 pts each.
    Returns (total, dimension_scores_dict).
    """
    all_prompts = [p for s in sessions for p in s["prompts"]]
    first_prompts = [s["prompts"][0] for s in sessions if s["prompts"]]

    if not all_prompts:
        return 0, {"specificity": 0, "context": 0, "first_message": 0, "clarity": 0, "lift": 0}

    # 1. Specificity (avg specificity scaled 0-10 -> 0-20)
    avg_spec = statistics.mean(p["specificity"] for p in all_prompts)
    specificity_score = min(20, avg_spec * 2)

    # 2. Context (% of prompts with context signals)
    context_count = sum(
        1 for p in all_prompts
        if p["has_code_blocks"] or p["has_file_paths"] or p["has_error_paste"]
    )
    context_pct = context_count / len(all_prompts)
    context_score = min(20, context_pct * 20)

    # 3. First Message quality
    if first_prompts:
        avg_first_spec = statistics.mean(p["specificity"] for p in first_prompts)
        good_categories = {"specific_instruction", "bug_report", "feature_request"}
        good_opener_pct = sum(
            1 for p in first_prompts if p.get("first_msg_category") in good_categories
        ) / len(first_prompts)
        first_msg_score = min(20, avg_first_spec * 1.2 + good_opener_pct * 8)
    else:
        first_msg_score = 0

    # 4. First-Attempt Clarity (% of sessions with zero corrections)
    if sessions:
        clear_sessions = sum(1 for s in sessions if s["correction_count"] == 0)
        clarity_pct = clear_sessions / len(sessions)
        clarity_score = min(20, clarity_pct * 20)
    else:
        clarity_score = 0

    # 5. Prompt-Outcome Lift
    high_spec = [s for s in sessions if s["prompts"] and s["prompts"][0]["specificity"] >= 7]
    low_spec = [s for s in sessions if s["prompts"] and s["prompts"][0]["specificity"] <= 3]

    if len(high_spec) >= 2 and len(low_spec) >= 2:
        high_rate = success_rate(high_spec)
        low_rate = success_rate(low_spec)
        lift = max(0, high_rate - low_rate)
        lift_score = min(20, lift * 0.5)
    else:
        # Median split fallback: divide sessions by median specificity
        specs_with_sessions = [(s["prompts"][0]["specificity"], s) for s in sessions if s["prompts"]]
        if len(specs_with_sessions) >= 4:
            median_spec = statistics.median(v for v, _ in specs_with_sessions)
            above = [s for v, s in specs_with_sessions if v >= median_spec]
            below = [s for v, s in specs_with_sessions if v < median_spec]
            if above and below:
                lift = max(0, success_rate(above) - success_rate(below))
                lift_score = min(20, lift * 0.5)
            else:
                overall_success = success_rate(sessions)
                lift_score = min(20, overall_success * 0.2)
        else:
            overall_success = success_rate(sessions)
            lift_score = min(20, overall_success * 0.2)

    dimensions = {
        "specificity": round(specificity_score, 1),
        "context": round(context_score, 1),
        "first_message": round(first_msg_score, 1),
        "clarity": round(clarity_score, 1),
        "lift": round(lift_score, 1),
    }

    total = sum(dimensions.values())
    return round(total), dimensions


def score_to_grade(score):
    """Map score 0-100 to letter grade."""
    if score >= 90:
        return "A+"
    if score >= 80:
        return "A"
    if score >= 70:
        return "B+"
    if score >= 60:
        return "B"
    if score >= 50:
        return "C+"
    if score >= 40:
        return "C"
    return "D"


def analyze_session_openers(sessions):
    """Group sessions by first_msg_category, compute success rate per category."""
    by_category = defaultdict(list)
    for s in sessions:
        if s["prompts"] and s["prompts"][0].get("first_msg_category"):
            cat = s["prompts"][0]["first_msg_category"]
            by_category[cat].append(s)

    results = {}
    for cat, cat_sessions in by_category.items():
        results[cat] = {
            "count": len(cat_sessions),
            "success_rate": round(success_rate(cat_sessions), 1),
            "example": _get_example_text(cat_sessions[0]["prompts"][0]) if cat_sessions else "",
        }
    return results


def _get_example_text(prompt, max_len=80):
    """Get display text from a prompt record, respecting sanitize mode."""
    if SANITIZE:
        return "[sanitized]"
    text = prompt["text"][:max_len].replace("\n", " ").strip()
    if len(prompt["text"]) > max_len:
        text += "..."
    return text


def analyze_context_signals(sessions):
    """For each context signal, compute success rate with vs without."""
    signals = {
        "code_blocks": "has_code_blocks",
        "file_paths": "has_file_paths",
        "error_paste": "has_error_paste",
        "numbered_steps": "has_numbered_steps",
    }

    results = {}
    for label, field in signals.items():
        with_signal = [s for s in sessions if s["prompts"] and s["prompts"][0].get(field)]
        without_signal = [s for s in sessions if s["prompts"] and not s["prompts"][0].get(field)]

        results[label] = {
            "with_count": len(with_signal),
            "without_count": len(without_signal),
            "with_success": round(success_rate(with_signal), 1),
            "without_success": round(success_rate(without_signal), 1),
            "delta": round(success_rate(with_signal) - success_rate(without_signal), 1),
        }
    return results


def find_sweet_spot(sessions):
    """Find the word count range with highest success rate using sliding window."""
    if len(sessions) < 10:
        return None

    # Sort by first prompt word count
    sorted_sessions = sorted(
        [s for s in sessions if s["prompts"]],
        key=lambda s: s["prompts"][0]["word_count"]
    )

    if not sorted_sessions:
        return None

    window_size = max(5, len(sorted_sessions) // 3)
    best_rate = 0
    best_range = None
    overall = success_rate(sorted_sessions)

    for i in range(len(sorted_sessions) - window_size + 1):
        window = sorted_sessions[i:i + window_size]
        rate = success_rate(window)
        if rate > best_rate:
            best_rate = rate
            low_wc = window[0]["prompts"][0]["word_count"]
            high_wc = window[-1]["prompts"][0]["word_count"]
            best_range = (low_wc, high_wc)

    if best_range and best_rate > overall:
        low, high = best_range
        # Cap range ratio at 5x; if wider, re-run with smaller window
        if low > 0 and high > low * 5:
            # Retry with smaller windows until ratio <= 5x
            min_window = max(20, len(sorted_sessions) // 10)  # at least 10% of data
            for divisor in [5, 7, 10]:
                smaller_window = max(min_window, len(sorted_sessions) // divisor)
                if smaller_window >= len(sorted_sessions):
                    continue
                retry_rate = 0
                retry_range = None
                for j in range(len(sorted_sessions) - smaller_window + 1):
                    w = sorted_sessions[j:j + smaller_window]
                    r = success_rate(w)
                    if r > retry_rate:
                        retry_rate = r
                        lo = w[0]["prompts"][0]["word_count"]
                        hi = w[-1]["prompts"][0]["word_count"]
                        retry_range = (lo, hi)
                if retry_range and retry_rate > overall:
                    lo, hi = retry_range
                    if lo > 0 and hi <= lo * 5:
                        low, high = lo, hi
                        best_rate = retry_rate
                        break
            # Final safety: if still too wide, use median-anchored range
            if low > 0 and high > low * 5:
                success_wcs = sorted([
                    s["prompts"][0]["word_count"] for s in sorted_sessions
                    if s["outcome"] in ("SUCCESS", "PARTIAL_SUCCESS") and s["prompts"]
                ])
                if len(success_wcs) >= 10:
                    med = success_wcs[len(success_wcs) // 2]
                    # Anchor to median: range is median/2 to median*2 (4x ratio max)
                    low = max(1, med // 2)
                    high = med * 2
        return {
            "low": low,
            "high": high,
            "success_rate": round(best_rate, 1),
            "overall_rate": round(overall, 1),
            "delta": round(best_rate - overall, 1),
        }
    return None


def detect_anti_patterns(sessions):
    """Detect 6 anti-patterns across all sessions."""
    patterns = {
        "vague_opener": {"count": 0, "examples": [], "tip": "Start with specific context: what file, what behavior, what you expect."},
        "no_context_code": {"count": 0, "examples": [], "tip": "Include a file path or paste the relevant code snippet."},
        "too_terse": {"count": 0, "examples": [], "tip": "Add a 'because' clause: what you want and why."},
        "error_without_context": {"count": 0, "examples": [], "tip": "Always paste the exact error message or stack trace."},
        "multi_task": {"count": 0, "examples": [], "tip": "Split into separate prompts, one task at a time."},
        "no_acceptance_criteria": {"count": 0, "examples": [], "tip": "Describe what 'done' looks like: expected behavior, output format."},
    }

    confirmations = {"yes", "no", "ok", "okay", "sure", "yep", "yeah", "nah", "y", "n"}

    for s in sessions:
        for p in s["prompts"]:
            text_lower = p["text"].lower().strip()
            words = text_lower.split()

            # vague_opener: first msg, specificity <= 3, word_count < 15
            if p["is_first_msg"] and p["specificity"] <= 3 and p["word_count"] < 15:
                patterns["vague_opener"]["count"] += 1
                if len(patterns["vague_opener"]["examples"]) < 3:
                    patterns["vague_opener"]["examples"].append(_get_example_text(p))

            # no_context_code: asks to fix/change but no code blocks or file paths
            if (re.search(r"\b(fix|change|update|modify|edit|refactor)\b", text_lower) and
                    not p["has_code_blocks"] and not p["has_file_paths"]):
                patterns["no_context_code"]["count"] += 1
                if len(patterns["no_context_code"]["examples"]) < 3:
                    patterns["no_context_code"]["examples"].append(_get_example_text(p))

            # too_terse: word_count <= 3, excluding confirmations
            if p["word_count"] <= 3:
                stripped = set(words) - confirmations
                if stripped:
                    patterns["too_terse"]["count"] += 1
                    if len(patterns["too_terse"]["examples"]) < 3:
                        patterns["too_terse"]["examples"].append(_get_example_text(p))

            # error_without_context: mentions error but no paste
            if (re.search(r"\b(error|broken|crash|fail|bug)\b", text_lower) and
                    not p["has_error_paste"] and not p["has_code_blocks"]):
                patterns["error_without_context"]["count"] += 1
                if len(patterns["error_without_context"]["examples"]) < 3:
                    patterns["error_without_context"]["examples"].append(_get_example_text(p))

            # multi_task: 50+ words with 3+ distinct action verbs
            if p["word_count"] >= 50:
                action_verbs = set(re.findall(
                    r"\b(add|fix|change|update|remove|delete|create|build|implement|refactor|move|rename|deploy|push|install|configure|set up|write|rewrite)\b",
                    text_lower
                ))
                if len(action_verbs) >= 3:
                    patterns["multi_task"]["count"] += 1
                    if len(patterns["multi_task"]["examples"]) < 3:
                        patterns["multi_task"]["examples"].append(_get_example_text(p))

            # no_acceptance_criteria: feature request with specificity < 5
            if (p["is_first_msg"] and p.get("first_msg_category") == "feature_request" and
                    p["specificity"] < 5):
                patterns["no_acceptance_criteria"]["count"] += 1
                if len(patterns["no_acceptance_criteria"]["examples"]) < 3:
                    patterns["no_acceptance_criteria"]["examples"].append(_get_example_text(p))

    # Compute success-with vs success-without for each pattern
    for pattern_name, data in patterns.items():
        with_sessions = []
        without_sessions = []
        for s in sessions:
            has_pattern = False
            for p in s["prompts"]:
                if _prompt_matches_pattern(p, pattern_name, confirmations):
                    has_pattern = True
                    break
            if has_pattern:
                with_sessions.append(s)
            else:
                without_sessions.append(s)
        data["with_success"] = round(success_rate(with_sessions), 1)
        data["without_success"] = round(success_rate(without_sessions), 1)
        data["impact"] = round(success_rate(without_sessions) - success_rate(with_sessions), 1)

    return patterns


def _prompt_matches_pattern(p, pattern_name, confirmations):
    """Check if a prompt matches a specific anti-pattern."""
    text_lower = p["text"].lower().strip()
    words = text_lower.split()

    if pattern_name == "vague_opener":
        return p["is_first_msg"] and p["specificity"] <= 3 and p["word_count"] < 15
    elif pattern_name == "no_context_code":
        return (re.search(r"\b(fix|change|update|modify|edit|refactor)\b", text_lower) and
                not p["has_code_blocks"] and not p["has_file_paths"])
    elif pattern_name == "too_terse":
        if p["word_count"] <= 3:
            stripped = set(words) - confirmations
            return bool(stripped)
        return False
    elif pattern_name == "error_without_context":
        return (re.search(r"\b(error|broken|crash|fail|bug)\b", text_lower) and
                not p["has_error_paste"] and not p["has_code_blocks"])
    elif pattern_name == "multi_task":
        if p["word_count"] >= 50:
            action_verbs = set(re.findall(
                r"\b(add|fix|change|update|remove|delete|create|build|implement|refactor|move|rename|deploy|push|install|configure|set up|write|rewrite)\b",
                text_lower
            ))
            return len(action_verbs) >= 3
        return False
    elif pattern_name == "no_acceptance_criteria":
        return (p["is_first_msg"] and p.get("first_msg_category") == "feature_request" and
                p["specificity"] < 5)
    return False


def find_before_after_pairs(sessions, max_pairs=3):
    """Find matched before/after pairs: same category, similar complexity, different outcomes."""
    by_category = defaultdict(list)
    for s in sessions:
        by_category[s["category"]].append(s)

    pairs = []
    for cat, cat_sessions in by_category.items():
        bad = [s for s in cat_sessions
               if s["prompts"] and s["prompts"][0]["specificity"] <= 4 and
               s["prompts"][0]["word_count"] >= 5 and
               s["outcome"] in ("FAILURE", "PARTIAL_FAILURE")]
        good = [s for s in cat_sessions
                if s["prompts"] and s["prompts"][0]["specificity"] >= 6 and
                s["prompts"][0]["word_count"] >= 5 and
                s["outcome"] in ("SUCCESS", "PARTIAL_SUCCESS")]

        for b in bad:
            for g in good:
                b_tools = max(1, b["total_tool_uses"])
                g_tools = max(1, g["total_tool_uses"])
                complexity_ratio = max(b_tools, g_tools) / min(b_tools, g_tools)
                if complexity_ratio <= 2.0:
                    spec_delta = g["prompts"][0]["specificity"] - b["prompts"][0]["specificity"]
                    pairs.append({
                        "category": cat,
                        "before": {
                            "text": _get_example_text(b["prompts"][0], 150),
                            "specificity": b["prompts"][0]["specificity"],
                            "word_count": b["prompts"][0]["word_count"],
                            "outcome": b["outcome"],
                        },
                        "after": {
                            "text": _get_example_text(g["prompts"][0], 150),
                            "specificity": g["prompts"][0]["specificity"],
                            "word_count": g["prompts"][0]["word_count"],
                            "outcome": g["outcome"],
                        },
                        "spec_delta": spec_delta,
                        "complexity_ratio": round(complexity_ratio, 1),
                    })

    # Sort by specificity delta (bigger = more instructive)
    pairs.sort(key=lambda x: x["spec_delta"], reverse=True)

    # Dedup: ensure each "before" text is unique (avoid same prompt appearing in all pairs)
    seen_before = set()
    deduped = []
    for pair in pairs:
        key = pair["before"]["text"][:50]
        if key in seen_before:
            continue
        seen_before.add(key)
        deduped.append(pair)
        if len(deduped) >= max_pairs:
            break

    return deduped


def compute_success_recipes(sessions, context_signals):
    """Find combos of opener type + specificity + signals with highest success."""
    recipes = []
    overall = success_rate(sessions)

    # Recipe: category x specificity bucket
    for cat in ["specific_instruction", "bug_report", "feature_request"]:
        for spec_bucket, spec_min, spec_max in [("high", 7, 10), ("medium", 4, 6)]:
            matching = [
                s for s in sessions
                if s["prompts"] and
                s["prompts"][0].get("first_msg_category") == cat and
                spec_min <= s["prompts"][0]["specificity"] <= spec_max
            ]
            if len(matching) >= 3:
                rate = success_rate(matching)
                delta = rate - overall
                if delta > 5:
                    recipes.append({
                        "label": f"{cat.replace('_', ' ').title()} + {spec_bucket} specificity",
                        "count": len(matching),
                        "success_rate": round(rate, 1),
                        "delta": round(delta, 1),
                    })

    # Recipe: context signals
    for label, data in context_signals.items():
        if data["delta"] > 5 and data["with_count"] >= 3:
            recipes.append({
                "label": f"Include {label.replace('_', ' ')}",
                "count": data["with_count"],
                "success_rate": data["with_success"],
                "delta": data["delta"],
            })

    recipes.sort(key=lambda x: x["delta"], reverse=True)
    return recipes[:5]


def compute_session_arc(sessions):
    """Track how prompt quality changes from message 1 to N within sessions."""
    by_position = defaultdict(list)
    for s in sessions:
        for i, p in enumerate(s["prompts"]):
            bucket = min(i, 3)  # 0, 1, 2, 3+
            by_position[bucket].append(p)

    arc = {}
    for pos in sorted(by_position.keys()):
        prompts = by_position[pos]
        arc[pos] = {
            "avg_specificity": round(statistics.mean(p["specificity"] for p in prompts), 1),
            "avg_word_count": round(statistics.mean(p["word_count"] for p in prompts), 0),
            "context_pct": round(
                sum(1 for p in prompts if p["has_code_blocks"] or p["has_file_paths"])
                / len(prompts) * 100, 1
            ),
            "correction_pct": round(
                sum(1 for p in prompts if p["corrections"])
                / len(prompts) * 100, 1
            ),
            "count": len(prompts),
        }
    return arc


def compute_correction_trend(sessions):
    """Monthly buckets of correction rate, with trend direction."""
    monthly = defaultdict(lambda: {"corrections": 0, "total": 0})

    for s in sessions:
        for p in s["prompts"]:
            ts = p.get("timestamp", "")
            if not ts:
                continue
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                month_key = dt.strftime("%Y-%m")
            except (ValueError, TypeError):
                continue
            monthly[month_key]["total"] += 1
            if p["corrections"]:
                monthly[month_key]["corrections"] += 1

    if not monthly:
        return {"months": [], "trend": "stable"}

    sorted_months = sorted(monthly.keys())
    month_data = []
    for m in sorted_months:
        d = monthly[m]
        rate = d["corrections"] / d["total"] * 100 if d["total"] else 0
        month_data.append({"month": m, "rate": round(rate, 1), "total": d["total"]})

    # Determine trend (allow 2+ months)
    if len(month_data) >= 2:
        first_half = statistics.mean(d["rate"] for d in month_data[:len(month_data) // 2])
        second_half = statistics.mean(d["rate"] for d in month_data[len(month_data) // 2:])
        # Use both relative (2x / 0.5x) and absolute (+-3pp) thresholds
        if second_half < max(first_half * 0.5, first_half - 3):
            trend = "improving"
        elif second_half > max(first_half * 2, first_half + 3):
            trend = "getting worse"
        else:
            trend = "stable"
    else:
        trend = "stable"

    return {"months": month_data, "trend": trend}


def generate_tips(dimensions, anti_patterns, sweet_spot, arc, openers):
    """Generate 5 personalized tips based on analysis data."""
    tips = []

    # 1. Weakest dimension
    weakest = min(dimensions.items(), key=lambda x: x[1])
    dim_tips = {
        "specificity": "Be more specific in your prompts. Include file names, function names, and exact behavior you want.",
        "context": "Provide more context. Paste relevant code blocks, file paths, or error messages with every request.",
        "first_message": "Invest more in your opening message. Start sessions with a clear, specific instruction rather than a vague direction.",
        "clarity": "Write clearer initial prompts to avoid corrections. If you find yourself saying 'no, I meant...', the first prompt needs more detail.",
        "lift": "Your prompt quality doesn't correlate with success. Try being more deliberate: specific prompts for complex tasks, quick ones for simple tasks.",
    }
    # Show "neutral" instead of "0.0/20" when lift is zero
    source_score = "neutral" if weakest[0] == "lift" and weakest[1] == 0 else f"{weakest[1]}/20"
    tips.append({
        "source": f"weakest dimension: {weakest[0]} ({source_score})",
        "tip": dim_tips.get(weakest[0], "Focus on improving your weakest prompting dimension."),
    })

    # 2-3. Top anti-patterns by count
    sorted_patterns = sorted(anti_patterns.items(), key=lambda x: x[1]["count"], reverse=True)
    for name, data in sorted_patterns[:2]:
        if data["count"] > 0:
            tips.append({
                "source": f"anti-pattern: {name.replace('_', ' ')} ({data['count']}x)",
                "tip": data["tip"],
            })

    # 4. Sweet spot or session arc
    if sweet_spot and sweet_spot["delta"] > 5:
        tips.append({
            "source": f"sweet spot: {sweet_spot['low']}-{sweet_spot['high']} words (+{sweet_spot['delta']}% success)",
            "tip": f"Your prompts perform best at {sweet_spot['low']}-{sweet_spot['high']} words. Aim for this range, especially on first messages.",
        })
    elif arc and len(arc) >= 2:
        first_spec = arc.get(0, {}).get("avg_specificity", 0)
        later_spec = arc.get(2, arc.get(1, {})).get("avg_specificity", 0)
        if later_spec > first_spec + 1:
            tips.append({
                "source": f"session arc: specificity {first_spec} -> {later_spec}",
                "tip": f"You start sessions at {first_spec} specificity but reach {later_spec} by message 3. Front-load that detail to save correction rounds.",
            })
        else:
            tips.append({
                "source": "session arc: consistent quality",
                "tip": "Your prompt quality stays consistent throughout sessions. Keep it up.",
            })
    else:
        tips.append({
            "source": "general",
            "tip": "Include the expected output format or acceptance criteria in complex prompts.",
        })

    # 5. Best opener type
    if openers:
        best = max(openers.items(), key=lambda x: x[1]["success_rate"])
        tips.append({
            "source": f"best opener: {best[0]} ({best[1]['success_rate']}% success)",
            "tip": f"Your most successful opener type is '{best[0].replace('_', ' ')}'. Use this framing when possible.",
        })

    return tips[:5]


# ---------------------------------------------------------------------------
# Word count histogram data for Chart.js
# ---------------------------------------------------------------------------
def build_word_count_histogram(sessions, sweet_spot=None):
    """Build histogram data for word count distribution of first prompts."""
    word_counts = [s["prompts"][0]["word_count"] for s in sessions if s["prompts"]]
    if not word_counts:
        return {"labels": [], "data": [], "colors": []}

    # Build bins
    max_wc = min(max(word_counts), 500)
    bin_size = max(5, max_wc // 20)
    bins = list(range(0, max_wc + bin_size, bin_size))

    labels = []
    data = []
    colors = []

    for i in range(len(bins) - 1):
        lo, hi = bins[i], bins[i + 1]
        count = sum(1 for wc in word_counts if lo <= wc < hi)
        labels.append(f"{lo}-{hi}")
        data.append(count)

        # Highlight sweet spot range
        if sweet_spot and lo >= sweet_spot["low"] and hi <= sweet_spot["high"] + bin_size:
            colors.append("rgba(34, 197, 94, 0.8)")
        else:
            colors.append("rgba(161, 161, 170, 0.3)")

    return {"labels": labels, "data": data, "colors": colors}


# ---------------------------------------------------------------------------
# HTML Generation
# ---------------------------------------------------------------------------
def generate_html(sessions, score, dimensions, grade, openers, context_signals,
                  sweet_spot, anti_patterns, pairs, recipes, arc, correction_trend,
                  tips):
    """Read template, do placeholder replacements, return HTML string."""
    template = TEMPLATE_PATH.read_text()

    author = AUTHOR_NAME or "Claude Code User"
    total_prompts = sum(len(s["prompts"]) for s in sessions)
    total_sessions = len(sessions)

    # Date range
    all_timestamps = []
    for s in sessions:
        for p in s["prompts"]:
            ts = p.get("timestamp", "")
            if ts:
                try:
                    all_timestamps.append(datetime.fromisoformat(ts.replace("Z", "+00:00")))
                except (ValueError, TypeError):
                    pass

    if all_timestamps:
        start_date = min(all_timestamps).strftime("%b %d")
        end_date = max(all_timestamps).strftime("%b %d, %Y")
        date_range = f"{start_date} &ndash; {end_date}"
    else:
        date_range = "No data"

    # Radar chart data (5 dimensions, values 0-20)
    radar_labels = json.dumps(["Specificity", "Context", "First Message", "Clarity", "Outcome Lift"])
    # When lift is 0, use small non-zero value so radar shape isn't completely flat on that axis
    radar_lift = max(dimensions["lift"], 1) if dimensions["lift"] == 0 else dimensions["lift"]
    radar_values = json.dumps([
        dimensions["specificity"], dimensions["context"],
        dimensions["first_message"], dimensions["clarity"], radar_lift
    ])

    # Opener chart data (include percentage in label for display)
    opener_labels = []
    opener_success = []
    opener_counts = []
    for cat in ["specific_instruction", "bug_report", "feature_request", "question", "continuation", "vague_direction", "other"]:
        if cat in openers:
            opener_labels.append(cat.replace("_", " ").title())
            opener_success.append(openers[cat]["success_rate"])
            opener_counts.append(openers[cat]["count"])

    # Context signals data
    ctx_html = ""
    for label in ["code_blocks", "file_paths", "error_paste", "numbered_steps"]:
        if label in context_signals:
            d = context_signals[label]
            display_label = label.replace("_", " ").title()
            delta_class = "positive" if d["delta"] > 0 else "negative" if d["delta"] < 0 else "neutral"
            delta_sign = "+" if d["delta"] > 0 else ""
            ctx_html += f'''<div class="ctx-card">
  <div class="ctx-label">{display_label}</div>
  <div class="ctx-row"><span class="ctx-with">With: {d["with_success"]}%</span><span class="ctx-count">({d["with_count"]})</span></div>
  <div class="ctx-row"><span class="ctx-without">Without: {d["without_success"]}%</span><span class="ctx-count">({d["without_count"]})</span></div>
  <div class="ctx-delta {delta_class}">{delta_sign}{d["delta"]}%</div>
</div>\n'''

    # Sweet spot
    if sweet_spot:
        sweet_spot_text = f"{sweet_spot['low']}-{sweet_spot['high']} words"
        sweet_spot_rate = f"{sweet_spot['success_rate']}%"
        sweet_spot_delta = f"+{sweet_spot['delta']}%"
    else:
        sweet_spot_text = "Not enough data"
        sweet_spot_rate = "-"
        sweet_spot_delta = "-"

    # Word count histogram
    histogram = build_word_count_histogram(sessions, sweet_spot)

    # Session arc chart data
    arc_labels = json.dumps(["1st", "2nd", "3rd", "4th+"])
    arc_specificity = json.dumps([arc.get(i, {}).get("avg_specificity", 0) for i in range(4)])
    arc_word_count = json.dumps([arc.get(i, {}).get("avg_word_count", 0) for i in range(4)])
    arc_context_pct = json.dumps([arc.get(i, {}).get("context_pct", 0) for i in range(4)])

    # Session arc insight
    if arc and len(arc) >= 2:
        first_spec = arc.get(0, {}).get("avg_specificity", 0)
        later_spec = arc.get(min(2, max(arc.keys())), {}).get("avg_specificity", 0)
        if later_spec > first_spec + 1:
            arc_insight = f"Your first messages average {first_spec} specificity but by message 3 you reach {later_spec}. Front-loading that detail saves correction rounds."
        elif first_spec > later_spec + 1:
            arc_insight = f"Strong start ({first_spec}) but specificity drops to {later_spec} in later messages. Keep the detail up throughout."
        else:
            arc_insight = f"Consistent specificity (~{first_spec}) throughout sessions. Solid prompting discipline."
    else:
        arc_insight = "Not enough multi-message sessions to analyze."

    # Before/After pairs HTML
    pairs_html = ""
    category_labels = {
        "MIXED": "General Task",
        "BUILD": "Build Task",
        "FIX": "Bug Fix",
        "EXPLORE": "Exploration",
        "REFACTOR": "Refactor",
        "TEST": "Testing",
        "DEPLOY": "Deployment",
    }
    for pair in pairs:
        b = pair["before"]
        a = pair["after"]
        cat_label = category_labels.get(pair["category"], pair["category"].title())
        pairs_html += f'''<div class="ba-pair">
  <div class="ba-label">{cat_label}</div>
  <div class="ba-cards">
    <div class="ba-card ba-before">
      <div class="ba-header">Before</div>
      <div class="ba-text">{_html_escape(b["text"])}</div>
      <div class="ba-meta">Specificity: {b["specificity"]}/10 &middot; {b["word_count"]} words &middot; {b["outcome"]}</div>
    </div>
    <div class="ba-card ba-after">
      <div class="ba-header">After</div>
      <div class="ba-text">{_html_escape(a["text"])}</div>
      <div class="ba-meta">Specificity: {a["specificity"]}/10 &middot; {a["word_count"]} words &middot; {a["outcome"]}</div>
    </div>
  </div>
</div>\n'''

    if not pairs_html:
        pairs_html = '<div class="ba-empty">Not enough matched pairs found. Need sessions with similar complexity but different prompt quality.</div>'

    # Anti-patterns HTML
    ap_html = ""
    sorted_ap = sorted(anti_patterns.items(), key=lambda x: x[1]["count"], reverse=True)
    for name, data in sorted_ap:
        if data["count"] == 0:
            continue
        display_name = name.replace("_", " ").title()
        # Only show impact comparison when data supports the anti-pattern claim
        # (sessions without the pattern outperform sessions with it).
        # When impact <= 0, session-length confounding makes the numbers misleading.
        if data["impact"] > 0:
            impact_line = f'Sessions without this pattern: {data["without_success"]}% success vs {data["with_success"]}% with'
            impact_class = "positive"
        else:
            impact_line = f'Detected in {data["count"]} prompts across your sessions'
            impact_class = "neutral"
        ap_html += f'''<div class="ap-item">
  <div class="ap-header">
    <span class="ap-name">{display_name}</span>
    <span class="ap-count">{data["count"]}x</span>
  </div>
  <div class="ap-tip">{data["tip"]}</div>
  <div class="ap-impact {impact_class}">{impact_line}</div>
</div>\n'''

    if not ap_html:
        ap_html = '<div class="ap-empty">No significant anti-patterns detected. Clean prompting!</div>'

    # Recipes HTML
    recipes_html = ""
    for r in recipes:
        recipes_html += f'''<div class="recipe-card">
  <div class="recipe-label">{r["label"]}</div>
  <div class="recipe-rate">{r["success_rate"]}% success</div>
  <div class="recipe-delta">+{r["delta"]}% vs baseline</div>
  <div class="recipe-count">{r["count"]} sessions</div>
</div>\n'''

    if not recipes_html:
        recipes_html = '<div class="recipe-empty">Not enough data to find reliable recipes yet.</div>'

    # Correction trend
    trend_labels = json.dumps([d["month"] for d in correction_trend["months"]])
    trend_data = json.dumps([d["rate"] for d in correction_trend["months"]])
    trend_direction = correction_trend["trend"]
    trend_class = "positive" if trend_direction == "improving" else "negative" if trend_direction == "getting worse" else "neutral"

    # Tips HTML
    tips_html = ""
    for i, t in enumerate(tips, 1):
        tips_html += f'''<div class="tip-item">
  <div class="tip-number">{i}</div>
  <div class="tip-content">
    <div class="tip-text">{t["tip"]}</div>
    <div class="tip-source">Based on: {t["source"]}</div>
  </div>
</div>\n'''

    # Success rate for display
    overall_success = round(success_rate(sessions), 1)

    # Do all replacements
    replacements = {
        "__PC_AUTHOR__": _html_escape(author),
        "__PC_DATE_RANGE__": date_range,
        "__PC_SESSION_COUNT__": str(total_sessions),
        "__PC_PROMPT_COUNT__": str(total_prompts),
        "__PC_SCORE_TOTAL__": str(score),
        "__PC_GRADE__": grade,
        "__PC_RADAR_LABELS__": radar_labels,
        "__PC_RADAR_VALUES__": radar_values,
        "__PC_SPEC_SCORE__": str(dimensions["specificity"]),
        "__PC_CTX_SCORE__": str(dimensions["context"]),
        "__PC_FIRST_SCORE__": str(dimensions["first_message"]),
        "__PC_CLARITY_SCORE__": str(dimensions["clarity"]),
        "__PC_LIFT_SCORE__": str(dimensions["lift"]),
        "__PC_LIFT_STATUS__": "neutral" if dimensions["lift"] == 0 else "positive",
        "__PC_OPENER_LABELS__": json.dumps(opener_labels),
        "__PC_OPENER_SUCCESS__": json.dumps(opener_success),
        "__PC_OPENER_COUNTS__": json.dumps(opener_counts),
        "__PC_CONTEXT_CARDS__": ctx_html,
        "__PC_SWEET_SPOT_TEXT__": sweet_spot_text,
        "__PC_SWEET_SPOT_RATE__": sweet_spot_rate,
        "__PC_SWEET_SPOT_DELTA__": sweet_spot_delta,
        "__PC_HISTOGRAM_LABELS__": json.dumps(histogram["labels"]),
        "__PC_HISTOGRAM_DATA__": json.dumps(histogram["data"]),
        "__PC_HISTOGRAM_COLORS__": json.dumps(histogram["colors"]),
        "__PC_ARC_LABELS__": arc_labels,
        "__PC_ARC_SPECIFICITY__": arc_specificity,
        "__PC_ARC_WORD_COUNT__": arc_word_count,
        "__PC_ARC_CONTEXT__": arc_context_pct,
        "__PC_ARC_INSIGHT__": arc_insight,
        "__PC_PAIRS_HTML__": pairs_html,
        "__PC_ANTIPATTERNS_HTML__": ap_html,
        "__PC_RECIPES_HTML__": recipes_html,
        "__PC_TREND_LABELS__": trend_labels,
        "__PC_TREND_DATA__": trend_data,
        "__PC_TREND_DIRECTION__": trend_direction,
        "__PC_TREND_CLASS__": trend_class,
        "__PC_TIPS_HTML__": tips_html,
        "__PC_SUCCESS_RATE__": str(overall_success),
    }

    html = template
    for key, value in replacements.items():
        html = html.replace(key, str(value))

    return html


def _html_escape(text):
    """Basic HTML escaping."""
    return (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("Collecting session data...")
    sessions = collect_data()

    if not sessions:
        print("No session data found. Make sure you have Claude Code sessions in ~/.claude/projects/")
        sys.exit(1)

    print("Computing overall score...")
    score, dimensions = compute_overall_score(sessions)
    grade = score_to_grade(score)

    print("Analyzing session openers...")
    openers = analyze_session_openers(sessions)

    print("Analyzing context signals...")
    context_signals = analyze_context_signals(sessions)

    print("Finding sweet spot...")
    sweet_spot = find_sweet_spot(sessions)

    print("Detecting anti-patterns...")
    anti_patterns = detect_anti_patterns(sessions)

    print("Finding before/after pairs...")
    pairs = find_before_after_pairs(sessions)

    print("Computing success recipes...")
    recipes = compute_success_recipes(sessions, context_signals)

    print("Computing session arc...")
    arc = compute_session_arc(sessions)

    print("Computing correction trend...")
    correction_trend = compute_correction_trend(sessions)

    print("Generating tips...")
    tips = generate_tips(dimensions, anti_patterns, sweet_spot, arc, openers)

    print("Generating HTML...")
    html = generate_html(
        sessions, score, dimensions, grade, openers, context_signals,
        sweet_spot, anti_patterns, pairs, recipes, arc, correction_trend, tips
    )

    OUTPUT_DIR.mkdir(exist_ok=True)
    OUTPUT_PATH.write_text(html)
    print(f"Wrote {OUTPUT_PATH} ({len(html):,} bytes)")

    # Summary
    print(f"\nPrompt Coach Summary:")
    print(f"  Sessions: {len(sessions)}")
    print(f"  Total prompts: {sum(len(s['prompts']) for s in sessions)}")
    print(f"  Score: {score}/100 ({grade})")
    print(f"  Dimensions: {dimensions}")
    print(f"  Top anti-pattern: {sorted(anti_patterns.items(), key=lambda x: x[1]['count'], reverse=True)[0][0] if anti_patterns else 'none'}")
    print(f"  Correction trend: {correction_trend['trend']}")


if __name__ == "__main__":
    main()
