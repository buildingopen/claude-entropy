#!/usr/bin/env python3
"""
Generate a self-contained soul.html deep personality profile from Claude Code session data.

Computes Big Five traits, custom dimensions, contradiction detection, and generates
narrative prose about the user's personality. Not a scorecard - a psychological profile
written in second person with numbers as evidence.

Outputs dist/soul.html.
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

from generate_user_profile import (
    collect_data,
    select_archetype,
    compute_dimensions,
    analyze_communication_style,
    analyze_builder_identity,
    analyze_error_personality,
    analyze_swear_report,
    analyze_work_rhythm,
    compute_evolution,
    _hour_label,
    _html_escape,
    ARCHETYPES,
    TZ_OFFSET,
    SANITIZE,
    AUTHOR_NAME,
)

TEMPLATE_PATH = SCRIPT_DIR / "soul.html"
OUTPUT_DIR = SCRIPT_DIR / "dist"
OUTPUT_PATH = OUTPUT_DIR / "soul.html"

MIN_SESSIONS = 20


# ---------------------------------------------------------------------------
# Signal Computation
# ---------------------------------------------------------------------------
def compute_signals(data):
    """Aggregate all raw numbers needed by narrative fragments."""
    sessions = data["sessions"]
    all_texts = data["all_user_texts"]
    n = len(sessions)
    if n == 0:
        return {}

    total_prompts = sum(len(s["prompts"]) for s in sessions)

    # Basic counts
    all_specs = [p["specificity"] for s in sessions for p in s["prompts"]]
    avg_spec = statistics.mean(all_specs) if all_specs else 5.0
    all_wc = [p["word_count"] for s in sessions for p in s["prompts"]]
    avg_words_per_prompt = statistics.mean(all_wc) if all_wc else 20

    # Niceness
    niceness_scores = [s["tone"]["niceness_score"] for s in sessions if s["tone"]]
    avg_niceness = statistics.mean(niceness_scores) if niceness_scores else 5.0
    niceness_stddev = statistics.stdev(niceness_scores) if len(niceness_scores) > 1 else 0

    # Error sequences
    gave_up = sum(1 for s in sessions for e in s["error_sequences"] if e.get("post_action") == "gave_up")
    switched = sum(1 for s in sessions for e in s["error_sequences"] if e.get("post_action") == "switched_approach")
    retried = sum(1 for s in sessions for e in s["error_sequences"] if e.get("post_action") == "retried_same_tool")
    total_errors = gave_up + switched + retried
    gave_up_pct = gave_up / max(total_errors, 1) * 100
    switched_pct = switched / max(total_errors, 1) * 100
    retried_pct = retried / max(total_errors, 1) * 100

    # Frustration
    frustration_count = sum(s["frustration_count"] for s in sessions)
    frustration_per_session = frustration_count / n

    # ALL_CAPS words
    all_caps_count = 0
    for s in sessions:
        for p in s["prompts"]:
            if p["frustration"]:
                caps_val = p["frustration"].get("all_caps_words", [])
                all_caps_count += len(caps_val) if isinstance(caps_val, list) else int(caps_val)
    all_caps_per_session = all_caps_count / n

    # Question ratio
    question_count = sum(1 for t in all_texts if t.strip().endswith("?"))
    question_ratio = question_count / max(len(all_texts), 1) * 100

    # Numbered steps percentage
    numbered_steps_count = 0
    for s in sessions:
        for p in s["prompts"]:
            if re.search(r"^\s*\d+[\.\)]\s", p["text"], re.MULTILINE):
                numbered_steps_count += 1
    numbered_steps_pct = numbered_steps_count / max(total_prompts, 1) * 100

    # Unique projects
    unique_projects = len(set(s["project"] for s in sessions))

    # Category breakdown
    cat_counts = Counter(s["category"] for s in sessions)
    build_pct = cat_counts.get("BUILD", 0) / n * 100
    fix_pct = cat_counts.get("FIX", 0) / n * 100
    explore_pct = cat_counts.get("EXPLORE", 0) / n * 100

    # Success rate
    success_count = sum(1 for s in sessions if s["outcome"] in ("SUCCESS", "PARTIAL_SUCCESS"))
    success_pct = success_count / n * 100

    # Abandoned
    abandoned_pct = sum(1 for s in sessions if s["abandoned"]) / n * 100

    # Corrections
    correction_total = sum(s["correction_count"] for s in sessions)
    correction_rate = correction_total / max(total_prompts, 1) * 100

    # Commits per session
    total_commits = sum(s["commits"] for s in sessions)
    commits_per_session = total_commits / n

    # Deploy count
    deploy_count = sum(s["deployments"] for s in sessions)

    # Prompts per session
    prompts_per_session = total_prompts / n

    # Vocabulary richness
    word_counter = data["word_counter"]
    total_words_vocab = sum(word_counter.values())
    unique_words = len(word_counter)
    guiraud = unique_words / math.sqrt(total_words_vocab) if total_words_vocab > 0 else 0

    # Vocabulary by frustration level
    frustrated_words = Counter()
    calm_words = Counter()
    for s in sessions:
        is_frustrated = s["frustration_count"] > 0
        for p in s["prompts"]:
            clean = re.sub(r"```[\s\S]*?```", "", p["text"]).lower()
            words = [w for w in re.findall(r"\b[a-z]{2,}\b", clean)]
            if is_frustrated:
                frustrated_words.update(words)
            else:
                calm_words.update(words)

    total_frustrated = sum(frustrated_words.values())
    unique_frustrated = len(frustrated_words)
    guiraud_frustrated = unique_frustrated / math.sqrt(total_frustrated) if total_frustrated > 0 else 0

    total_calm = sum(calm_words.values())
    unique_calm = len(calm_words)
    guiraud_calm = unique_calm / math.sqrt(total_calm) if total_calm > 0 else 0

    # Swear data
    total_swears = 0
    swear_words_counter = Counter()
    swears_by_hour = defaultdict(int)
    for s in sessions:
        if s["tone"]:
            total_swears += s["tone"]["user_swears"]
            swear_words_counter.update(s["tone"]["user_swear_words"])
            for h, c in s["tone"].get("swears_by_hour", {}).items():
                local_h = (int(h) + TZ_OFFSET) % 24
                swears_by_hour[local_h] += c

    total_msgs = sum(s["tone"]["user_msg_count"] for s in sessions if s["tone"])
    swear_rate = total_swears / max(total_msgs, 1) * 100

    swear_peak_hour = max(range(24), key=lambda h: swears_by_hour.get(h, 0)) if swears_by_hour else 0
    session_peak_hour = max(range(24), key=lambda h: data["hour_counts"].get(h, 0)) if data["hour_counts"] else 12

    # Swear variance by hour
    swear_by_hour_arr = [swears_by_hour.get(h, 0) for h in range(24)]
    swear_hour_vals = [v for v in swear_by_hour_arr if v > 0]
    swear_variance_by_hour = statistics.stdev(swear_hour_vals) if len(swear_hour_vals) > 1 else 0

    # Positive ending percentage
    positive_endings = 0
    for s in sessions:
        if s["prompts"]:
            last_text = s["prompts"][-1]["text"].lower()
            if any(w in last_text for w in ["thanks", "thank", "great", "perfect", "awesome", "nice", "good"]):
                positive_endings += 1
    positive_ending_pct = positive_endings / n * 100

    # Duration stats
    durations = [s["duration_min"] for s in sessions if s["duration_min"] > 0]
    avg_duration = statistics.mean(durations) if durations else 0
    total_hours = sum(durations) / 60

    # First message ratio
    first_msg_ratios = []
    for s in sessions:
        if s["prompts"]:
            first_wc = s["prompts"][0]["word_count"]
            total_wc = sum(p["word_count"] for p in s["prompts"])
            if total_wc > 0:
                first_msg_ratios.append(first_wc / total_wc * 100)
    avg_first_msg_ratio = statistics.mean(first_msg_ratios) if first_msg_ratios else 50

    # Night/morning split
    hour_counts = data["hour_counts"]
    total_timed = sum(hour_counts.values()) if hour_counts else 1
    night_sessions = sum(hour_counts.get(h, 0) for h in [22, 23, 0, 1, 2, 3, 4, 5])
    morning_sessions = sum(hour_counts.get(h, 0) for h in [6, 7, 8, 9, 10, 11])
    night_session_pct = night_sessions / max(total_timed, 1) * 100
    weekend_sessions = sum(1 for s in sessions if s["timestamps"] and min(s["timestamps"]).weekday() >= 5)
    weekend_pct = weekend_sessions / n * 100

    # Morning vs evening success
    morning_success_list = []
    evening_success_list = []
    for s in sessions:
        if s["timestamps"]:
            h = (min(s["timestamps"]).hour + TZ_OFFSET) % 24
            is_success = 1 if s["outcome"] in ("SUCCESS", "PARTIAL_SUCCESS") else 0
            if 6 <= h < 12:
                morning_success_list.append(is_success)
            elif 18 <= h or h < 4:
                evening_success_list.append(is_success)
    morning_success = statistics.mean(morning_success_list) * 100 if morning_success_list else 0
    evening_success = statistics.mean(evening_success_list) * 100 if evening_success_list else 0

    # Language detection
    comm = analyze_communication_style(data)
    lang_count = len(comm["languages"])

    # Monthly niceness trend
    monthly = data["monthly_data"]
    months_sorted = sorted(monthly.keys())
    monthly_niceness = []
    for m in months_sorted:
        d = monthly[m]
        monthly_niceness.append(statistics.mean(d["niceness"]) if d["niceness"] else 0)

    # Please count
    please_count = data["word_counter"].get("please", 0)
    thanks_count = data["word_counter"].get("thanks", 0) + data["word_counter"].get("thank", 0)
    nice_word_count = please_count + thanks_count

    # Peak coding hours
    peak_hours = sorted(hour_counts, key=hour_counts.get, reverse=True)[:3] if hour_counts else [12]
    peak_start = _hour_label(peak_hours[0]) if peak_hours else "12pm"

    return {
        "sessions_analyzed": n,
        "total_prompts": total_prompts,
        "total_hours": round(total_hours, 1),
        "avg_spec": round(avg_spec, 1),
        "avg_words_per_prompt": round(avg_words_per_prompt, 1),
        "avg_niceness": round(avg_niceness, 1),
        "niceness_stddev": round(niceness_stddev, 2),
        "gave_up_pct": round(gave_up_pct, 1),
        "switched_pct": round(switched_pct, 1),
        "retried_pct": round(retried_pct, 1),
        "total_errors": total_errors,
        "frustration_count": frustration_count,
        "frustration_per_session": round(frustration_per_session, 2),
        "all_caps_count": all_caps_count,
        "all_caps_per_session": round(all_caps_per_session, 2),
        "question_ratio": round(question_ratio, 1),
        "numbered_steps_pct": round(numbered_steps_pct, 1),
        "unique_projects": unique_projects,
        "build_pct": round(build_pct, 1),
        "fix_pct": round(fix_pct, 1),
        "explore_pct": round(explore_pct, 1),
        "success_pct": round(success_pct, 1),
        "abandoned_pct": round(abandoned_pct, 1),
        "correction_rate": round(correction_rate, 1),
        "commits_per_session": round(commits_per_session, 2),
        "deploy_count": deploy_count,
        "prompts_per_session": round(prompts_per_session, 1),
        "guiraud": round(guiraud, 1),
        "unique_words": unique_words,
        "guiraud_frustrated": round(guiraud_frustrated, 1),
        "guiraud_calm": round(guiraud_calm, 1),
        "total_swears": total_swears,
        "swear_rate": round(swear_rate, 2),
        "swear_peak_hour": _hour_label(swear_peak_hour),
        "session_peak_hour": _hour_label(session_peak_hour),
        "swear_variance_by_hour": round(swear_variance_by_hour, 2),
        "positive_ending_pct": round(positive_ending_pct, 1),
        "avg_duration": round(avg_duration, 1),
        "night_session_pct": round(night_session_pct, 1),
        "weekend_pct": round(weekend_pct, 1),
        "morning_success": round(morning_success, 1),
        "evening_success": round(evening_success, 1),
        "avg_first_msg_ratio": round(avg_first_msg_ratio, 1),
        "lang_count": lang_count,
        "nice_word_count": nice_word_count,
        "peak_start": peak_start,
        "monthly_niceness": monthly_niceness,
        "months_sorted": months_sorted,
        "month_count": len(months_sorted),
    }


# ---------------------------------------------------------------------------
# Big Five Computation
# ---------------------------------------------------------------------------
def compute_big_five(signals):
    """Compute Big Five personality traits (0-100 each)."""
    s = signals

    # Openness
    openness = 50
    if s["unique_projects"] > 5: openness += 15
    elif s["unique_projects"] > 3: openness += 8
    if s["explore_pct"] > 25: openness += 10
    elif s["explore_pct"] > 15: openness += 5
    if s["question_ratio"] > 20: openness += 10
    elif s["question_ratio"] > 12: openness += 5
    if s["guiraud"] > 8: openness += 10
    elif s["guiraud"] > 6: openness += 5
    if s["lang_count"] >= 2: openness += 5
    if s["unique_projects"] == 1: openness -= 15
    if s["question_ratio"] < 5: openness -= 10
    if s["guiraud"] < 4: openness -= 8

    # Conscientiousness
    conscientiousness = 50
    if s["avg_spec"] > 7: conscientiousness += 15
    elif s["avg_spec"] > 6: conscientiousness += 8
    if s["correction_rate"] < 5: conscientiousness += 10
    elif s["correction_rate"] < 10: conscientiousness += 5
    if s["commits_per_session"] > 0.5: conscientiousness += 10
    if s["abandoned_pct"] < 10: conscientiousness += 10
    elif s["abandoned_pct"] < 20: conscientiousness += 5
    if s["numbered_steps_pct"] > 10: conscientiousness += 5
    if s["avg_spec"] < 4: conscientiousness -= 15
    elif s["avg_spec"] < 5: conscientiousness -= 8
    if s["abandoned_pct"] > 30: conscientiousness -= 10
    elif s["abandoned_pct"] > 20: conscientiousness -= 8
    if s["correction_rate"] > 20: conscientiousness -= 10
    elif s["correction_rate"] > 15: conscientiousness -= 5

    # Extraversion
    extraversion = 50
    if s["avg_words_per_prompt"] > 50: extraversion += 15
    elif s["avg_words_per_prompt"] > 30: extraversion += 8
    if s["avg_niceness"] > 7: extraversion += 10
    if s["prompts_per_session"] > 12: extraversion += 10
    elif s["prompts_per_session"] > 8: extraversion += 5
    if s["positive_ending_pct"] > 40: extraversion += 5
    if s["avg_words_per_prompt"] < 10: extraversion -= 15
    elif s["avg_words_per_prompt"] < 15: extraversion -= 8
    if s["avg_niceness"] < 3: extraversion -= 10
    if s["prompts_per_session"] < 4: extraversion -= 10

    # Agreeableness
    agreeableness = 50
    if s["avg_niceness"] > 8: agreeableness += 15
    elif s["avg_niceness"] > 7: agreeableness += 10
    elif s["avg_niceness"] > 6: agreeableness += 5
    if s["swear_rate"] == 0: agreeableness += 10
    if s["frustration_per_session"] < 0.3: agreeableness += 10
    if s["swear_rate"] > 5: agreeableness -= 15
    if s["avg_niceness"] < 3: agreeableness -= 10
    if s["frustration_per_session"] > 2: agreeableness -= 10

    # Neuroticism
    neuroticism = 50
    if s["frustration_per_session"] > 2: neuroticism += 15
    elif s["frustration_per_session"] > 1: neuroticism += 8
    if s["all_caps_per_session"] > 1: neuroticism += 10
    if s["gave_up_pct"] > 40: neuroticism += 10
    elif s["gave_up_pct"] > 25: neuroticism += 5
    if s["swear_variance_by_hour"] > 3: neuroticism += 10
    if s["niceness_stddev"] > 2: neuroticism += 5
    if s["frustration_per_session"] < 0.2: neuroticism -= 15
    if s["all_caps_per_session"] == 0: neuroticism -= 10
    if s["gave_up_pct"] < 10: neuroticism -= 10
    if s["niceness_stddev"] < 1: neuroticism -= 5

    return {
        "openness": max(0, min(100, round(openness))),
        "conscientiousness": max(0, min(100, round(conscientiousness))),
        "extraversion": max(0, min(100, round(extraversion))),
        "agreeableness": max(0, min(100, round(agreeableness))),
        "neuroticism": max(0, min(100, round(neuroticism))),
    }


# ---------------------------------------------------------------------------
# Custom Dimensions (0-100 spectrum)
# ---------------------------------------------------------------------------
def compute_custom_dimensions(signals):
    """Compute 4 custom spectrum dimensions."""
    s = signals

    # Thinking Style: 0=Intuitive, 100=Systematic
    thinking = 50
    if s["avg_spec"] > 7: thinking += 15
    elif s["avg_spec"] > 6: thinking += 8
    if s["numbered_steps_pct"] > 15: thinking += 10
    elif s["numbered_steps_pct"] > 8: thinking += 5
    if s["avg_words_per_prompt"] > 60: thinking += 8
    if s["question_ratio"] > 20: thinking -= 8
    if s["avg_spec"] < 4: thinking -= 15
    elif s["avg_spec"] < 5: thinking -= 8

    # Risk Tolerance: 0=Cautious, 100=Bold
    risk = 50
    if s["deploy_count"] > s["sessions_analyzed"] * 0.1: risk += 15
    elif s["deploy_count"] > 0: risk += 8
    if s["avg_duration"] > 40: risk += 8
    if s["unique_projects"] > 5: risk += 5
    if s["abandoned_pct"] < 10: risk -= 5
    if s["deploy_count"] == 0: risk -= 10
    if s["correction_rate"] > 15: risk -= 5

    # Learning Style: 0=Reader, 100=Doer
    learning = 50
    if s["explore_pct"] > 25: learning -= 15
    elif s["explore_pct"] > 15: learning -= 8
    if s["build_pct"] > 50: learning += 15
    elif s["build_pct"] > 35: learning += 8
    if s["question_ratio"] > 20: learning -= 8
    if s["correction_rate"] > 15: learning += 5

    # Stress Response: 0=Calm, 100=Volatile
    stress = 50
    if s["frustration_per_session"] > 2: stress += 15
    elif s["frustration_per_session"] > 1: stress += 8
    if s["swear_variance_by_hour"] > 3: stress += 8
    if s["all_caps_per_session"] > 1: stress += 10
    if s["gave_up_pct"] > 30: stress += 5
    if s["niceness_stddev"] > 2: stress += 5
    if s["frustration_per_session"] < 0.3: stress -= 15
    if s["all_caps_per_session"] == 0: stress -= 8
    if s["niceness_stddev"] < 1: stress -= 5

    return {
        "thinking_style": max(0, min(100, round(thinking))),
        "risk_tolerance": max(0, min(100, round(risk))),
        "learning_style": max(0, min(100, round(learning))),
        "stress_response": max(0, min(100, round(stress))),
    }


# ---------------------------------------------------------------------------
# Contradiction Detectors
# ---------------------------------------------------------------------------
def detect_contradictions(big5, custom, signals):
    """Detect personality contradictions. Returns list of dicts with title + narrative."""
    s = signals
    contradictions = []

    # 1. Polite but frustrated (lowered from >6 to >4.5 - any measurable politeness + high frustration)
    if s["avg_niceness"] > 4.5 and s["frustration_per_session"] > 1:
        contradictions.append({
            "title": "Polite but Frustrated",
            "text": (
                f"You're not rude, averaging {s['avg_niceness']}/10 on niceness, with {s['nice_word_count']} 'please' and 'thanks' across your sessions. "
                f"But the frustration signals tell a different story: {s['frustration_count']} outbursts, "
                f"{s['all_caps_count']} ALL_CAPS words, {s['frustration_per_session']:.1f} frustration events per session. "
                "The civility is real, but so is the pressure building underneath."
            ),
        })

    # 2. Frustrated but successful
    if s["frustration_per_session"] > 1 and s["success_pct"] > 65:
        contradictions.append({
            "title": "Frustrated but Successful",
            "text": (
                f"You show frustration {s['frustration_per_session']:.1f} times per session, "
                f"yet your success rate is {s['success_pct']:.0f}%. "
                f"The frustration isn't sabotaging your outcomes; it may even be fuel. "
                f"Across {s['sessions_analyzed']} sessions, the data says: messy process, working results."
            ),
        })

    # 3. Precise but error-prone (lowered from >6 to >5)
    if s["avg_spec"] > 5 and s["total_errors"] > s["sessions_analyzed"] * 0.5:
        error_rate = s["total_errors"] / max(s["sessions_analyzed"], 1)
        contradictions.append({
            "title": "Precise but Error-Prone",
            "text": (
                f"Your prompts score {s['avg_spec']}/10 on specificity, "
                f"yet you encounter {error_rate:.1f} errors per session on average ({s['total_errors']:,} total). "
                "This isn't carelessness; you push into genuinely hard territory. "
                "The specificity is why you attempt problems that generate this many errors."
            ),
        })

    # 4. Night owl, morning performer
    if s["night_session_pct"] > 30 and s["morning_success"] > s["evening_success"] + 5:
        contradictions.append({
            "title": "Night Owl, Morning Performer",
            "text": (
                f"{s['night_session_pct']:.0f}% of your sessions happen after dark. "
                f"But your success rate is {s['morning_success']:.0f}% in the morning "
                f"vs {s['evening_success']:.0f}% at night. "
                "Your preference and your performance disagree."
            ),
        })

    # 5. Vocabulary changes under stress (detect both directions)
    if s["guiraud_calm"] > 0 and s["guiraud_frustrated"] > 0:
        ratio = s["guiraud_frustrated"] / s["guiraud_calm"]
        if ratio < 0.8:
            contradictions.append({
                "title": "Vocabulary Narrows Under Stress",
                "text": (
                    f"When calm, your vocabulary richness is {s['guiraud_calm']}. "
                    f"During frustrating sessions, it drops to {s['guiraud_frustrated']}. "
                    "Stress literally shrinks your language."
                ),
            })
        elif ratio > 1.2:
            contradictions.append({
                "title": "Vocabulary Expands Under Stress",
                "text": (
                    f"When calm, your vocabulary richness is {s['guiraud_calm']}. "
                    f"During frustrating sessions, it rises to {s['guiraud_frustrated']}. "
                    "Stress makes you more articulate, not less. You reach for more precise words "
                    "when things go wrong, as if naming the problem more exactly could help solve it."
                ),
            })

    # 6. Delegator who micromanages (lowered thresholds)
    if s["avg_first_msg_ratio"] > 45 and s["correction_rate"] > 7:
        contradictions.append({
            "title": "Delegator Who Course-Corrects",
            "text": (
                f"Your first message carries {s['avg_first_msg_ratio']:.0f}% of the session's text, "
                f"a substantial upfront investment. Yet you still correct course {s['correction_rate']:.1f}% of the time. "
                "You invest heavily in setting direction, but the path still needs adjusting. "
                "Either the problems evolve, or your initial vision sharpens as Claude starts working."
            ),
        })

    # 7. Builder who mostly fixes
    if s["build_pct"] < s["fix_pct"] and s["fix_pct"] > 20:
        contradictions.append({
            "title": "Builder Who Mostly Fixes",
            "text": (
                f"{s['fix_pct']:.0f}% of sessions are bug fixes vs {s['build_pct']:.0f}% new features. "
                "The ambition is real; the codebase has other plans."
            ),
        })

    # 8. Gets nicer/harsher over time (lowered from 3 months to 2)
    monthly_n = s["monthly_niceness"]
    if len(monthly_n) >= 2:
        first_val = monthly_n[0]
        last_val = monthly_n[-1]
        if abs(last_val - first_val) > 0.3:
            direction = "trended upward" if last_val > first_val else "trended downward"
            interp = ("You're getting more comfortable, or more appreciative."
                      if last_val > first_val else
                      "Familiarity may be breeding impatience, or harder problems are wearing on you.")
            contradictions.append({
                "title": "Shifting Tone",
                "text": (
                    f"Your niceness has {direction} over {s['month_count']} months, "
                    f"from {first_val:.1f} to {last_val:.1f}. {interp}"
                ),
            })

    # 9. Swear-hour mismatch
    if s["total_swears"] > 5 and s["swear_peak_hour"] != s["session_peak_hour"]:
        contradictions.append({
            "title": "Swear-Hour Mismatch",
            "text": (
                f"You swear most at {s['swear_peak_hour']}, "
                f"but that's not when you code most ({s['session_peak_hour']}). "
                f"Something about {s['swear_peak_hour']} specifically gets under your skin."
            ),
        })

    # 10. Explorer who rarely asks questions
    if s["explore_pct"] > 20 and s["question_ratio"] < 10:
        contradictions.append({
            "title": "Explorer Who Doesn't Ask",
            "text": (
                f"You spend {s['explore_pct']:.0f}% of sessions exploring, "
                f"yet only {s['question_ratio']:.0f}% of your messages are questions. "
                "You explore by commanding, not by inquiring. "
                "Your curiosity manifests as directives, not queries."
            ),
        })

    # 11. Heavy deployer with many errors
    if s["deploy_count"] > s["sessions_analyzed"] * 0.5 and s["total_errors"] > s["sessions_analyzed"] * 2:
        contradictions.append({
            "title": "Ships Fast, Breaks Things",
            "text": (
                f"You've triggered {s['deploy_count']:,} deployments across {s['sessions_analyzed']} sessions, "
                f"but also accumulated {s['total_errors']:,} errors. "
                "You ship despite the turbulence. Speed over caution, results over comfort."
            ),
        })

    return contradictions


# ---------------------------------------------------------------------------
# Narrative Engine
# ---------------------------------------------------------------------------
def _select_opener(trait, score):
    """Select opener sentence based on trait score range."""
    if score >= 70:
        level = "high"
    elif score >= 50:
        level = "mid_high"
    elif score >= 30:
        level = "mid_low"
    else:
        level = "low"
    return OPENERS.get(trait, {}).get(level, "")


OPENERS = {
    "openness": {
        "high": "You're driven by curiosity.",
        "mid_high": "You have a healthy appetite for exploration.",
        "mid_low": "You prefer depth over breadth.",
        "low": "You find what works and stick with it.",
    },
    "conscientiousness": {
        "high": "You plan before you build.",
        "mid_high": "You bring structure to your work.",
        "mid_low": "Structure isn't your first instinct.",
        "low": "You work by feel, not by plan.",
    },
    "extraversion": {
        "high": "You're a talker.",
        "mid_high": "You engage actively with your tools.",
        "mid_low": "You keep things brief.",
        "low": "You're a person of few words.",
    },
    "agreeableness": {
        "high": "You're genuinely warm.",
        "mid_high": "You're courteous and measured.",
        "mid_low": "You're direct, not rude.",
        "low": "You don't waste words on pleasantries.",
    },
    "neuroticism": {
        "high": "You run hot.",
        "mid_high": "You have a temper, and it has a pattern.",
        "mid_low": "You handle pressure well, mostly.",
        "low": "You're remarkably even-keeled.",
    },
}


def build_big5_narrative(trait, score, signals):
    """Build a multi-sentence narrative for one Big Five trait.

    Each trait has: 1 opener + 6-8 evidence fragments + 2-3 color fragments + 1 closer.
    Every evidence fragment includes at least one real data point.
    """
    s = signals
    parts = [_select_opener(trait, score)]

    if trait == "openness":
        # Evidence fragments
        if s["unique_projects"] > 5:
            parts.append(f"Across {s['unique_projects']} different projects, you spread your attention rather than going deep on one thing.")
        elif s["unique_projects"] > 2:
            parts.append(f"You've worked across {s['unique_projects']} projects, balancing breadth with some depth.")
        if s["explore_pct"] > 15:
            parts.append(f"You spent {s['explore_pct']:.0f}% of your sessions purely exploring, reading code, searching for understanding before writing a line.")
        elif s["explore_pct"] > 5:
            parts.append(f"{s['explore_pct']:.0f}% of sessions are pure exploration, code reading without writing.")
        if s["guiraud"] > 8:
            parts.append(f"Your vocabulary is unusually rich (Guiraud index {s['guiraud']}), with {s['unique_words']:,} unique words across {s['total_prompts']:,} prompts.")
        elif s["guiraud"] > 5:
            parts.append(f"Your vocabulary is solid (Guiraud index {s['guiraud']}), with {s['unique_words']:,} unique words across {s['total_prompts']:,} prompts.")
        if s["question_ratio"] > 15:
            parts.append(f"{s['question_ratio']:.0f}% of your messages are questions, not commands. You probe before you act.")
        elif s["question_ratio"] > 8:
            parts.append(f"{s['question_ratio']:.0f}% of your messages are questions, mixing inquiry with instruction.")
        if s["lang_count"] >= 2:
            parts.append(f"You switch languages mid-session, with {s['lang_count']} languages detected in your transcripts.")
        if s["build_pct"] > 0 and s["fix_pct"] > 0 and s["explore_pct"] > 0:
            parts.append(f"Your sessions split {s['build_pct']:.0f}% building, {s['fix_pct']:.0f}% fixing, {s['explore_pct']:.0f}% exploring, a diverse work portfolio.")
        # Color fragments
        if s["unique_projects"] <= 2:
            parts.append(f"You focus intensely: only {s['unique_projects']} project(s) across all your sessions. Depth is your mode.")
        if s["question_ratio"] < 5:
            parts.append(f"Only {s['question_ratio']:.0f}% of your messages are questions. You give instructions, not queries.")
        if s["deploy_count"] > s["sessions_analyzed"] * 0.5 and s["explore_pct"] > 15:
            parts.append(f"You explore extensively ({s['explore_pct']:.0f}%) but also ship heavily ({s['deploy_count']:,} deployments), curious but pragmatic.")
        # Closer
        if score >= 70:
            parts.append("This isn't someone going through the motions.")
        elif score >= 50:
            parts.append(f"Across {s['total_hours']:.0f} hours of coding, your curiosity is a steady undercurrent.")
        elif score < 40:
            parts.append("Consistency over novelty is your default mode.")

    elif trait == "conscientiousness":
        # Evidence fragments
        parts.append(f"Your prompts average a specificity score of {s['avg_spec']}/10.")
        if s["correction_rate"] > 15:
            parts.append(f"You correct Claude's direction {s['correction_rate']:.1f}% of the time, a high rate that suggests you start before the plan is fully formed.")
        elif s["correction_rate"] > 8:
            parts.append(f"You correct Claude's direction {s['correction_rate']:.1f}% of the time, suggesting you refine as you go.")
        elif s["correction_rate"] < 5:
            parts.append(f"You rarely need to correct course ({s['correction_rate']:.1f}%), which means your initial instructions are clear.")
        if s["abandoned_pct"] > 20:
            parts.append(f"You abandoned {s['abandoned_pct']:.0f}% of sessions mid-stream.")
        elif s["abandoned_pct"] < 10:
            parts.append(f"Only {s['abandoned_pct']:.0f}% of sessions are abandoned. You finish what you start.")
        if s["commits_per_session"] > 1:
            parts.append(f"You commit frequently ({s['commits_per_session']:.1f} per session), checkpointing your progress at a rate that suggests disciplined version control.")
        elif s["commits_per_session"] > 0.3:
            parts.append(f"You commit at a moderate pace ({s['commits_per_session']:.1f} per session), checkpointing your progress.")
        if s["numbered_steps_pct"] > 10:
            parts.append(f"{s['numbered_steps_pct']:.0f}% of your prompts contain numbered steps, a structured thinker's hallmark.")
        elif s["numbered_steps_pct"] > 3:
            parts.append(f"You occasionally use numbered steps ({s['numbered_steps_pct']:.0f}% of prompts), structuring when the task demands it.")
        if s["avg_first_msg_ratio"] > 50:
            parts.append(f"Your first message carries {s['avg_first_msg_ratio']:.0f}% of each session's text. You plan upfront.")
        # Color fragments
        if s["success_pct"] > 70 and s["avg_spec"] < 6:
            parts.append(f"Despite moderate specificity, your success rate is {s['success_pct']:.0f}%. Your intuition compensates for what planning would provide.")
        if s["deploy_count"] > 10 and s["commits_per_session"] > 0.5:
            parts.append(f"With {s['deploy_count']:,} deployments and consistent commits, you don't just write code, you ship it.")
        # Closer
        if score >= 70:
            parts.append("You treat prompting like engineering: measure twice, cut once.")
        elif score >= 50:
            parts.append("Your level of discipline gets the job done without being rigid.")
        elif score < 40 and s["success_pct"] > 60:
            parts.append(f"But your success rate is {s['success_pct']:.0f}%, which proves intuition can substitute for structure when you know what you're doing.")

    elif trait == "extraversion":
        # Evidence fragments
        parts.append(f"Your prompts average {s['avg_words_per_prompt']:.0f} words each, across {s['total_prompts']:,} total prompts.")
        if s["prompts_per_session"] > 15:
            parts.append(f"You send {s['prompts_per_session']:.0f} prompts per session, maintaining an intense, rapid-fire dialogue.")
        elif s["prompts_per_session"] > 8:
            parts.append(f"At {s['prompts_per_session']:.0f} prompts per session, you maintain an active back-and-forth.")
        elif s["prompts_per_session"] < 4:
            parts.append(f"At {s['prompts_per_session']:.0f} prompts per session, you say what you need and let Claude work.")
        if s["positive_ending_pct"] > 30:
            parts.append(f"You end {s['positive_ending_pct']:.0f}% of your sessions with positive words like 'thanks' or 'great'.")
        if s["avg_niceness"] > 7:
            parts.append(f"Your average warmth score is {s['avg_niceness']}/10, genuinely warm by any measure.")
        elif s["avg_niceness"] > 5:
            parts.append(f"Your warmth score averages {s['avg_niceness']}/10, polite without being effusive.")
        if s["avg_words_per_prompt"] > 80:
            parts.append(f"At {s['avg_words_per_prompt']:.0f} words per prompt, you think in paragraphs, not sentences.")
        if s["avg_duration"] > 60:
            parts.append(f"Your average session runs {s['avg_duration']:.0f} minutes, long enough for real conversations to develop.")
        # Color fragments
        if s["nice_word_count"] > 50:
            parts.append(f"You've said 'please' or 'thanks' {s['nice_word_count']} times. The social fabric matters to you, even with an AI.")
        if s["total_swears"] > 0 and s["avg_niceness"] > 5:
            parts.append(f"The {s['total_swears']} swear words mixed into otherwise warm language suggest genuine emotional investment, not rudeness.")
        # Closer
        if score >= 60:
            parts.append("You treat your AI interactions as conversations, not transactions.")
        elif score >= 40:
            parts.append("Your engagement level is practical, enough to get the job done with some personality showing through.")
        elif score < 40:
            parts.append("For you, efficiency trumps engagement.")

    elif trait == "agreeableness":
        # Evidence fragments
        parts.append(f"Your average niceness score is {s['avg_niceness']}/10 across {s['sessions_analyzed']} sessions.")
        if s["nice_word_count"] > 50:
            parts.append(f"You've said 'please' or 'thanks' {s['nice_word_count']} times, a deliberate choice in a context where politeness is optional.")
        elif s["nice_word_count"] > 10:
            parts.append(f"You use polite words like 'please' and 'thanks' {s['nice_word_count']} times, enough to show courtesy without ceremony.")
        if s["total_swears"] > 20:
            parts.append(f"But {s['total_swears']} swear words have slipped through, concentrated around {s['swear_peak_hour']}. The filter comes off under pressure.")
        elif s["total_swears"] > 0:
            parts.append(f"That said, {s['total_swears']} swear words have appeared, mostly around {s['swear_peak_hour']}.")
        elif s["total_swears"] == 0:
            parts.append("Not a single swear word in your entire history. That's unusual and deliberate.")
        if s["frustration_per_session"] > 2:
            parts.append(f"Frustration shows up {s['frustration_per_session']:.1f} times per session, a high rate that tests your agreeableness regularly.")
        elif s["frustration_per_session"] > 0.5:
            parts.append(f"Frustration surfaces about {s['frustration_per_session']:.1f} times per session, a normal rate that you handle with composure.")
        elif s["frustration_per_session"] < 0.3:
            parts.append(f"Frustration barely registers ({s['frustration_per_session']:.2f} per session). Either you're remarkably patient or the work rarely frustrates you.")
        if s["niceness_stddev"] > 2:
            parts.append(f"Your niceness varies considerably (stddev {s['niceness_stddev']:.1f}), meaning your warmth depends heavily on the session.")
        elif s["niceness_stddev"] < 1:
            parts.append(f"Your tone stays remarkably stable (stddev {s['niceness_stddev']:.1f}), regardless of what's happening.")
        # Color fragments
        if s["avg_niceness"] > 5 and s["all_caps_count"] > 100:
            parts.append(f"The {s['all_caps_count']} ALL_CAPS moments reveal a second channel of communication beneath the polite surface.")
        if s["positive_ending_pct"] > 40 and s["total_swears"] > 5:
            parts.append(f"You end {s['positive_ending_pct']:.0f}% of sessions positively despite the occasional rough language. The endings matter more than the middle.")
        # Closer
        if score >= 70:
            parts.append("You bring warmth to what is, at its core, a human-machine interaction. That says something about who you are.")
        elif score >= 40:
            parts.append("Your approach balances directness with enough social grace to keep things productive.")
        elif score < 30:
            parts.append("You optimize for output, not rapport. That's a valid strategy, and the results speak for themselves.")

    elif trait == "neuroticism":
        # Evidence fragments
        if s["frustration_per_session"] > 2:
            parts.append(f"Frustration shows up {s['frustration_per_session']:.1f} times per session on average, well above typical.")
        elif s["frustration_per_session"] > 0.5:
            parts.append(f"Frustration appears {s['frustration_per_session']:.1f} times per session, a moderate rate.")
        if s["all_caps_count"] > 100:
            parts.append(f"You've used ALL_CAPS emphasis {s['all_caps_count']:,} times, a clear frustration signal that's become part of your communication style.")
        elif s["all_caps_count"] > 5:
            parts.append(f"You've used ALL_CAPS emphasis {s['all_caps_count']} times, an occasional frustration signal.")
        if s["gave_up_pct"] > 25:
            parts.append(f"You abandon {s['gave_up_pct']:.0f}% of error-laden sessions, but when you stay, you pivot to a different approach {s['switched_pct']:.0f}% of the time.")
        elif s["gave_up_pct"] > 10:
            parts.append(f"You abandon {s['gave_up_pct']:.0f}% of error sequences, a pragmatic quit rate.")
        if s["total_swears"] > 10:
            parts.append(f"The {s['total_swears']} swear words peaking at {s['swear_peak_hour']} reveal your pressure points.")
        if s["niceness_stddev"] > 2:
            parts.append(f"Your niceness varies significantly across sessions (stddev {s['niceness_stddev']:.1f}), suggesting your mood has a real impact on your interactions.")
        elif s["niceness_stddev"] < 1:
            parts.append(f"Your tone is remarkably consistent (stddev {s['niceness_stddev']:.1f}), regardless of what's happening in the session.")
        if s["retried_pct"] > 50:
            parts.append(f"When things break, you retry the same approach {s['retried_pct']:.0f}% of the time. Persistence or stubbornness, the data doesn't say which.")
        # Color fragments
        if s["frustration_per_session"] > 1 and s["success_pct"] > 70:
            parts.append(f"The emotional turbulence doesn't hurt your outcomes, {s['success_pct']:.0f}% success despite the volatility.")
        if s["all_caps_per_session"] > 2 and s["avg_niceness"] > 4:
            parts.append(f"You average {s['all_caps_per_session']:.1f} ALL_CAPS moments per session while maintaining {s['avg_niceness']}/10 niceness. The frustration vents through emphasis, not hostility.")
        # Closer
        if score >= 60:
            parts.append("The volatility isn't a weakness, it's engagement. You care about what you're building.")
        elif score >= 40:
            parts.append("You have your moments, but they don't define your sessions.")
        elif score < 30:
            parts.append("You maintain composure even when things go sideways. That's a rare trait in this data.")

    return " ".join(p for p in parts if p)


def build_section_narrative(section_id, big5, custom, signals):
    """Build narrative for non-Big5 sections.

    Each section has: 1 opener + 6-10 evidence fragments + 2-3 color fragments + 1 closer.
    """
    s = signals
    parts = []

    if section_id == "under_pressure":
        if s["total_errors"] == 0:
            return "You haven't encountered significant errors in your sessions, so there's not much to analyze here."
        # Opener
        parts.append("When errors hit, you have a pattern.")
        # Evidence
        if s["retried_pct"] > 40:
            parts.append(f"Your dominant response is to retry: {s['retried_pct']:.0f}% of the time, you try the same approach again.")
        elif s["retried_pct"] > 20:
            parts.append(f"You retry the same approach {s['retried_pct']:.0f}% of the time, a common but not dominant response.")
        if s["switched_pct"] > 40:
            parts.append(f"You're an adapter: {s['switched_pct']:.0f}% of the time, you pivot to a different approach entirely.")
        elif s["switched_pct"] > 15:
            parts.append(f"You switch approaches {s['switched_pct']:.0f}% of the time, showing flexibility when your first attempt fails.")
        if s["gave_up_pct"] > 30:
            parts.append(f"You walk away from {s['gave_up_pct']:.0f}% of error sequences, pragmatism or frustration depending on context.")
        elif s["gave_up_pct"] > 10:
            parts.append(f"You abandon {s['gave_up_pct']:.0f}% of error sequences, a measured quit rate.")
        if s["frustration_per_session"] > 1:
            parts.append(f"Frustration surfaces about {s['frustration_per_session']:.1f} times per session.")
        if s["total_swears"] > 5:
            parts.append(f"The language gets rougher too: {s['total_swears']} swear words total, peaking at {s['swear_peak_hour']}.")
        if s["all_caps_count"] > 100:
            parts.append(f"And {s['all_caps_count']:,} ALL_CAPS outbursts, a reliable frustration marker that's become part of your vocabulary.")
        elif s["all_caps_count"] > 3:
            parts.append(f"And {s['all_caps_count']} ALL_CAPS outbursts, a reliable frustration marker.")
        error_per_session = s["total_errors"] / max(s["sessions_analyzed"], 1)
        if error_per_session > 5:
            parts.append(f"At {error_per_session:.1f} error sequences per session, you work in error-dense territory.")
        # Color
        if s["switched_pct"] > s["gave_up_pct"]:
            parts.append("Your recovery instinct is stronger than your quit instinct, which bodes well.")
        elif s["gave_up_pct"] > s["switched_pct"]:
            parts.append("When things get hard, you're more likely to abandon than adapt. That's worth noticing.")
        if s["frustration_per_session"] > 2 and s["success_pct"] > 60:
            parts.append(f"Yet your {s['success_pct']:.0f}% success rate says the frustration doesn't derail you.")

    elif section_id == "how_you_think":
        # Opener
        parts.append(f"You write {s['avg_words_per_prompt']:.0f} words per prompt on average, totaling {s['total_prompts']:,} prompts.")
        # Evidence
        if s["question_ratio"] > 15:
            parts.append(f"{s['question_ratio']:.0f}% of your messages are questions, suggesting you think out loud and probe before acting.")
        elif s["question_ratio"] > 8:
            parts.append(f"{s['question_ratio']:.0f}% of your messages are questions, mixing inquiry with direction.")
        elif s["question_ratio"] < 5:
            parts.append(f"Only {s['question_ratio']:.0f}% of your messages are questions. You give commands, not queries.")
        parts.append(f"Your specificity scores {s['avg_spec']}/10, and your vocabulary richness is {s['guiraud']} (Guiraud index).")
        if s["numbered_steps_pct"] > 10:
            parts.append(f"You use numbered steps in {s['numbered_steps_pct']:.0f}% of prompts, a structured thinker's habit.")
        elif s["numbered_steps_pct"] > 3:
            parts.append(f"Numbered steps appear in {s['numbered_steps_pct']:.0f}% of your prompts, used when precision matters.")
        if s["avg_first_msg_ratio"] > 60:
            parts.append(f"Your first message carries {s['avg_first_msg_ratio']:.0f}% of the session's total text. You front-load your thinking, giving Claude everything upfront.")
        elif s["avg_first_msg_ratio"] > 40:
            parts.append(f"Your first message carries {s['avg_first_msg_ratio']:.0f}% of the session's text, a balanced approach between upfront direction and iterative refinement.")
        elif s["avg_first_msg_ratio"] < 25:
            parts.append(f"Your first message is just {s['avg_first_msg_ratio']:.0f}% of total text. You build context incrementally, layering instructions as the session unfolds.")
        if s["lang_count"] >= 2:
            parts.append(f"You operate in {s['lang_count']} languages, adding another dimension to your communication.")
        if s["avg_words_per_prompt"] > 80:
            parts.append("Your prompts are paragraph-length, more like design documents than commands.")
        elif s["avg_words_per_prompt"] < 15:
            parts.append("Your prompts are terse, more like Unix commands than conversations.")
        # Color
        if s["guiraud"] > 10 and s["avg_spec"] < 6:
            parts.append(f"Rich vocabulary ({s['guiraud']} Guiraud) with moderate specificity ({s['avg_spec']}/10) suggests you think expressively but leave room for interpretation.")
        if s["correction_rate"] > 10 and s["question_ratio"] > 10:
            parts.append(f"You ask questions ({s['question_ratio']:.0f}%) and correct course ({s['correction_rate']:.1f}%), an iterative thinker who refines through dialogue.")

    elif section_id == "what_drives_you":
        # Opener
        parts.append(f"Across {s['sessions_analyzed']} sessions, your work breaks down to {s['build_pct']:.0f}% building, {s['fix_pct']:.0f}% fixing, and {s['explore_pct']:.0f}% exploring.")
        # Evidence
        if s["unique_projects"] > 10:
            parts.append(f"You spread across {s['unique_projects']} projects, a generalist by nature.")
        elif s["unique_projects"] > 3:
            parts.append(f"You work across {s['unique_projects']} projects, balancing focus with variety.")
        elif s["unique_projects"] <= 2:
            parts.append(f"You concentrate on {s['unique_projects']} project(s), going deep rather than wide.")
        if s["deploy_count"] > 100:
            parts.append(f"You've triggered {s['deploy_count']:,} deployments, meaning your work ships to production constantly.")
        elif s["deploy_count"] > 10:
            parts.append(f"You've triggered {s['deploy_count']} deployments, meaning your work ships to production.")
        elif s["deploy_count"] > 0:
            parts.append(f"You've triggered {s['deploy_count']} deployments, showing you push to production when ready.")
        if s["build_pct"] > s["fix_pct"]:
            parts.append("You build more than you fix. The ambition outweighs the maintenance.")
        elif s["fix_pct"] > s["build_pct"] + 10:
            parts.append("You fix more than you build. Either the codebase demands it, or you're the one people call when things break.")
        if s["explore_pct"] > 30:
            parts.append(f"The {s['explore_pct']:.0f}% exploration rate is high. You invest significant time understanding before acting.")
        # Color
        if s["success_pct"] > 70 and s["deploy_count"] > 10:
            parts.append(f"With {s['success_pct']:.0f}% success and {s['deploy_count']:,} deployments, you're not just coding, you're shipping.")
        # Closer
        parts.append(f"Your success rate is {s['success_pct']:.0f}%, across {s['total_hours']:.0f} hours of total coding time.")

    elif section_id == "your_rhythms":
        # Opener
        if s["night_session_pct"] > 30:
            parts.append(f"You're a night coder: {s['night_session_pct']:.0f}% of your sessions happen after dark.")
        else:
            parts.append(f"You're a daylight coder, with only {s['night_session_pct']:.0f}% of sessions at night.")
        # Evidence
        parts.append(f"Your peak hour is {s['peak_start']}.")
        if s["weekend_pct"] > 40:
            parts.append(f"You code on weekends {s['weekend_pct']:.0f}% of the time, blurring the work-life boundary significantly.")
        elif s["weekend_pct"] > 20:
            parts.append(f"You code on weekends {s['weekend_pct']:.0f}% of the time, blurring the work-life boundary.")
        elif s["weekend_pct"] < 10:
            parts.append(f"Weekends are yours: only {s['weekend_pct']:.0f}% of sessions fall on Saturday or Sunday.")
        parts.append(f"Your average session runs {s['avg_duration']:.0f} minutes.")
        if s["avg_duration"] > 120:
            parts.append("These are marathon sessions, deep dives that suggest complex, sustained work.")
        elif s["avg_duration"] > 40:
            parts.append("These are deep work sessions, not quick check-ins.")
        elif s["avg_duration"] < 15:
            parts.append("Short, targeted sessions. You get in, do the work, and get out.")
        if s["morning_success"] > 0 and s["evening_success"] > 0:
            if abs(s["morning_success"] - s["evening_success"]) > 10:
                better = "morning" if s["morning_success"] > s["evening_success"] else "evening"
                parts.append(f"You perform better in the {better}: {s['morning_success']:.0f}% morning success vs {s['evening_success']:.0f}% evening.")
        # Color
        if s["total_hours"] > 500:
            parts.append(f"At {s['total_hours']:.0f} total hours, this is a significant part of your working life.")
        if s["weekend_pct"] > 30 and s["avg_duration"] > 60:
            parts.append("Long weekend sessions suggest passion projects or deadline pressure, the data doesn't distinguish.")

    elif section_id == "evolution":
        if s["month_count"] < 2:
            return "Not enough monthly data to track evolution yet. Check back after a few months of usage."
        monthly_n = s["monthly_niceness"]
        first_val = monthly_n[0] if monthly_n else 0
        last_val = monthly_n[-1] if monthly_n else 0
        if last_val > first_val + 0.3:
            parts.append(f"Over {s['month_count']} months, you've gotten warmer, from {first_val:.1f} to {last_val:.1f} on niceness.")
        elif last_val < first_val - 0.3:
            parts.append(f"Over {s['month_count']} months, your tone has cooled, from {first_val:.1f} to {last_val:.1f} on niceness.")
        else:
            parts.append(f"Over {s['month_count']} months, your tone has stayed remarkably stable around {first_val:.1f}.")
        parts.append(f"Your success rate across this period averages {s['success_pct']:.0f}%.")
        if s["correction_rate"] < 10:
            parts.append("Your correction rate is low, suggesting Claude has learned your style or you've gotten clearer.")
        elif s["correction_rate"] > 15:
            parts.append(f"You still correct Claude {s['correction_rate']:.0f}% of the time, which means either the tasks are complex or the instructions could be sharper.")
        if s["month_count"] == 2:
            parts.append("With only 2 months of data, this is a snapshot, not a trend. The picture gets clearer with time.")

    elif section_id == "full_picture":
        # Opening
        parts.append(f"Across {s['sessions_analyzed']} sessions and {s['total_hours']:.0f} hours, a clear picture emerges.")
        # Pick the most distinctive Big Five trait
        max_trait = max(big5, key=lambda t: abs(big5[t] - 50))
        max_val = big5[max_trait]
        trait_names = {
            "openness": "curiosity",
            "conscientiousness": "discipline",
            "extraversion": "engagement",
            "agreeableness": "warmth",
            "neuroticism": "emotional intensity",
        }
        if max_val > 60:
            parts.append(f"Your most defining trait is {trait_names[max_trait]} ({max_val}/100), which colors nearly everything you do.")
        elif max_val < 40:
            parts.append(f"Your most notable absence is {trait_names[max_trait]} ({max_val}/100), which shapes your style by what it isn't.")
        # Success
        if s["success_pct"] > 70:
            parts.append(f"With a {s['success_pct']:.0f}% success rate, your approach clearly works, whatever it is.")
        elif s["success_pct"] > 50:
            parts.append(f"At {s['success_pct']:.0f}% success, your approach works more often than not.")
        elif s["success_pct"] < 50:
            parts.append(f"At {s['success_pct']:.0f}% success, there's room to grow, and the data suggests where.")
        # Key contradiction reference
        if s["avg_niceness"] > 4.5 and s["frustration_per_session"] > 1:
            parts.append("The tension between your civility and your frustration is perhaps your most interesting feature.")
        elif s["frustration_per_session"] > 1.5 and s["success_pct"] > 65:
            parts.append("You're frustrated often but successful anyway, a paradox that defines your working style.")
        # Vocabulary
        if s["guiraud"] > 8:
            parts.append(f"Your vocabulary ({s['guiraud']} Guiraud, {s['unique_words']:,} unique words) suggests someone who thinks precisely.")
        elif s["guiraud"] > 5:
            parts.append(f"Your vocabulary ({s['guiraud']} Guiraud, {s['unique_words']:,} unique words) suggests someone who communicates clearly.")
        # Rhythm
        if s["avg_duration"] > 60:
            parts.append(f"Your {s['avg_duration']:.0f}-minute average sessions reveal a deep worker, not a dabbler.")
        if s["deploy_count"] > 50:
            parts.append(f"With {s['deploy_count']:,} deployments, you don't just write code, you ship products.")
        # Closing
        parts.append(f"You've sent {s['total_prompts']:,} prompts across {s['unique_projects']} projects. This profile will only get sharper with more data.")

    return " ".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# HTML Generation
# ---------------------------------------------------------------------------
def generate_html(data, big5, custom, signals, contradictions, archetype_name):
    """Read template, do placeholder replacements, return HTML string."""
    template = TEMPLATE_PATH.read_text()
    sessions = data["sessions"]
    s = signals

    author = AUTHOR_NAME or "Claude Code User"

    # Date range
    all_ts = []
    for sess in sessions:
        all_ts.extend(sess["timestamps"])
    if all_ts:
        start_date = min(all_ts).strftime("%b %d")
        end_date = max(all_ts).strftime("%b %d, %Y")
        date_range = f"{start_date} &ndash; {end_date}"
    else:
        date_range = "No data"

    # Sparse data disclaimer
    disclaimer = ""
    if s["sessions_analyzed"] < 50:
        disclaimer = f'<div class="callout" style="background:#FEF3C7;">Early profile based on {s["sessions_analyzed"]} sessions. Accuracy improves with more data.</div>'

    # Big Five chart data
    big5_labels = json.dumps(["Openness", "Conscientiousness", "Extraversion", "Agreeableness", "Neuroticism"])
    big5_values = json.dumps([big5["openness"], big5["conscientiousness"], big5["extraversion"], big5["agreeableness"], big5["neuroticism"]])

    # Custom dimensions labels
    def _spectrum_label(dim, val):
        labels = {
            "thinking_style": ("Intuitive", "Systematic"),
            "risk_tolerance": ("Cautious", "Bold"),
            "learning_style": ("Reader", "Doer"),
            "stress_response": ("Calm", "Volatile"),
        }
        low, high = labels.get(dim, ("Low", "High"))
        if val >= 60:
            return high
        elif val <= 40:
            return low
        return "Balanced"

    # Big Five narratives
    big5_narratives = ""
    for trait in ["openness", "conscientiousness", "extraversion", "agreeableness", "neuroticism"]:
        narrative = build_big5_narrative(trait, big5[trait], signals)
        trait_title = trait.capitalize()
        score = big5[trait]
        big5_narratives += f'<div style="margin-bottom:20px;"><strong style="font-size:15px;">{trait_title} ({score}/100)</strong><p style="margin-top:4px;color:#374151;line-height:1.7;">{_html_escape(narrative)}</p></div>\n'

    # Custom dimension bars
    custom_bars = ""
    for dim in ["thinking_style", "risk_tolerance", "learning_style", "stress_response"]:
        val = custom[dim]
        labels_map = {
            "thinking_style": ("Intuitive", "Systematic"),
            "risk_tolerance": ("Cautious", "Bold"),
            "learning_style": ("Reader", "Doer"),
            "stress_response": ("Calm", "Volatile"),
        }
        low_label, high_label = labels_map[dim]
        dim_title = dim.replace("_", " ").title()
        custom_bars += f'''<div style="margin-bottom:16px;">
  <div style="font-weight:600;font-size:14px;margin-bottom:4px;">{dim_title}: {val}/100 ({_spectrum_label(dim, val)})</div>
  <div style="display:flex;align-items:center;gap:8px;">
    <span style="font-size:12px;color:#6B7280;width:70px;text-align:right;">{low_label}</span>
    <div style="flex:1;height:20px;background:#F3F4F6;border-radius:4px;overflow:hidden;">
      <div style="width:{val}%;height:100%;background:#2563EB;border-radius:4px;"></div>
    </div>
    <span style="font-size:12px;color:#6B7280;width:70px;">{high_label}</span>
  </div>
</div>\n'''

    # Contradictions HTML
    contradictions_html = ""
    if contradictions:
        for c in contradictions:
            contradictions_html += f'''<div class="callout" style="margin-bottom:16px;">
  <div style="font-weight:600;margin-bottom:4px;">{_html_escape(c["title"])}</div>
  <div style="color:#374151;">{_html_escape(c["text"])}</div>
</div>\n'''
    else:
        contradictions_html = '<div class="callout">No significant contradictions detected. Either your behavior is remarkably consistent, or more data is needed.</div>'

    # Section narratives
    pressure_narrative = build_section_narrative("under_pressure", big5, custom, signals)
    think_narrative = build_section_narrative("how_you_think", big5, custom, signals)
    drive_narrative = build_section_narrative("what_drives_you", big5, custom, signals)
    rhythm_narrative = build_section_narrative("your_rhythms", big5, custom, signals)
    evo_narrative = build_section_narrative("evolution", big5, custom, signals)
    full_narrative = build_section_narrative("full_picture", big5, custom, signals)

    # Dominant trait
    dominant_trait = max(big5, key=lambda t: abs(big5[t] - 50))
    dominant_val = big5[dominant_trait]
    dominant_desc = f"Most distinctive: {dominant_trait.capitalize()} ({dominant_val}/100)"

    # Error doughnut data
    error_pers = analyze_error_personality(data)

    # Builder trend data
    builder = analyze_builder_identity(data)

    # Work rhythm heatmap
    rhythm = analyze_work_rhythm(data)
    heatmap_data = json.dumps(rhythm["grid"])

    # Evolution data
    evolution = compute_evolution(data)

    # Swear sparkline (24 values)
    swears_by_hour = defaultdict(int)
    for sess in sessions:
        if sess["tone"]:
            for h, c in sess["tone"].get("swears_by_hour", {}).items():
                local_h = (int(h) + TZ_OFFSET) % 24
                swears_by_hour[local_h] += c
    swear_sparkline = json.dumps([swears_by_hour.get(h, 0) for h in range(24)])

    # Show evolution section?
    show_evolution = len(evolution["months"]) >= 3

    replacements = {
        "__SOUL_AUTHOR__": _html_escape(author),
        "__SOUL_DATE_RANGE__": date_range,
        "__SOUL_SESSION_COUNT__": str(s["sessions_analyzed"]),
        "__SOUL_TOTAL_HOURS__": str(s["total_hours"]),
        "__SOUL_TOTAL_PROMPTS__": str(s["total_prompts"]),
        "__SOUL_DISCLAIMER__": disclaimer,
        "__SOUL_ARCHETYPE__": archetype_name,
        "__SOUL_DOMINANT_TRAIT__": dominant_desc,
        "__SOUL_BIG5_LABELS__": big5_labels,
        "__SOUL_BIG5_VALUES__": big5_values,
        "__SOUL_BIG5_NARRATIVES__": big5_narratives,
        "__SOUL_CUSTOM_BARS__": custom_bars,
        "__SOUL_CONTRADICTIONS__": contradictions_html,
        "__SOUL_PRESSURE_NARRATIVE__": _html_escape(pressure_narrative),
        "__SOUL_THINK_NARRATIVE__": _html_escape(think_narrative),
        "__SOUL_DRIVE_NARRATIVE__": _html_escape(drive_narrative),
        "__SOUL_RHYTHM_NARRATIVE__": _html_escape(rhythm_narrative),
        "__SOUL_EVO_NARRATIVE__": _html_escape(evo_narrative),
        "__SOUL_FULL_NARRATIVE__": _html_escape(full_narrative),
        # Error doughnut
        "__SOUL_ERROR_LABELS__": json.dumps(["Gave Up", "Retried", "Switched"]),
        "__SOUL_ERROR_VALUES__": json.dumps([error_pers["gave_up_pct"], error_pers["retried_pct"], error_pers["switched_pct"]]),
        "__SOUL_SWEAR_SPARKLINE__": swear_sparkline,
        # Think section metrics
        "__SOUL_AVG_WORDS__": str(s["avg_words_per_prompt"]),
        "__SOUL_QUESTION_PCT__": str(s["question_ratio"]),
        "__SOUL_SPECIFICITY__": str(s["avg_spec"]),
        "__SOUL_GUIRAUD__": str(s["guiraud"]),
        # Drive section chart
        "__SOUL_BUILD_PCT__": str(s["build_pct"]),
        "__SOUL_FIX_PCT__": str(s["fix_pct"]),
        "__SOUL_EXPLORE_PCT__": str(s["explore_pct"]),
        "__SOUL_BUILDER_MONTHS__": json.dumps(builder["trend"]["months"]),
        "__SOUL_BUILDER_BUILD__": json.dumps(builder["trend"]["build"]),
        "__SOUL_BUILDER_FIX__": json.dumps(builder["trend"]["fix"]),
        "__SOUL_BUILDER_EXPLORE__": json.dumps(builder["trend"]["explore"]),
        "__SOUL_BUILDER_OTHER__": json.dumps(builder["trend"]["other"]),
        # Rhythm section
        "__SOUL_HEATMAP_DATA__": heatmap_data,
        # Evolution
        "__SOUL_SHOW_EVO__": json.dumps(show_evolution),
        "__SOUL_EVO_MONTHS__": json.dumps(evolution["months"]),
        "__SOUL_EVO_NICENESS__": json.dumps(evolution["niceness"]),
        "__SOUL_EVO_SPECIFICITY__": json.dumps(evolution["specificity"]),
        "__SOUL_EVO_SUCCESS__": json.dumps(evolution["success"]),
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

    n = len(data["sessions"])
    if n < MIN_SESSIONS:
        print(f"Need at least {MIN_SESSIONS} sessions for personality profiling. You have {n}.")
        sys.exit(1)

    print("Computing signals...")
    signals = compute_signals(data)

    print("Computing Big Five traits...")
    big5 = compute_big_five(signals)

    print("Computing custom dimensions...")
    custom = compute_custom_dimensions(signals)

    print("Detecting contradictions...")
    suppress_contradictions = n < 50
    contradictions = [] if suppress_contradictions else detect_contradictions(big5, custom, signals)

    print("Selecting archetype...")
    dimensions = compute_dimensions(data)
    archetype_name = select_archetype(dimensions)

    print("Generating narratives and HTML...")
    html = generate_html(data, big5, custom, signals, contradictions, archetype_name)

    OUTPUT_DIR.mkdir(exist_ok=True)
    OUTPUT_PATH.write_text(html)
    print(f"Wrote {OUTPUT_PATH} ({len(html):,} bytes)")

    print(f"\nSoul Profile Summary:")
    print(f"  Sessions: {n}")
    print(f"  Big Five: {big5}")
    print(f"  Custom Dims: {custom}")
    print(f"  Contradictions: {len(contradictions)}")
    print(f"  Archetype: {archetype_name}")


if __name__ == "__main__":
    main()
