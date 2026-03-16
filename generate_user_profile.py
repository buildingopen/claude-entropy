#!/usr/bin/env python3
"""
Generate a self-contained user_profile.html report from Claude Code session data.

Analyzes personality dimensions, coding archetypes, communication style,
work rhythms, and behavioral quirks. Same architecture as generate_wrapped.py:
single-pass JSONL iteration, pattern analyzers, __UP_*__ HTML template.

Outputs dist/user_profile.html.
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

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from patterns.config import CLAUDE_PROJECTS_DIRS, resolve_project_name
from patterns.session_outcomes import analyze_session as analyze_outcome
from patterns.communication_tone import (
    analyze_session as analyze_tone,
    count_swears,
    SWEAR_WORDS,
)
from patterns.prompting_style import (
    extract_user_text,
    classify_first_message,
    analyze_prompt_specificity,
    detect_corrections,
    detect_frustration,
    strip_code_and_pasted_content,
    LANG_PATTERNS,
    STOPWORDS,
)
from patterns.error_taxonomy import process_session as process_errors, analyze_error_sequences
from patterns.project_stats import parse_session_fast

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
TEMPLATE_PATH = SCRIPT_DIR / "user_profile.html"
OUTPUT_DIR = SCRIPT_DIR / "dist"
OUTPUT_PATH = OUTPUT_DIR / "user_profile.html"

SANITIZE = os.environ.get("WRAPPED_SANITIZE", "") == "1"
AUTHOR_NAME = os.environ.get("WRAPPED_AUTHOR", "")
TZ_OFFSET = int(os.environ.get("WRAPPED_TZ_OFFSET", "0"))


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
                if stat.st_size >= 10 * 1024:
                    sessions.append(jsonl)
            except OSError:
                continue
    return sorted(sessions)


def get_proj_dir_name(filepath):
    parts = filepath.parts
    for i, p in enumerate(parts):
        if p == "projects" and i + 1 < len(parts):
            return parts[i + 1]
    return "unknown"


def collect_data():
    """Single pass over all sessions, collecting all data needed for user profile."""
    session_files = find_all_sessions()
    print(f"Found {len(session_files)} session files")

    sessions = []
    all_user_texts = []
    word_counter = Counter()
    bigram_counter = Counter()
    hour_counts = defaultdict(int)  # hour -> session count
    day_hour_counts = defaultdict(int)  # (weekday, hour) -> count
    monthly_data = defaultdict(lambda: {"niceness": [], "specificity": [], "success": []})

    for i, filepath in enumerate(session_files):
        if (i + 1) % 100 == 0:
            print(f"  Processing {i + 1}/{len(session_files)}...")

        # Outcome analysis
        try:
            outcome_data = analyze_outcome(filepath)
        except Exception:
            outcome_data = None
        if not outcome_data:
            continue

        # Tone analysis
        try:
            tone_data = analyze_tone(filepath)
        except Exception:
            tone_data = None

        # Error analysis
        try:
            error_data = process_errors(filepath)
            error_sequences = analyze_error_sequences(error_data)
        except Exception:
            error_sequences = []

        # Project stats (tokens, etc.)
        proj_dir = get_proj_dir_name(filepath)
        try:
            proj_data = parse_session_fast(filepath, proj_dir)
        except Exception:
            proj_data = None

        # Parse JSONL for user messages + timestamps
        prompts = []
        timestamps = []
        msg_idx = 0
        try:
            with open(filepath) as f:
                for line in f:
                    try:
                        obj = json.loads(line)
                    except (ValueError, json.JSONDecodeError):
                        continue

                    ts = obj.get("timestamp", "")
                    if ts:
                        try:
                            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                            timestamps.append(dt)
                        except (ValueError, TypeError):
                            pass

                    if obj.get("type") != "user":
                        continue
                    text = extract_user_text(obj)
                    if not text:
                        continue
                    if text.startswith("[continuation") or text == "Implement the following plan":
                        msg_idx += 1
                        continue
                    if text.startswith("pls read [pasted"):
                        msg_idx += 1
                        continue

                    specificity = analyze_prompt_specificity(text)
                    corrections = detect_corrections(text)
                    frustration = detect_frustration(text)

                    prompts.append({
                        "text": text,
                        "word_count": len(text.split()),
                        "specificity": specificity,
                        "corrections": corrections,
                        "frustration": frustration,
                        "is_first": msg_idx == 0,
                        "first_msg_category": classify_first_message(text) if msg_idx == 0 else None,
                        "timestamp": ts,
                    })
                    all_user_texts.append(text)

                    # Word / bigram counting (stripped of code)
                    clean = strip_code_and_pasted_content(text).lower()
                    words = [w for w in re.findall(r"\b[a-z]{2,}\b", clean) if w not in STOPWORDS]
                    word_counter.update(words)
                    for j in range(len(words) - 1):
                        bigram_counter[(words[j], words[j + 1])] += 1

                    msg_idx += 1
        except Exception:
            continue

        if not prompts:
            continue

        # Track timing
        if timestamps:
            start = min(timestamps)
            local_hour = (start.hour + TZ_OFFSET) % 24
            hour_counts[local_hour] += 1
            day_hour_counts[(start.weekday(), local_hour)] += 1

            month_key = start.strftime("%Y-%m")
            is_success = outcome_data["outcome"] in ("SUCCESS", "PARTIAL_SUCCESS")
            monthly_data[month_key]["success"].append(1 if is_success else 0)
            if tone_data:
                monthly_data[month_key]["niceness"].append(tone_data["niceness_score"])
            avg_spec = statistics.mean(p["specificity"] for p in prompts)
            monthly_data[month_key]["specificity"].append(avg_spec)

        project = resolve_project_name(proj_dir)
        correction_count = sum(1 for p in prompts if p["corrections"])
        frustration_count = sum(1 for p in prompts if p["frustration"])

        session_record = {
            "filepath": str(filepath),
            "project": project,
            "outcome": outcome_data["outcome"],
            "category": outcome_data["category"],
            "error_rate": outcome_data["error_rate"],
            "files_edited": outcome_data["files_edited"],
            "commits": outcome_data["commits"],
            "deployments": outcome_data.get("deployments", 0),
            "has_loop": outcome_data["has_loop"],
            "abandoned": outcome_data["abandoned"],
            "duration_min": min(outcome_data["duration_min"], 480),
            "total_tool_uses": outcome_data["total_tool_uses"],
            "prompts": prompts,
            "correction_count": correction_count,
            "frustration_count": frustration_count,
            "timestamps": timestamps,
            "tone": tone_data,
            "error_sequences": error_sequences,
            "proj_data": proj_data,
        }
        sessions.append(session_record)

    print(f"Collected {len(sessions)} sessions with prompts")
    return {
        "sessions": sessions,
        "all_user_texts": all_user_texts,
        "word_counter": word_counter,
        "bigram_counter": bigram_counter,
        "hour_counts": hour_counts,
        "day_hour_counts": day_hour_counts,
        "monthly_data": monthly_data,
    }


# ---------------------------------------------------------------------------
# 7 Personality Dimensions
# ---------------------------------------------------------------------------
def compute_dimensions(data):
    """Compute 7 personality dimensions (0-100 each)."""
    sessions = data["sessions"]
    if not sessions:
        return {d: 50 for d in ["patience", "precision", "warmth", "ambition", "persistence", "autonomy", "night_owl"]}

    # --- Patience ---
    durations = [s["duration_min"] for s in sessions if s["duration_min"] > 0]
    median_duration = statistics.median(durations) if durations else 15
    abandoned_pct = sum(1 for s in sessions if s["abandoned"]) / len(sessions) * 100
    frustration_per_session = sum(s["frustration_count"] for s in sessions) / len(sessions)
    gave_up = sum(1 for s in sessions for e in s["error_sequences"] if e.get("post_action") == "gave_up")
    switched = sum(1 for s in sessions for e in s["error_sequences"] if e.get("post_action") == "switched_approach")

    patience = 50
    if median_duration > 30:
        patience += 15
    elif median_duration > 20:
        patience += 8
    if abandoned_pct < 10:
        patience += 10
    elif abandoned_pct < 20:
        patience += 5
    if frustration_per_session < 0.5:
        patience += 10
    elif frustration_per_session < 1:
        patience += 5
    if switched > gave_up and (switched + gave_up) > 0:
        patience += 10
    if median_duration < 10:
        patience -= 15
    elif median_duration < 15:
        patience -= 8
    if abandoned_pct > 30:
        patience -= 15
    elif abandoned_pct > 20:
        patience -= 8
    if frustration_per_session > 2:
        patience -= 10
    elif frustration_per_session > 1.5:
        patience -= 5

    # --- Precision ---
    all_specs = [p["specificity"] for s in sessions for p in s["prompts"]]
    avg_spec = statistics.mean(all_specs) if all_specs else 5
    avg_error_rate = statistics.mean(s["error_rate"] for s in sessions)
    correction_rate = sum(s["correction_count"] for s in sessions) / max(sum(len(s["prompts"]) for s in sessions), 1) * 100

    precision = 50
    if avg_spec > 7:
        precision += 15
    elif avg_spec > 6:
        precision += 8
    if avg_error_rate < 3:
        precision += 10
    elif avg_error_rate < 5:
        precision += 5
    if correction_rate < 5:
        precision += 10
    elif correction_rate < 10:
        precision += 5
    if avg_spec < 4:
        precision -= 15
    elif avg_spec < 5:
        precision -= 8
    if avg_error_rate > 10:
        precision -= 10
    elif avg_error_rate > 7:
        precision -= 5
    if correction_rate > 20:
        precision -= 10
    elif correction_rate > 15:
        precision -= 5

    # --- Warmth ---
    niceness_scores = [s["tone"]["niceness_score"] for s in sessions if s["tone"]]
    avg_niceness = statistics.mean(niceness_scores) if niceness_scores else 5
    warmth = max(0, min(100, avg_niceness * 10))

    # --- Ambition ---
    build_count = sum(1 for s in sessions if s["category"] == "BUILD")
    fix_count = sum(1 for s in sessions if s["category"] == "FIX")
    deploy_count = sum(s["deployments"] for s in sessions)
    unique_projects = len(set(s["project"] for s in sessions))
    total = len(sessions)

    build_ratio = build_count / total if total else 0
    feature_vs_bug = build_count / max(fix_count, 1)

    ambition = 50
    if build_ratio > 0.5:
        ambition += 15
    elif build_ratio > 0.35:
        ambition += 8
    if unique_projects > 5:
        ambition += 10
    elif unique_projects > 3:
        ambition += 5
    if deploy_count > total * 0.1:
        ambition += 10
    elif deploy_count > 0:
        ambition += 5
    if feature_vs_bug > 2:
        ambition += 5
    if build_ratio < 0.2:
        ambition -= 15
    elif build_ratio < 0.3:
        ambition -= 8
    if unique_projects <= 1:
        ambition -= 10
    if deploy_count == 0:
        ambition -= 5

    # --- Persistence ---
    total_errors = sum(len(s["error_sequences"]) for s in sessions)
    if total_errors > 0:
        gave_up_pct = gave_up / total_errors * 100
        switched_pct = switched / total_errors * 100
    else:
        gave_up_pct = 0
        switched_pct = 0
    loop_sessions = sum(1 for s in sessions if s["has_loop"])
    loop_pct = loop_sessions / total * 100 if total else 0

    persistence = 50
    if abandoned_pct < 10:
        persistence += 15
    elif abandoned_pct < 20:
        persistence += 8
    if switched_pct > gave_up_pct and total_errors > 5:
        persistence += 10
    if loop_pct < 5:
        persistence += 5
    if abandoned_pct > 30:
        persistence -= 15
    elif abandoned_pct > 20:
        persistence -= 8
    if gave_up_pct > 50 and total_errors > 5:
        persistence -= 15
    elif gave_up_pct > 30 and total_errors > 5:
        persistence -= 8

    # --- Autonomy ---
    prompts_per_session = sum(len(s["prompts"]) for s in sessions) / total if total else 0
    correction_per_session = sum(s["correction_count"] for s in sessions) / total if total else 0
    first_msg_ratios = []
    for s in sessions:
        if len(s["prompts"]) > 0:
            first_wc = s["prompts"][0]["word_count"]
            total_wc = sum(p["word_count"] for p in s["prompts"])
            if total_wc > 0:
                first_msg_ratios.append(first_wc / total_wc)
    avg_first_ratio = statistics.mean(first_msg_ratios) if first_msg_ratios else 0.5

    autonomy = 50
    if prompts_per_session < 5:
        autonomy += 15
    elif prompts_per_session < 8:
        autonomy += 8
    if correction_per_session < 0.5:
        autonomy += 10
    elif correction_per_session < 1:
        autonomy += 5
    if avg_first_ratio > 0.6:
        autonomy += 10
    if prompts_per_session > 15:
        autonomy -= 15
    elif prompts_per_session > 10:
        autonomy -= 8
    if correction_per_session > 2:
        autonomy -= 10
    elif correction_per_session > 1.5:
        autonomy -= 5

    # --- Night Owl ---
    hour_counts = data["hour_counts"]
    if hour_counts:
        total_sessions_timed = sum(hour_counts.values())
        # Weighted average: night hours (22-5) push toward 100, morning (6-11) toward 0
        night_weight = sum(hour_counts.get(h, 0) for h in [22, 23, 0, 1, 2, 3, 4, 5])
        morning_weight = sum(hour_counts.get(h, 0) for h in [6, 7, 8, 9, 10, 11])
        if total_sessions_timed > 0:
            night_pct = night_weight / total_sessions_timed * 100
            morning_pct = morning_weight / total_sessions_timed * 100
            night_owl = 50 + (night_pct - morning_pct) * 0.8
        else:
            night_owl = 50
    else:
        night_owl = 50

    return {
        "patience": max(0, min(100, round(patience))),
        "precision": max(0, min(100, round(precision))),
        "warmth": max(0, min(100, round(warmth))),
        "ambition": max(0, min(100, round(ambition))),
        "persistence": max(0, min(100, round(persistence))),
        "autonomy": max(0, min(100, round(autonomy))),
        "night_owl": max(0, min(100, round(night_owl))),
    }


def dimension_label(dimension, value):
    """Get descriptive label for a dimension value."""
    labels = {
        "patience": [(30, "Impatient Sprinter"), (60, "Measured Pacer"), (100, "Zen Master")],
        "precision": [(30, "Chaotic Tinkerer"), (60, "Pragmatic Coder"), (100, "Surgical")],
        "warmth": [(30, "Ice Cold"), (60, "Professional"), (100, "Sunshine")],
        "ambition": [(30, "Maintainer"), (60, "Steady Builder"), (100, "Empire Builder")],
        "persistence": [(30, "Quick Quitter"), (60, "Resilient"), (100, "Unstoppable")],
        "autonomy": [(30, "Micromanager"), (60, "Collaborative"), (100, "Full Delegator")],
        "night_owl": [(30, "Early Bird"), (60, "Flexible Hours"), (100, "Night Owl")],
    }
    for threshold, label in labels.get(dimension, []):
        if value <= threshold:
            return label
    return "Unknown"


# ---------------------------------------------------------------------------
# 12 Archetypes
# ---------------------------------------------------------------------------
ARCHETYPES = {
    "The Architect": {
        "tagline": "You design before you build",
        "description": "Methodical, precise, and patient. You plan carefully and execute with surgical accuracy. Your code is clean because your thinking is clear.",
        "weights": {"precision": 1.5, "patience": 1.2, "ambition": 1.0},
    },
    "The Speedrunner": {
        "tagline": "Ship it yesterday",
        "description": "Fast, autonomous, and ambitious. You value velocity over perfection and trust Claude to fill in the gaps. Your sessions are short, sharp, and productive.",
        "weights": {"patience": -1.5, "ambition": 1.2, "autonomy": 1.0},
    },
    "The Perfectionist": {
        "tagline": "Not done until it's flawless",
        "description": "Precise, persistent, and hands-on. You review every detail, correct every mistake, and won't ship until it's right.",
        "weights": {"precision": 1.5, "persistence": 1.2, "autonomy": -1.0},
    },
    "The Whisperer": {
        "tagline": "Soft-spoken, sharp results",
        "description": "Warm, patient, and precise. You guide Claude with kindness and clarity, getting excellent results through encouragement rather than commands.",
        "weights": {"warmth": 1.5, "patience": 1.2, "precision": 1.0},
    },
    "The Commander": {
        "tagline": "Direct orders, no small talk",
        "description": "Efficient, autonomous, and ambitious. You give clear orders and expect them executed. No pleasantries, no wasted tokens.",
        "weights": {"warmth": -1.5, "ambition": 1.2, "autonomy": 1.0},
    },
    "The Firefighter": {
        "tagline": "Always putting out fires",
        "description": "Persistent and battle-tested. You spend most of your time fixing bugs and recovering from errors. You never give up, even when the codebase fights back.",
        "weights": {"persistence": 1.5, "ambition": -1.0, "patience": 0.8},
    },
    "The Night Wizard": {
        "tagline": "Dark hours, bright code",
        "description": "A nocturnal coder with ambition and persistence. Your best work happens when the world sleeps.",
        "weights": {"night_owl": 1.5, "persistence": 1.0, "ambition": 1.0},
    },
    "The Diplomat": {
        "tagline": "Collaborative to the core",
        "description": "Warm, patient, and collaborative. You treat Claude as a partner, not a tool. Every interaction is a conversation.",
        "weights": {"warmth": 1.5, "patience": 1.0, "autonomy": -1.0},
    },
    "The Tinkerer": {
        "tagline": "Move fast, fix later",
        "description": "Ambitious and persistent, but rough around the edges. You prototype rapidly and iterate toward quality.",
        "weights": {"precision": -1.0, "ambition": 1.2, "persistence": 1.0},
    },
    "The Strategist": {
        "tagline": "Minimum moves, maximum impact",
        "description": "Precise, autonomous, and patient. You think before you act and make every prompt count. Efficiency is your art form.",
        "weights": {"precision": 1.2, "autonomy": 1.2, "patience": 1.0},
    },
    "The Maverick": {
        "tagline": "Chaos with a vision",
        "description": "Impatient and ambitious with a loose grip on precision. You move fast, break things, and somehow it all works out.",
        "weights": {"patience": -1.0, "precision": -1.0, "ambition": 1.5},
    },
    "The Guardian": {
        "tagline": "Steady hands, stable systems",
        "description": "Patient, persistent, and methodical. You maintain and protect rather than chase new features. Reliability is your superpower.",
        "weights": {"patience": 1.2, "persistence": 1.2, "ambition": -1.0},
    },
}


def select_archetype(dimensions):
    """Score each archetype against dimensions, pick highest."""
    best_name = "The Architect"
    best_score = -999

    for name, arch in ARCHETYPES.items():
        score = 0
        for dim, weight in arch["weights"].items():
            val = dimensions.get(dim, 50)
            if weight > 0:
                score += weight * (val - 50) / 50
            else:
                score += abs(weight) * (50 - val) / 50
        if score > best_score:
            best_score = score
            best_name = name

    return best_name


# ---------------------------------------------------------------------------
# Section Analysis Functions
# ---------------------------------------------------------------------------
def analyze_communication_style(data):
    """Section 4: Communication style analysis."""
    word_counter = data["word_counter"]
    bigram_counter = data["bigram_counter"]
    sessions = data["sessions"]
    all_texts = data["all_user_texts"]

    # Top words
    top_words = [w for w, _ in word_counter.most_common(20)]

    # Top bigrams
    top_bigrams = [f"{a} {b}" for (a, b), _ in bigram_counter.most_common(10)]

    # Vocab richness (Guiraud's index)
    total_words = sum(word_counter.values())
    unique_words = len(word_counter)
    guiraud = unique_words / math.sqrt(total_words) if total_words > 0 else 0

    # Avg words per prompt
    all_wc = [p["word_count"] for s in sessions for p in s["prompts"]]
    avg_wpm = statistics.mean(all_wc) if all_wc else 0

    # Question percentage
    question_count = sum(1 for t in all_texts if t.strip().endswith("?"))
    question_pct = question_count / max(len(all_texts), 1) * 100

    # Style label
    if avg_wpm < 10:
        style = "Telegraphic"
    elif avg_wpm < 25:
        style = "Directive"
    elif avg_wpm < 50:
        style = "Conversational"
    elif avg_wpm < 100:
        style = "Detailed"
    else:
        style = "Specification Writer"

    # Language detection
    lang_counts = Counter()
    for text in all_texts[:500]:  # sample
        text_lower = text.lower()
        for lang, patterns in LANG_PATTERNS.items():
            for pat in patterns:
                if re.search(pat, text_lower):
                    lang_counts[lang] += 1
                    break

    languages = [lang for lang, cnt in lang_counts.most_common(3) if cnt > 5]

    return {
        "top_words": top_words,
        "top_bigrams": top_bigrams,
        "guiraud": round(guiraud, 1),
        "avg_wpm": round(avg_wpm, 1),
        "question_pct": round(question_pct, 1),
        "style": style,
        "languages": languages,
    }


def analyze_emotional_timeline(data):
    """Section 5: Nice vs harsh by hour."""
    sessions = data["sessions"]
    nice_by_hour = defaultdict(int)
    harsh_by_hour = defaultdict(int)

    for s in sessions:
        if not s["tone"]:
            continue
        for h, c in s["tone"].get("nice_by_hour", {}).items():
            local_h = (int(h) + TZ_OFFSET) % 24
            nice_by_hour[local_h] += c
        for h, c in s["tone"].get("swears_by_hour", {}).items():
            local_h = (int(h) + TZ_OFFSET) % 24
            harsh_by_hour[local_h] += c

    nice_arr = [nice_by_hour.get(h, 0) for h in range(24)]
    harsh_arr = [harsh_by_hour.get(h, 0) for h in range(24)]

    calmest = min(range(24), key=lambda h: harsh_by_hour.get(h, 0)) if harsh_by_hour else 10
    stormiest = max(range(24), key=lambda h: harsh_by_hour.get(h, 0)) if harsh_by_hour else 15

    return {
        "nice_arr": nice_arr,
        "harsh_arr": harsh_arr,
        "calmest_hour": calmest,
        "stormiest_hour": stormiest,
    }


def analyze_work_rhythm(data):
    """Section 6: Heatmap + rhythm label."""
    day_hour = data["day_hour_counts"]
    sessions = data["sessions"]

    # Build 7x24 grid
    grid = [[0] * 24 for _ in range(7)]
    for (day, hour), count in day_hour.items():
        grid[day][hour] += count

    # Peak hours (top 3)
    hour_totals = defaultdict(int)
    for (_, hour), count in day_hour.items():
        hour_totals[hour] += count
    peak_hours = sorted(hour_totals, key=hour_totals.get, reverse=True)[:3]

    # Weekend percentage
    weekend_sessions = sum(1 for s in sessions if s["timestamps"] and min(s["timestamps"]).weekday() >= 5)
    weekend_pct = weekend_sessions / max(len(sessions), 1) * 100

    # Avg duration
    durations = [s["duration_min"] for s in sessions if s["duration_min"] > 0]
    avg_duration = statistics.mean(durations) if durations else 0

    # Rhythm label
    night_sessions = sum(hour_totals.get(h, 0) for h in [22, 23, 0, 1, 2, 3, 4, 5])
    morning_sessions = sum(hour_totals.get(h, 0) for h in [6, 7, 8, 9, 10, 11])
    total_timed = sum(hour_totals.values())

    if total_timed == 0:
        rhythm = "Unknown"
    elif weekend_pct > 40:
        rhythm = "Weekend Warrior"
    elif night_sessions / max(total_timed, 1) > 0.4:
        rhythm = "Night Owl"
    elif morning_sessions / max(total_timed, 1) > 0.4:
        rhythm = "9-to-5er"
    else:
        rhythm = "Always On"

    return {
        "grid": grid,
        "peak_hours": peak_hours,
        "weekend_pct": round(weekend_pct, 1),
        "avg_duration": round(avg_duration, 1),
        "rhythm": rhythm,
    }


def analyze_project_loyalty(data):
    """Section 7: Project distribution."""
    sessions = data["sessions"]
    project_counts = Counter(s["project"] for s in sessions)
    total = len(sessions)

    top_project = project_counts.most_common(1)[0] if project_counts else ("Unknown", 0)
    top_pct = top_project[1] / total * 100 if total else 0

    if top_pct > 70:
        loyalty_label = "Monogamous"
    elif top_pct > 50:
        loyalty_label = "Committed"
    elif top_pct > 30:
        loyalty_label = "Dating Around"
    else:
        loyalty_label = "Polyamorous"

    # Switch rate: consecutive sessions with different projects
    switches = 0
    for i in range(1, len(sessions)):
        if sessions[i]["project"] != sessions[i - 1]["project"]:
            switches += 1
    switch_rate = switches / max(len(sessions) - 1, 1) * 100

    return {
        "project_counts": dict(project_counts.most_common(8)),
        "loyalty_label": loyalty_label,
        "loyalty_score": round(top_pct, 1),
        "switch_rate": round(switch_rate, 1),
    }


def analyze_builder_identity(data):
    """Section 8: BUILD vs FIX vs EXPLORE."""
    sessions = data["sessions"]
    cat_counts = Counter(s["category"] for s in sessions)
    total = len(sessions)

    build_n = cat_counts.get("BUILD", 0)
    fix_n = cat_counts.get("FIX", 0)
    explore_n = cat_counts.get("EXPLORE", 0)
    other_n = total - build_n - fix_n - explore_n  # DEPLOY, DESIGN, PLAN, MIXED, etc.
    build_pct = build_n / max(total, 1) * 100
    fix_pct = fix_n / max(total, 1) * 100
    explore_pct = explore_n / max(total, 1) * 100
    other_pct = other_n / max(total, 1) * 100

    if build_pct > fix_pct and build_pct > explore_pct:
        identity = "Builder"
    elif fix_pct > build_pct and fix_pct > explore_pct:
        identity = "Firefighter"
    else:
        identity = "Explorer"

    # Monthly trend
    monthly = defaultdict(lambda: Counter())
    for s in sessions:
        if s["timestamps"]:
            month = min(s["timestamps"]).strftime("%Y-%m")
            monthly[month][s["category"]] += 1

    months_sorted = sorted(monthly.keys())
    build_arr = [monthly[m].get("BUILD", 0) for m in months_sorted]
    fix_arr = [monthly[m].get("FIX", 0) for m in months_sorted]
    explore_arr = [monthly[m].get("EXPLORE", 0) for m in months_sorted]
    # Compute Other per month = total_month - build - fix - explore
    other_arr = []
    for i, m in enumerate(months_sorted):
        month_total = sum(monthly[m].values())
        other_arr.append(max(0, month_total - build_arr[i] - fix_arr[i] - explore_arr[i]))
    trend_data = {
        "months": months_sorted,
        "build": build_arr,
        "fix": fix_arr,
        "explore": explore_arr,
        "other": other_arr,
    }

    return {
        "build_pct": round(build_pct, 1),
        "fix_pct": round(fix_pct, 1),
        "explore_pct": round(explore_pct, 1),
        "other_pct": round(other_pct, 1),
        "identity": identity,
        "trend": trend_data,
    }


def analyze_error_personality(data):
    """Section 9: Error recovery style."""
    sessions = data["sessions"]
    gave_up = 0
    retried = 0
    switched = 0

    for s in sessions:
        for e in s["error_sequences"]:
            action = e.get("post_action", "unknown")
            if action == "gave_up":
                gave_up += 1
            elif action == "retried_same_tool":
                retried += 1
            elif action == "switched_approach":
                switched += 1

    total = gave_up + retried + switched
    if total == 0:
        return {"gave_up_pct": 0, "retried_pct": 0, "switched_pct": 0, "label": "The Balanced", "stubbornness": 50}

    gave_up_pct = gave_up / total * 100
    retried_pct = retried / total * 100
    switched_pct = switched / total * 100

    stubbornness = retried_pct  # how often they just retry

    if retried_pct > 50:
        label = "The Bulldozer"
    elif switched_pct > 50:
        label = "The Adapter"
    elif gave_up_pct > 40:
        label = "The Quitter"
    else:
        label = "The Balanced"

    return {
        "gave_up_pct": round(gave_up_pct, 1),
        "retried_pct": round(retried_pct, 1),
        "switched_pct": round(switched_pct, 1),
        "label": label,
        "stubbornness": round(stubbornness, 1),
    }


def analyze_swear_report(data):
    """Section 11: Swear word report."""
    sessions = data["sessions"]
    all_swear_words = Counter()
    total_swears = 0
    swears_by_hour = defaultdict(int)

    for s in sessions:
        if not s["tone"]:
            continue
        total_swears += s["tone"]["user_swears"]
        all_swear_words.update(s["tone"]["user_swear_words"])
        for h, c in s["tone"].get("swears_by_hour", {}).items():
            local_h = (int(h) + TZ_OFFSET) % 24
            swears_by_hour[local_h] += c

    total_msgs = sum(s["tone"]["user_msg_count"] for s in sessions if s["tone"])
    swear_rate = total_swears / max(total_msgs, 1) * 100

    if total_swears == 0:
        personality = "Profanity-Free"
    elif swear_rate < 1:
        personality = "Occasional Slips"
    elif swear_rate < 5:
        personality = "Colorful Vocabulary"
    else:
        personality = "Sailor"

    peak_hour = max(range(24), key=lambda h: swears_by_hour.get(h, 0)) if swears_by_hour else 0

    return {
        "top_words": dict(all_swear_words.most_common(10)),
        "total": total_swears,
        "personality": personality,
        "peak_hour": peak_hour,
        "swear_rate": round(swear_rate, 1),
    }


def generate_quirks(data, dimensions):
    """Section 12: Conditional fun facts."""
    sessions = data["sessions"]
    quirks = []

    # Language switching
    comm = analyze_communication_style(data)
    if comm["languages"]:
        langs = ", ".join(comm["languages"])
        quirks.append(f"You switch to {langs} in your prompts")

    # Night sessions
    hour_counts = data["hour_counts"]
    late_sessions = sum(hour_counts.get(h, 0) for h in [0, 1, 2, 3, 4, 5])
    total_timed = sum(hour_counts.values())
    if total_timed > 0 and late_sessions / total_timed > 0.15:
        pct = round(late_sessions / total_timed * 100)
        quirks.append(f"{pct}% of your sessions start after midnight")

    # Please count
    please_count = data["word_counter"].get("please", 0)
    if please_count > 10:
        quirks.append(f'You said "please" {please_count} times')

    # Swear peak
    swear_data = analyze_swear_report(data)
    if swear_data["total"] > 5:
        quirks.append(f"Your swearing peaks at {_hour_label(swear_data['peak_hour'])}")

    # Longest session
    durations = [s["duration_min"] for s in sessions if s["duration_min"] > 0]
    if durations:
        longest = max(durations)
        if longest > 60:
            hours = longest / 60
            quirks.append(f"Your longest session was {hours:.1f} hours")

    # Most common first word
    opener_stopwords = {
        "you", "i", "the", "a", "an", "it", "is", "can", "do", "so", "we",
        "my", "me", "this", "that", "hey", "hi", "ok", "okay", "yes", "no",
        "claude", "now", "also", "just", "please", "thanks", "sure",
    }
    first_words = Counter()
    for s in sessions:
        if s["prompts"]:
            fw = s["prompts"][0]["text"].split()[0].lower() if s["prompts"][0]["text"] else ""
            if fw and len(fw) > 1 and fw not in opener_stopwords:
                first_words[fw] += 1
    if first_words:
        top_fw, top_count = first_words.most_common(1)[0]
        if top_count > 5:
            quirks.append(f'Your most common opener: "{top_fw}" ({top_count} times)')

    # Project juggling
    unique_projects = len(set(s["project"] for s in sessions))
    if unique_projects > 5:
        quirks.append(f"You juggle {unique_projects} projects")

    return quirks[:7]


def compute_evolution(data):
    """Section 13: Monthly niceness, specificity, success rate."""
    monthly = data["monthly_data"]
    months_sorted = sorted(monthly.keys())

    niceness_arr = []
    specificity_arr = []
    success_arr = []

    for m in months_sorted:
        d = monthly[m]
        niceness_arr.append(round(statistics.mean(d["niceness"]), 1) if d["niceness"] else 0)
        specificity_arr.append(round(statistics.mean(d["specificity"]), 1) if d["specificity"] else 0)
        success_arr.append(round(statistics.mean(d["success"]) * 100, 1) if d["success"] else 0)

    # Trend direction: composite across all 3 metrics
    # For each metric, compare first half vs second half. Score: +1 improve, -1 decline, 0 stable.
    # Use +-5% relative threshold for success (0-100 scale) and +-0.3 absolute for niceness/specificity (0-10 scale).
    def _metric_direction(arr, threshold_abs):
        if len(arr) >= 3:
            first_half = statistics.mean(arr[:len(arr) // 2])
            second_half = statistics.mean(arr[len(arr) // 2:])
        elif len(arr) == 2:
            first_half, second_half = arr[0], arr[1]
        else:
            return 0
        if second_half > first_half + threshold_abs:
            return 1
        elif second_half < first_half - threshold_abs:
            return -1
        return 0

    if len(success_arr) >= 2:
        score_sum = (
            _metric_direction(success_arr, 5)      # success: +-5pp
            + _metric_direction(niceness_arr, 0.3)  # niceness: +-0.3 on 0-10
            + _metric_direction(specificity_arr, 0.3)  # specificity: +-0.3 on 0-10
        )
        if score_sum > 0:
            trend = "improving"
        elif score_sum < 0:
            trend = "declining"
        else:
            trend = "mixed"
    else:
        trend = "stable"

    # If only 2 months, generate then-vs-now comparison data
    then_vs_now = None
    if len(months_sorted) == 2:
        then_vs_now = {
            "then_month": months_sorted[0],
            "now_month": months_sorted[1],
            "metrics": []
        }
        for label, arr in [("Niceness", niceness_arr), ("Specificity", specificity_arr), ("Success %", success_arr)]:
            old_val, new_val = arr[0], arr[1]
            if old_val > 0:
                pct_change = round((new_val - old_val) / old_val * 100, 1)
            else:
                pct_change = 0
            # Use per-metric thresholds matching the composite trend logic
            if label == "Success %":
                thresh = 5  # +-5pp for success rate
            else:
                thresh = 0.3  # +-0.3 for niceness/specificity (0-10 scale)
            direction = "up" if new_val > old_val + thresh else "down" if new_val < old_val - thresh else "stable"
            then_vs_now["metrics"].append({
                "label": label,
                "old": old_val,
                "new": new_val,
                "direction": direction,
                "pct_change": pct_change,
            })

    return {
        "months": months_sorted,
        "niceness": niceness_arr,
        "specificity": specificity_arr,
        "success": success_arr,
        "trend": trend,
        "then_vs_now": then_vs_now,
    }


def compute_ai_relationship(dimensions):
    """Section 14: Relationship type based on warmth + autonomy + patience."""
    w = dimensions["warmth"]
    a = dimensions["autonomy"]
    p = dimensions["patience"]

    if w >= 60 and p >= 60:
        return {"type": "Best Friends", "description": "Warm, patient, and collaborative. You and Claude are a team."}
    if w <= 40 and a >= 60:
        return {"type": "Boss & Employee", "description": "Efficient and direct. You give orders, Claude executes."}
    if p <= 40 and w >= 40:
        return {"type": "Sparring Partners", "description": "Energetic and impatient. You push Claude hard and expect fast results."}
    if a >= 70 and 40 <= w <= 60:
        return {"type": "Silent Partner", "description": "You delegate fully and let Claude do its thing. Minimal intervention."}
    if w <= 35 and dimensions["precision"] >= 60 and p <= 40:
        return {"type": "Taskmaster", "description": "Cold, precise, and impatient. Every token must count."}
    if w >= 60 and a <= 40:
        return {"type": "Study Buddy", "description": "Warm and hands-on. You learn together, step by step."}
    return {"type": "Balanced Partnership", "description": "A healthy mix of delegation and collaboration."}


# ---------------------------------------------------------------------------
# HTML Generation
# ---------------------------------------------------------------------------
def _html_escape(text):
    return (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _censor_word(word):
    if len(word) <= 2:
        return word
    return word[0] + "*" * (len(word) - 2) + word[-1]


def _hour_label(h):
    if h == 0:
        return "12am"
    if h < 12:
        return f"{h}am"
    if h == 12:
        return "12pm"
    return f"{h-12}pm"


def generate_html(data, dimensions, archetype_name):
    """Read template, do placeholder replacements, return HTML string."""
    template = TEMPLATE_PATH.read_text()
    sessions = data["sessions"]

    author = AUTHOR_NAME or "Claude Code User"
    total_prompts = sum(len(s["prompts"]) for s in sessions)
    total_sessions = len(sessions)

    # Date range
    all_ts = []
    for s in sessions:
        all_ts.extend(s["timestamps"])
    if all_ts:
        start_date = min(all_ts).strftime("%b %d")
        end_date = max(all_ts).strftime("%b %d, %Y")
        date_range = f"{start_date} &ndash; {end_date}"
    else:
        date_range = "No data"

    # Archetype
    arch = ARCHETYPES[archetype_name]

    # Dimension labels
    dim_labels = {d: dimension_label(d, v) for d, v in dimensions.items()}

    # Section analyses
    comm = analyze_communication_style(data)
    emotional = analyze_emotional_timeline(data)
    rhythm = analyze_work_rhythm(data)
    loyalty = analyze_project_loyalty(data)
    builder = analyze_builder_identity(data)
    error_pers = analyze_error_personality(data)
    swear = analyze_swear_report(data)
    quirks = generate_quirks(data, dimensions)
    evolution = compute_evolution(data)
    relationship = compute_ai_relationship(dimensions)

    # Delegation stats
    prompts_per_session = total_prompts / max(total_sessions, 1)
    corrections_per_session = sum(s["correction_count"] for s in sessions) / max(total_sessions, 1)

    # Build quirks HTML
    quirks_html = ""
    for q in quirks:
        quirks_html += f'<div class="quirk-item">{_html_escape(q)}</div>\n'
    if not quirks_html:
        quirks_html = '<div class="quirk-item">Not enough data for quirks yet</div>'

    # Build swear pills HTML
    swear_pills = ""
    for word, count in list(swear["top_words"].items())[:8]:
        censored = _censor_word(word) if SANITIZE else word
        swear_pills += f'<span class="pill">{_html_escape(censored)} ({count})</span> '
    if not swear_pills:
        swear_pills = '<span class="pill">Clean as a whistle</span>'

    # Build word pills
    word_pills = ""
    for w in comm["top_words"][:12]:
        word_pills += f'<span class="pill">{_html_escape(w)}</span> '

    # Build bigram pills
    bigram_pills = ""
    for bg in comm["top_bigrams"][:6]:
        bigram_pills += f'<span class="pill">{_html_escape(bg)}</span> '

    # Project donut data
    proj_labels = list(loyalty["project_counts"].keys())
    proj_values = list(loyalty["project_counts"].values())
    if SANITIZE:
        proj_labels = [f"Project {i+1}" for i in range(len(proj_labels))]

    # Archetype top 3 stats
    sorted_dims = sorted(dimensions.items(), key=lambda x: abs(x[1] - 50), reverse=True)[:3]
    arch_stats_html = ""
    for dim_name, val in sorted_dims:
        label = dim_labels[dim_name]
        arch_stats_html += f'<div class="arch-stat"><span class="arch-dim">{dim_name.replace("_", " ").title()}</span><span class="arch-val">{val}/100 - {label}</span></div>\n'

    # Share card: top 3 dimensions + key stats
    sorted_dims_by_score = sorted(dimensions.items(), key=lambda x: x[1], reverse=True)[:3]
    share_dims_html = ""
    for dim_name, val in sorted_dims_by_score:
        label = dim_labels[dim_name]
        share_dims_html += f'<span class="pill" style="background:rgba(168,85,247,0.15);color:#a855f7;">{dim_name.replace("_"," ").title()}: {val}</span> '

    total_hours = round(sum(s["duration_min"] for s in sessions) / 60, 1)

    # Heatmap grid JSON (7 rows x 24 cols)
    heatmap_data = json.dumps(rhythm["grid"])

    # Do all replacements
    replacements = {
        # Section 1: Title
        "__UP_AUTHOR__": _html_escape(author),
        "__UP_DATE_RANGE__": date_range,
        "__UP_SESSION_COUNT__": str(total_sessions),
        "__UP_PROMPT_COUNT__": str(total_prompts),
        # Section 2: Radar
        "__UP_RADAR_LABELS__": json.dumps(["Patience", "Precision", "Warmth", "Ambition", "Persistence", "Autonomy", "Night Owl"]),
        "__UP_RADAR_VALUES__": json.dumps([dimensions["patience"], dimensions["precision"], dimensions["warmth"], dimensions["ambition"], dimensions["persistence"], dimensions["autonomy"], dimensions["night_owl"]]),
        "__UP_PATIENCE_SCORE__": str(dimensions["patience"]),
        "__UP_PATIENCE_LABEL__": dim_labels["patience"],
        "__UP_PRECISION_SCORE__": str(dimensions["precision"]),
        "__UP_PRECISION_LABEL__": dim_labels["precision"],
        "__UP_WARMTH_SCORE__": str(dimensions["warmth"]),
        "__UP_WARMTH_LABEL__": dim_labels["warmth"],
        "__UP_AMBITION_SCORE__": str(dimensions["ambition"]),
        "__UP_AMBITION_LABEL__": dim_labels["ambition"],
        "__UP_PERSISTENCE_SCORE__": str(dimensions["persistence"]),
        "__UP_PERSISTENCE_LABEL__": dim_labels["persistence"],
        "__UP_AUTONOMY_SCORE__": str(dimensions["autonomy"]),
        "__UP_AUTONOMY_LABEL__": dim_labels["autonomy"],
        "__UP_NIGHTOWL_SCORE__": str(dimensions["night_owl"]),
        "__UP_NIGHTOWL_LABEL__": dim_labels["night_owl"],
        # Section 3: Archetype
        "__UP_ARCHETYPE_NAME__": archetype_name,
        "__UP_ARCHETYPE_TAGLINE__": arch["tagline"],
        "__UP_ARCHETYPE_DESC__": arch["description"],
        "__UP_ARCHETYPE_STATS__": arch_stats_html,
        # Section 4: Communication
        "__UP_WORD_PILLS__": word_pills,
        "__UP_BIGRAM_PILLS__": bigram_pills,
        "__UP_GUIRAUD__": str(comm["guiraud"]),
        "__UP_STYLE_LABEL__": comm["style"],
        "__UP_QUESTION_PCT__": str(comm["question_pct"]),
        "__UP_AVG_WPM__": str(comm["avg_wpm"]),
        "__UP_LANGUAGES__": ", ".join(comm["languages"]) if comm["languages"] else "English only",
        # Section 5: Emotional timeline
        "__UP_NICE_BY_HOUR__": json.dumps(emotional["nice_arr"]),
        "__UP_HARSH_BY_HOUR__": json.dumps(emotional["harsh_arr"]),
        "__UP_CALMEST_HOUR__": _hour_label(emotional["calmest_hour"]),
        "__UP_STORMIEST_HOUR__": _hour_label(emotional["stormiest_hour"]),
        # Section 6: Work rhythm
        "__UP_HEATMAP_DATA__": heatmap_data,
        "__UP_PEAK_HOURS__": ", ".join(_hour_label(h) for h in rhythm["peak_hours"]),
        "__UP_WEEKEND_PCT__": str(rhythm["weekend_pct"]),
        "__UP_AVG_DURATION__": str(rhythm["avg_duration"]),
        "__UP_RHYTHM_LABEL__": rhythm["rhythm"],
        # Section 7: Project loyalty
        "__UP_PROJECT_LABELS__": json.dumps(proj_labels),
        "__UP_PROJECT_VALUES__": json.dumps(proj_values),
        "__UP_LOYALTY_LABEL__": loyalty["loyalty_label"],
        "__UP_LOYALTY_SCORE__": str(loyalty["loyalty_score"]),
        "__UP_SWITCH_RATE__": str(loyalty["switch_rate"]),
        # Section 8: Builder identity
        "__UP_BUILD_PCT__": str(builder["build_pct"]),
        "__UP_FIX_PCT__": str(builder["fix_pct"]),
        "__UP_EXPLORE_PCT__": str(builder["explore_pct"]),
        "__UP_BUILDER_IDENTITY__": builder["identity"],
        "__UP_BUILDER_MONTHS__": json.dumps(builder["trend"]["months"]),
        "__UP_BUILDER_BUILD__": json.dumps(builder["trend"]["build"]),
        "__UP_BUILDER_FIX__": json.dumps(builder["trend"]["fix"]),
        "__UP_BUILDER_EXPLORE__": json.dumps(builder["trend"]["explore"]),
        "__UP_BUILDER_OTHER__": json.dumps(builder["trend"]["other"]),
        # Section 9: Error personality
        "__UP_GAVEUP_PCT__": str(error_pers["gave_up_pct"]),
        "__UP_RETRIED_PCT__": str(error_pers["retried_pct"]),
        "__UP_SWITCHED_PCT__": str(error_pers["switched_pct"]),
        "__UP_ERROR_LABEL__": error_pers["label"],
        "__UP_STUBBORNNESS__": str(error_pers["stubbornness"]),
        # Section 10: Delegation
        "__UP_PROMPTS_PER_SESSION__": str(round(prompts_per_session, 1)),
        "__UP_CORRECTIONS_PER_SESSION__": str(round(corrections_per_session, 1)),
        "__UP_AUTONOMY_SCORE_2__": str(dimensions["autonomy"]),
        # Section 11: Swear report
        "__UP_SWEAR_PILLS__": swear_pills,
        "__UP_SWEAR_PEAK_HOUR__": _hour_label(swear["peak_hour"]),
        "__UP_SWEAR_PERSONALITY__": swear["personality"],
        "__UP_SWEAR_TOTAL__": str(swear["total"]),
        # Section 12: Quirks
        "__UP_QUIRKS_HTML__": quirks_html,
        # Section 13: Evolution
        "__UP_EVO_MONTHS__": json.dumps(evolution["months"]),
        "__UP_EVO_NICENESS__": json.dumps(evolution["niceness"]),
        "__UP_EVO_SPECIFICITY__": json.dumps(evolution["specificity"]),
        "__UP_EVO_SUCCESS__": json.dumps(evolution["success"]),
        "__UP_EVO_TREND__": evolution["trend"],
        "__UP_EVO_USE_CHART__": json.dumps(len(evolution["months"]) >= 3),
        "__UP_EVO_THEN_VS_NOW__": json.dumps(evolution.get("then_vs_now")),
        # Section 14: AI Relationship
        "__UP_RELATIONSHIP_TYPE__": relationship["type"],
        "__UP_RELATIONSHIP_DESC__": relationship["description"],
        "__UP_WARMTH_SCORE_2__": str(dimensions["warmth"]),
        "__UP_PATIENCE_SCORE_2__": str(dimensions["patience"]),
        "__UP_AUTONOMY_SCORE_3__": str(dimensions["autonomy"]),
        # Section 8 extra: Other category
        "__UP_OTHER_PCT__": str(builder["other_pct"]),
        # Section 15: Share card
        "__UP_SHARE_DIMS__": share_dims_html,
        "__UP_TOTAL_HOURS__": str(total_hours),
    }

    html = template
    for key, value in replacements.items():
        html = html.replace(key, str(value))

    return html


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("Collecting session data...")
    data = collect_data()

    if not data["sessions"]:
        print("No session data found. Make sure you have Claude Code sessions in ~/.claude/projects/")
        sys.exit(1)

    print("Computing personality dimensions...")
    dimensions = compute_dimensions(data)

    print("Selecting archetype...")
    archetype_name = select_archetype(dimensions)

    print("Generating HTML...")
    html = generate_html(data, dimensions, archetype_name)

    OUTPUT_DIR.mkdir(exist_ok=True)
    OUTPUT_PATH.write_text(html)
    print(f"Wrote {OUTPUT_PATH} ({len(html):,} bytes)")

    print(f"\nUser Profile Summary:")
    print(f"  Sessions: {len(data['sessions'])}")
    print(f"  Dimensions: {dimensions}")
    print(f"  Archetype: {archetype_name}")
    print(f"  Tagline: {ARCHETYPES[archetype_name]['tagline']}")


if __name__ == "__main__":
    main()
