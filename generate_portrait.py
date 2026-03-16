#!/usr/bin/env python3
"""
Generate a self-contained portrait.html - "How AI Sees You".

A personal character study written as long-form prose in second person.
Reads like a letter from someone who's watched you work for 1,400 hours.
Minimal charts, mostly narrative prose. Every claim backed by data.

Outputs dist/portrait.html.
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
    analyze_communication_style,
    analyze_work_rhythm,
    compute_dimensions,
    _hour_label,
    _html_escape,
    TZ_OFFSET,
    SANITIZE,
    AUTHOR_NAME,
)

TEMPLATE_PATH = SCRIPT_DIR / "portrait.html"
OUTPUT_DIR = SCRIPT_DIR / "dist"
OUTPUT_PATH = OUTPUT_DIR / "portrait.html"

MIN_SESSIONS = 20


# ---------------------------------------------------------------------------
# Signal Mining
# ---------------------------------------------------------------------------
def mine_signals(data):
    """Extract every signal needed for the portrait narrative."""
    sessions = data["sessions"]
    all_texts = data["all_user_texts"]
    n = len(sessions)
    if n == 0:
        return {}

    total_prompts = sum(len(s["prompts"]) for s in sessions)

    # Durations
    durations = [s["duration_min"] for s in sessions if s["duration_min"] > 0]
    total_hours = sum(durations) / 60 if durations else 0
    avg_duration = statistics.mean(durations) if durations else 0

    # Niceness
    niceness_scores = [s["tone"]["niceness_score"] for s in sessions if s["tone"]]
    avg_niceness = statistics.mean(niceness_scores) if niceness_scores else 5.0
    niceness_stddev = statistics.stdev(niceness_scores) if len(niceness_scores) > 1 else 0

    # Niceness range
    min_niceness = min(niceness_scores) if niceness_scores else 0
    max_niceness = max(niceness_scores) if niceness_scores else 10

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

    # ALL_CAPS
    all_caps_count = 0
    for s in sessions:
        for p in s["prompts"]:
            if p["frustration"]:
                caps_val = p["frustration"].get("all_caps_words", [])
                all_caps_count += len(caps_val) if isinstance(caps_val, list) else int(caps_val)

    # Questions
    question_count = sum(1 for t in all_texts if t.strip().endswith("?"))
    question_ratio = question_count / max(len(all_texts), 1) * 100

    # Numbered steps
    numbered_steps_count = 0
    for s in sessions:
        for p in s["prompts"]:
            if re.search(r"^\s*\d+[\.\)]\s", p["text"], re.MULTILINE):
                numbered_steps_count += 1
    numbered_steps_pct = numbered_steps_count / max(total_prompts, 1) * 100

    # Projects - filter out catch-all buckets that aren't real projects
    GENERIC_PROJECTS = {"AX41 General", "Mac General", "General", "Unknown", "unknown"}
    project_counts = Counter(s["project"] for s in sessions)
    unique_projects = len(project_counts)
    # Top projects excludes generic catch-alls
    meaningful_projects = {k: v for k, v in project_counts.items() if k not in GENERIC_PROJECTS}
    top_projects = Counter(meaningful_projects).most_common(5)
    generic_session_count = sum(project_counts.get(g, 0) for g in GENERIC_PROJECTS)
    generic_session_pct = generic_session_count / n * 100

    # Category breakdown
    cat_counts = Counter(s["category"] for s in sessions)
    build_pct = cat_counts.get("BUILD", 0) / n * 100
    fix_pct = cat_counts.get("FIX", 0) / n * 100
    explore_pct = cat_counts.get("EXPLORE", 0) / n * 100
    mixed_pct = cat_counts.get("MIXED", 0) / n * 100
    deploy_pct = cat_counts.get("DEPLOY", 0) / n * 100
    dominant_category = cat_counts.most_common(1)[0][0] if cat_counts else "BUILD"

    # Success
    success_count = sum(1 for s in sessions if s["outcome"] in ("SUCCESS", "PARTIAL_SUCCESS"))
    success_pct = success_count / n * 100

    # Abandoned
    abandoned_pct = sum(1 for s in sessions if s["abandoned"]) / n * 100

    # Corrections
    correction_total = sum(s["correction_count"] for s in sessions)
    correction_rate = correction_total / max(total_prompts, 1) * 100

    # Commits / Deploys
    total_commits = sum(s["commits"] for s in sessions)
    deploy_count = sum(s["deployments"] for s in sessions)

    # Prompts
    all_wc = [p["word_count"] for s in sessions for p in s["prompts"]]
    avg_words_per_prompt = statistics.mean(all_wc) if all_wc else 20
    prompts_per_session = total_prompts / n

    # Specificity
    all_specs = [p["specificity"] for s in sessions for p in s["prompts"]]
    avg_spec = statistics.mean(all_specs) if all_specs else 5.0

    # Vocabulary
    word_counter = data["word_counter"]
    total_words_vocab = sum(word_counter.values())
    unique_words = len(word_counter)
    guiraud = unique_words / math.sqrt(total_words_vocab) if total_words_vocab > 0 else 0

    # Please / thanks
    please_count = word_counter.get("please", 0)
    thanks_count = word_counter.get("thanks", 0) + word_counter.get("thank", 0)
    nice_word_count = please_count + thanks_count

    # Swears
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

    # Positive endings
    positive_endings = 0
    for s in sessions:
        if s["prompts"]:
            last_text = s["prompts"][-1]["text"].lower()
            if any(w in last_text for w in ["thanks", "thank", "great", "perfect", "awesome", "nice", "good"]):
                positive_endings += 1
    positive_ending_pct = positive_endings / n * 100

    # Hour patterns
    hour_counts = data["hour_counts"]
    total_timed = sum(hour_counts.values()) if hour_counts else 1
    night_sessions = sum(hour_counts.get(h, 0) for h in [22, 23, 0, 1, 2, 3, 4, 5])
    morning_sessions = sum(hour_counts.get(h, 0) for h in [6, 7, 8, 9, 10, 11])
    afternoon_sessions = sum(hour_counts.get(h, 0) for h in [12, 13, 14, 15, 16, 17])
    night_session_pct = night_sessions / max(total_timed, 1) * 100
    morning_session_pct = morning_sessions / max(total_timed, 1) * 100
    afternoon_session_pct = afternoon_sessions / max(total_timed, 1) * 100
    peak_hours = sorted(hour_counts, key=hour_counts.get, reverse=True)[:3] if hour_counts else [12]
    peak_start = _hour_label(peak_hours[0]) if peak_hours else "12pm"

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
    languages = comm["languages"]
    lang_count = len(languages)

    # First message ratio
    first_msg_ratios = []
    for s in sessions:
        if s["prompts"]:
            first_wc = s["prompts"][0]["word_count"]
            total_wc = sum(p["word_count"] for p in s["prompts"])
            if total_wc > 0:
                first_msg_ratios.append(first_wc / total_wc * 100)
    avg_first_msg_ratio = statistics.mean(first_msg_ratios) if first_msg_ratios else 50

    # Monthly niceness trend
    monthly = data["monthly_data"]
    months_sorted = sorted(monthly.keys())
    monthly_niceness = []
    for m in months_sorted:
        d = monthly[m]
        monthly_niceness.append(statistics.mean(d["niceness"]) if d["niceness"] else 0)

    # Top words (excluding code-like terms)
    top_words = [w for w, _ in word_counter.most_common(30)
                 if len(w) > 3 and w not in {"this", "that", "with", "from", "have",
                                              "will", "your", "what", "when", "make",
                                              "like", "just", "also", "need", "should",
                                              "would", "could", "they", "them", "then",
                                              "than", "been", "were", "does", "done",
                                              "only", "more", "some", "into", "each",
                                              "here", "there", "about", "which", "their",
                                              "other", "after", "before", "these", "those",
                                              "first", "file", "code", "want", "sure",
                                              "don't", "it's", "i'll"}][:10]

    # Goal language detection ("want to", "trying to", "need to")
    goal_phrases = {"want to": 0, "trying to": 0, "need to": 0, "going to": 0, "have to": 0}
    for t in all_texts:
        lower = t.lower()
        for phrase in goal_phrases:
            goal_phrases[phrase] += lower.count(phrase)
    dominant_goal_phrase = max(goal_phrases, key=goal_phrases.get) if any(goal_phrases.values()) else "want to"
    total_goal_phrases = sum(goal_phrases.values())

    # Vocabulary under stress
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

    # Session length consistency
    if len(durations) > 1:
        duration_cv = statistics.stdev(durations) / statistics.mean(durations) if statistics.mean(durations) > 0 else 0
    else:
        duration_cv = 0

    # Streak: longest run of consecutive days
    session_dates = set()
    for s in sessions:
        if s["timestamps"]:
            dt = min(s["timestamps"])
            session_dates.add(dt.date())
    sorted_dates = sorted(session_dates)
    max_streak = 0
    current_streak = 1
    for i in range(1, len(sorted_dates)):
        if (sorted_dates[i] - sorted_dates[i - 1]).days == 1:
            current_streak += 1
        else:
            max_streak = max(max_streak, current_streak)
            current_streak = 1
    max_streak = max(max_streak, current_streak) if sorted_dates else 0

    # Date range
    all_ts = []
    for s in sessions:
        all_ts.extend(s["timestamps"])

    return {
        "sessions_analyzed": n,
        "total_prompts": total_prompts,
        "total_hours": round(total_hours, 1),
        "avg_duration": round(avg_duration, 1),
        "avg_niceness": round(avg_niceness, 1),
        "niceness_stddev": round(niceness_stddev, 2),
        "min_niceness": round(min_niceness, 1),
        "max_niceness": round(max_niceness, 1),
        "gave_up_pct": round(gave_up_pct, 1),
        "switched_pct": round(switched_pct, 1),
        "retried_pct": round(retried_pct, 1),
        "total_errors": total_errors,
        "frustration_count": frustration_count,
        "frustration_per_session": round(frustration_per_session, 2),
        "all_caps_count": all_caps_count,
        "question_ratio": round(question_ratio, 1),
        "numbered_steps_pct": round(numbered_steps_pct, 1),
        "unique_projects": unique_projects,
        "top_projects": top_projects,
        "build_pct": round(build_pct, 1),
        "fix_pct": round(fix_pct, 1),
        "explore_pct": round(explore_pct, 1),
        "mixed_pct": round(mixed_pct, 1),
        "deploy_pct": round(deploy_pct, 1),
        "dominant_category": dominant_category,
        "generic_session_pct": round(generic_session_pct, 1),
        "success_pct": round(success_pct, 1),
        "abandoned_pct": round(abandoned_pct, 1),
        "correction_rate": round(correction_rate, 1),
        "correction_total": correction_total,
        "total_commits": total_commits,
        "deploy_count": deploy_count,
        "avg_words_per_prompt": round(avg_words_per_prompt, 1),
        "prompts_per_session": round(prompts_per_session, 1),
        "avg_spec": round(avg_spec, 1),
        "guiraud": round(guiraud, 1),
        "unique_words": unique_words,
        "nice_word_count": nice_word_count,
        "please_count": please_count,
        "thanks_count": thanks_count,
        "total_swears": total_swears,
        "swear_rate": round(swear_rate, 2),
        "swear_peak_hour": _hour_label(swear_peak_hour),
        "positive_ending_pct": round(positive_ending_pct, 1),
        "night_session_pct": round(night_session_pct, 1),
        "morning_session_pct": round(morning_session_pct, 1),
        "afternoon_session_pct": round(afternoon_session_pct, 1),
        "peak_start": peak_start,
        "weekend_pct": round(weekend_pct, 1),
        "morning_success": round(morning_success, 1),
        "evening_success": round(evening_success, 1),
        "lang_count": lang_count,
        "languages": languages,
        "avg_first_msg_ratio": round(avg_first_msg_ratio, 1),
        "monthly_niceness": monthly_niceness,
        "months_sorted": months_sorted,
        "month_count": len(months_sorted),
        "top_words": top_words,
        "goal_phrases": goal_phrases,
        "dominant_goal_phrase": dominant_goal_phrase,
        "total_goal_phrases": total_goal_phrases,
        "guiraud_frustrated": round(guiraud_frustrated, 1),
        "guiraud_calm": round(guiraud_calm, 1),
        "duration_cv": round(duration_cv, 2),
        "max_streak": max_streak,
        "all_timestamps": all_ts,
        "swear_words_counter": swear_words_counter,
    }


# ---------------------------------------------------------------------------
# Narrative Builders - one per section
# ---------------------------------------------------------------------------
def _proj_list(top_projects, limit=5):
    """Format top projects as a readable list."""
    parts = []
    for name, count in top_projects[:limit]:
        if SANITIZE:
            name = f"Project {len(parts) + 1}"
        parts.append(f"{name} ({count} sessions)")
    return ", ".join(parts)


def build_first_impression(s):
    """Section 1: Opening paragraph - what stands out immediately."""
    parts = []

    # Lead with the most distinctive signal
    if s["total_hours"] > 500:
        parts.append(f"The first thing that stands out is the sheer volume: {s['total_hours']:.0f} hours across {s['sessions_analyzed']} sessions.")
    elif s["total_hours"] > 100:
        parts.append(f"You've spent {s['total_hours']:.0f} hours across {s['sessions_analyzed']} sessions, enough time for patterns to emerge clearly.")
    else:
        parts.append(f"Across {s['sessions_analyzed']} sessions and {s['total_hours']:.0f} hours, your working style is already taking shape.")

    # Most striking personality signal
    if s["avg_niceness"] > 7.5:
        parts.append(f"You're unusually polite for someone talking to a machine, averaging {s['avg_niceness']}/10 on warmth with {s['nice_word_count']} instances of 'please' and 'thanks'.")
    elif s["avg_niceness"] < 3:
        parts.append(f"You don't waste words on pleasantries. Your niceness score averages {s['avg_niceness']}/10, and that's not criticism, it's efficiency.")
    elif s["frustration_per_session"] > 2:
        parts.append(f"You run hot. Frustration surfaces {s['frustration_per_session']:.1f} times per session on average, with {s['all_caps_count']} ALL_CAPS outbursts across your history.")
    elif s["avg_words_per_prompt"] > 80:
        parts.append(f"You think in paragraphs: {s['avg_words_per_prompt']:.0f} words per prompt on average, across {s['total_prompts']:,} total prompts. You give context, not commands.")
    elif s["avg_words_per_prompt"] < 12:
        parts.append(f"You're terse: {s['avg_words_per_prompt']:.0f} words per prompt on average. You say what you need and nothing more.")
    else:
        parts.append(f"Your prompts average {s['avg_words_per_prompt']:.0f} words each, {s['total_prompts']:,} of them total, a steady working rhythm.")

    # Work style characterization
    if s["mixed_pct"] > 30:
        parts.append(f"Most of your sessions ({s['mixed_pct']:.0f}%) are mixed-mode: building, fixing, and exploring in the same sitting. You don't compartmentalize your work.")
    elif s["explore_pct"] > s["build_pct"] + 15:
        parts.append(f"You spend more time exploring ({s['explore_pct']:.0f}%) than building ({s['build_pct']:.0f}%). Understanding comes before action.")
    elif s["build_pct"] > s["fix_pct"] + 20:
        parts.append(f"You're a builder at heart: {s['build_pct']:.0f}% of your sessions create something new.")
    elif s["fix_pct"] > s["build_pct"] + 20:
        parts.append(f"You spend more time fixing than building ({s['fix_pct']:.0f}% vs {s['build_pct']:.0f}%), a pattern that says something about your relationship with existing code.")
    else:
        parts.append(f"Your sessions split across building ({s['build_pct']:.0f}%), fixing ({s['fix_pct']:.0f}%), and exploring ({s['explore_pct']:.0f}%).")

    # Success rate quick hit
    if s["success_pct"] > 80:
        parts.append(f"And it works: {s['success_pct']:.0f}% success rate.")
    elif s["success_pct"] > 60:
        parts.append(f"Your success rate of {s['success_pct']:.0f}% says the approach is sound, if imperfect.")

    return " ".join(parts)


def build_what_you_care_about(s):
    """Section 2: What domains and projects draw your energy."""
    parts = []

    if s["unique_projects"] > 10:
        parts.append(f"You scatter your attention across {s['unique_projects']} projects.")
        parts.append("This is a generalist's portfolio, someone who gets bored of one thing or who has too many ideas to contain.")
    elif s["unique_projects"] > 3:
        parts.append(f"You work across {s['unique_projects']} projects, enough variety to stay engaged but not so much that nothing gets depth.")
    elif s["unique_projects"] <= 2:
        parts.append(f"You concentrate on {s['unique_projects']} project(s), a focused investment.")
        parts.append("When you commit to something, you go deep.")

    if s["top_projects"] and not SANITIZE:
        proj_str = _proj_list(s["top_projects"], 3)
        if s["generic_session_pct"] > 40:
            parts.append(f"{s['generic_session_pct']:.0f}% of your sessions are ad-hoc work not tied to a specific project. Of the rest, your most-visited: {proj_str}.")
        else:
            parts.append(f"Your most-visited: {proj_str}.")

    if s["build_pct"] > 50:
        parts.append(f"{s['build_pct']:.0f}% of your sessions are building new things. Creation is your default mode.")
    elif s["fix_pct"] > 30:
        parts.append(f"Maintenance dominates: {s['fix_pct']:.0f}% of sessions are fixing existing work. You care about getting things right, not just getting them out.")
    if s["explore_pct"] > 20:
        parts.append(f"You spend {s['explore_pct']:.0f}% of your time just exploring, reading code without changing it. Curiosity isn't an afterthought for you.")
    if s["deploy_count"] > 50:
        parts.append(f"With {s['deploy_count']:,} deployments, you don't just write code. You ship it to production, constantly.")
    elif s["deploy_count"] > 10:
        parts.append(f"You've triggered {s['deploy_count']} deployments. The work isn't academic; it reaches users.")
    elif s["deploy_count"] == 0:
        parts.append("Zero deployments detected. Either you deploy through other channels, or the work is still in progress, still becoming.")

    if s["total_commits"] > 100:
        parts.append(f"You've made {s['total_commits']:,} commits, checkpointing your progress with the discipline of someone who's lost work before.")

    if s["total_goal_phrases"] > 20:
        gp = s["goal_phrases"]
        dominant = s["dominant_goal_phrase"]
        parts.append(f"When you talk about what you're doing, your go-to framing is \"{dominant}\" ({gp[dominant]} times).")
        if gp.get("need to", 0) > gp.get("want to", 0):
            parts.append("You frame your work as obligations more than desires. The language of necessity, not aspiration.")
        elif gp.get("want to", 0) > gp.get("need to", 0) * 2:
            parts.append("You frame your work as desires, not obligations. This is someone who does what they want, not just what they must.")

    return " ".join(parts)


def build_how_you_treat_others(s):
    """Section 3: Warmth, patience, frustration, politeness patterns."""
    parts = []

    parts.append(f"Your average niceness score is {s['avg_niceness']}/10 across {s['sessions_analyzed']} sessions, ranging from {s['min_niceness']} to {s['max_niceness']}.")

    if s["avg_niceness"] > 7:
        parts.append("You're genuinely warm. Not performatively polite, but authentically courteous in a context where politeness is entirely optional.")
    elif s["avg_niceness"] > 5:
        parts.append("You're polite without being effusive. There's enough warmth to show you see this as a conversation, not just a command line.")
    elif s["avg_niceness"] > 3:
        parts.append("You're direct. The warmth is minimal but not hostile. You treat your tools as tools.")
    else:
        parts.append("You don't do small talk. The interaction is transactional, and you make no apologies for that.")

    if s["nice_word_count"] > 100:
        parts.append(f"You've said 'please' {s['please_count']} times and 'thanks' {s['thanks_count']} times. That's a deliberate choice, repeated hundreds of times, in a context where no one is watching.")
    elif s["nice_word_count"] > 20:
        parts.append(f"'Please' appears {s['please_count']} times, 'thanks' {s['thanks_count']} times. Enough to show the instinct is there.")
    elif s["nice_word_count"] > 0:
        parts.append(f"'Please' appears {s['please_count']} times, 'thanks' {s['thanks_count']} times across {s['sessions_analyzed']} sessions. Almost nothing. You don't perform gratitude; if it shows up, it's genuine.")
    else:
        parts.append("Not a single 'please' or 'thanks' in your entire history. That's not rudeness; it's a particular kind of efficiency.")

    if s["positive_ending_pct"] > 40:
        parts.append(f"You end {s['positive_ending_pct']:.0f}% of your sessions on a positive note, a 'thanks' or 'great' as you close out. The endings matter to you.")
    elif s["positive_ending_pct"] > 15:
        parts.append(f"You end {s['positive_ending_pct']:.0f}% of sessions positively. When things go well, you acknowledge it.")
    elif s["positive_ending_pct"] < 10 and s["sessions_analyzed"] > 50:
        parts.append(f"Only {s['positive_ending_pct']:.0f}% of your sessions end with a positive word. You don't celebrate completions; you just move on to the next thing.")

    if s["frustration_per_session"] > 2:
        parts.append(f"But the frustration is real: {s['frustration_count']} outbursts across your history, averaging {s['frustration_per_session']:.1f} per session.")
        if s["all_caps_count"] > 50:
            parts.append(f"And {s['all_caps_count']} ALL_CAPS moments. When something breaks, you don't hide it.")
    elif s["frustration_per_session"] > 0.5:
        parts.append(f"Frustration surfaces about {s['frustration_per_session']:.1f} times per session, a moderate rate that you handle without escalating.")
    elif s["frustration_per_session"] < 0.2:
        parts.append(f"Frustration barely registers ({s['frustration_per_session']:.2f} per session). You're either remarkably patient or the work rarely gets under your skin.")

    if s["total_swears"] > 20:
        parts.append(f"You swear. {s['total_swears']} times total, peaking around {s['swear_peak_hour']}.")
        parts.append("It's not aggression. It's emphasis, a pressure valve that keeps the rest of your communication civil.")
    elif s["total_swears"] > 0:
        parts.append(f"The occasional swear ({s['total_swears']} total) slips through, mostly around {s['swear_peak_hour']}. Rare enough to be notable when it happens.")

    if s["niceness_stddev"] > 2:
        parts.append(f"Your tone varies considerably across sessions (stddev {s['niceness_stddev']:.1f}). Some days you're warm, some days you're all business. Context matters more than personality for your politeness level.")
    elif s["niceness_stddev"] < 1:
        parts.append(f"Your tone is remarkably stable (stddev {s['niceness_stddev']:.1f}). Good day or bad day, your communication style stays the same.")

    if s["correction_rate"] > 15:
        parts.append(f"You correct course {s['correction_rate']:.1f}% of the time ({s['correction_total']} corrections total). High standards, and you enforce them.")
    elif s["correction_rate"] > 5:
        parts.append(f"You correct course {s['correction_rate']:.1f}% of the time. Enough to show you're paying attention, not enough to suggest distrust.")

    return " ".join(parts)


def build_your_drive(s):
    """Section 4: Ambition, perfectionism, what pushes you."""
    parts = []

    if s["success_pct"] > 80:
        parts.append(f"You succeed {s['success_pct']:.0f}% of the time across {s['sessions_analyzed']} sessions. That's not luck over that many attempts; it's competence.")
    elif s["success_pct"] > 60:
        parts.append(f"A {s['success_pct']:.0f}% success rate across {s['sessions_analyzed']} sessions. You win more than you lose, but you're not playing it safe.")
    else:
        parts.append(f"Your success rate is {s['success_pct']:.0f}%. Lower than average, which means either the problems are hard or you're still finding your rhythm.")

    if s["abandoned_pct"] < 10:
        parts.append(f"You almost never walk away: only {s['abandoned_pct']:.0f}% of sessions are abandoned. When you start something, you finish it.")
    elif s["abandoned_pct"] < 25:
        parts.append(f"You abandon {s['abandoned_pct']:.0f}% of sessions, a pragmatic quit rate. You know when to cut your losses.")
    else:
        parts.append(f"You abandon {s['abandoned_pct']:.0f}% of sessions. That's high, and it could mean you take on things that are too ambitious, or you're quick to recognize dead ends.")

    if s["max_streak"] > 14:
        parts.append(f"Your longest coding streak is {s['max_streak']} consecutive days. That's not discipline; it's obsession.")
    elif s["max_streak"] > 7:
        parts.append(f"Your longest streak is {s['max_streak']} consecutive days of coding. Dedicated.")
    elif s["max_streak"] > 3:
        parts.append(f"Your longest streak is {s['max_streak']} consecutive days. You work in bursts, not marathons.")

    if s["avg_duration"] > 90:
        parts.append(f"Your average session runs {s['avg_duration']:.0f} minutes. These are deep work sessions, not quick check-ins. You sink into problems.")
    elif s["avg_duration"] > 40:
        parts.append(f"Your average session is {s['avg_duration']:.0f} minutes. Long enough for real progress, short enough to stay sharp.")
    elif s["avg_duration"] < 15:
        parts.append(f"At {s['avg_duration']:.0f} minutes per session, you work fast. Get in, get it done, get out.")

    if s["duration_cv"] > 1.0:
        parts.append("Your session lengths vary wildly. Some are quick fixes, others are marathon deep dives. You match your investment to the problem.")
    elif s["duration_cv"] < 0.4 and s["sessions_analyzed"] > 30:
        parts.append("Your session lengths are remarkably consistent. You have a natural working rhythm and you stick to it.")

    if s["mixed_pct"] > 30 and s["deploy_count"] > 10:
        parts.append(f"You don't separate building from fixing from exploring; you do whatever the problem demands, and you ship constantly ({s['deploy_count']:,} deployments).")
    elif s["build_pct"] > 50 and s["deploy_count"] > 10:
        parts.append(f"Building is your dominant mode ({s['build_pct']:.0f}%), and you ship what you build ({s['deploy_count']:,} deployments). You're not a tinkerer; you're a shipper.")
    elif s["fix_pct"] > 50:
        parts.append(f"You spend most of your time fixing ({s['fix_pct']:.0f}%). Your drive is less about creating and more about making things right.")
    elif s["deploy_count"] > 100:
        parts.append(f"Regardless of session type, you ship: {s['deploy_count']:,} deployments across {s['sessions_analyzed']} sessions.")

    if s["correction_rate"] > 10:
        parts.append(f"Your {s['correction_rate']:.1f}% correction rate reveals high standards. You don't accept 'good enough' from your tools.")

    # Grit indicator
    if s["total_errors"] > 0:
        if s["switched_pct"] > s["gave_up_pct"] and s["switched_pct"] > 30:
            parts.append(f"When things break, you adapt: {s['switched_pct']:.0f}% of the time you try a different approach. That's grit, not stubbornness.")
        elif s["retried_pct"] > 50:
            parts.append(f"When things break, you push through: {s['retried_pct']:.0f}% of the time you retry the same approach. Persistent, possibly to a fault.")
        elif s["gave_up_pct"] > 40:
            parts.append(f"When things break, you walk away {s['gave_up_pct']:.0f}% of the time. You know when the cost exceeds the benefit.")

    return " ".join(parts)


def build_temperament(s):
    """Section 5: Emotional patterns, stress response, mood."""
    parts = []

    # Overall emotional temperature
    if s["frustration_per_session"] < 0.3 and s["niceness_stddev"] < 1.5:
        parts.append("You're even-keeled. Your emotional baseline barely fluctuates across sessions, regardless of what's happening in the code.")
    elif s["frustration_per_session"] > 2 or s["all_caps_count"] > 100:
        parts.append("You feel things. The data shows clear emotional peaks and valleys across your sessions.")
    else:
        parts.append("Your emotional range is moderate, neither flat nor volatile.")

    # Frustration patterns
    if s["frustration_count"] > 0:
        if s["frustration_per_session"] > 2:
            parts.append(f"Frustration is a regular companion: {s['frustration_count']} events across {s['sessions_analyzed']} sessions, {s['frustration_per_session']:.1f} per session.")
        elif s["frustration_per_session"] > 0.5:
            parts.append(f"Frustration appears at a moderate rate ({s['frustration_per_session']:.1f} per session). It exists, but it doesn't dominate.")
        else:
            parts.append(f"Frustration is rare ({s['frustration_per_session']:.2f} per session). You keep your composure.")

    # ALL_CAPS as emotional indicator
    if s["all_caps_count"] > 100:
        parts.append(f"You've used ALL_CAPS emphasis {s['all_caps_count']} times. It's become part of your communication style, not just a frustration signal but a way of adding weight to words.")
    elif s["all_caps_count"] > 10:
        parts.append(f"The {s['all_caps_count']} ALL_CAPS moments are stress markers, points where the text alone wasn't carrying enough urgency.")

    # Vocabulary under stress
    if s["guiraud_calm"] > 0 and s["guiraud_frustrated"] > 0:
        ratio = s["guiraud_frustrated"] / s["guiraud_calm"]
        if ratio < 0.85:
            parts.append(f"Under stress, your vocabulary narrows (richness drops from {s['guiraud_calm']} to {s['guiraud_frustrated']}). Stress literally shrinks your language, as if your brain is conserving bandwidth for the problem.")
        elif ratio > 1.15:
            parts.append(f"Under stress, your vocabulary actually expands ({s['guiraud_calm']} calm vs {s['guiraud_frustrated']} frustrated). You reach for more precise words when things go wrong.")

    # Niceness vs frustration tension
    if s["avg_niceness"] > 5 and s["frustration_per_session"] > 1:
        parts.append(f"There's a tension in your data: {s['avg_niceness']}/10 niceness alongside {s['frustration_per_session']:.1f} frustration events per session. You're civil on the surface while the pressure builds underneath. The politeness isn't fake; neither is the frustration.")

    # Error recovery style as temperament signal
    if s["total_errors"] > 0:
        if s["retried_pct"] > 50:
            parts.append(f"Your error response is persistence: {s['retried_pct']:.0f}% of the time, you try the same thing again. Your temperament says 'push through' before 'step back'.")
        elif s["switched_pct"] > 40:
            parts.append(f"Your error response is flexibility: {s['switched_pct']:.0f}% of the time, you pivot. You don't get attached to approaches that aren't working.")
        elif s["gave_up_pct"] > 40:
            parts.append(f"You walk away from {s['gave_up_pct']:.0f}% of error sequences. Your temperament has a clear 'not worth it' threshold.")

    # Frustration + success paradox
    if s["frustration_per_session"] > 1 and s["success_pct"] > 65:
        parts.append(f"The frustration doesn't cost you outcomes. {s['success_pct']:.0f}% success despite the emotional turbulence. Some people do their best work while annoyed.")

    return " ".join(parts)


def build_your_mind(s):
    """Section 6: How you think, communicate, solve problems."""
    parts = []

    # Communication style
    if s["avg_words_per_prompt"] > 80:
        parts.append(f"You write at {s['avg_words_per_prompt']:.0f} words per prompt, more like design documents than instructions. You think by writing, explaining the problem as you formulate the solution.")
    elif s["avg_words_per_prompt"] > 30:
        parts.append(f"Your prompts average {s['avg_words_per_prompt']:.0f} words, a balanced approach that provides context without drowning in it.")
    elif s["avg_words_per_prompt"] < 12:
        parts.append(f"At {s['avg_words_per_prompt']:.0f} words per prompt, you communicate like a command line. Efficient, precise, no waste.")
    else:
        parts.append(f"Your prompts average {s['avg_words_per_prompt']:.0f} words. Direct but not terse.")

    # Specificity
    if s["avg_spec"] > 7:
        parts.append(f"Your specificity scores {s['avg_spec']}/10. You know what you want before you ask for it. The prompts read like specifications, not wishes.")
    elif s["avg_spec"] > 5:
        parts.append(f"Specificity at {s['avg_spec']}/10. You provide direction without micromanaging the approach.")
    else:
        parts.append(f"Your specificity is {s['avg_spec']}/10. You tend to describe outcomes rather than paths, leaving room for interpretation.")

    # Vocabulary richness
    if s["guiraud"] > 10:
        parts.append(f"Your vocabulary is exceptionally rich (Guiraud index {s['guiraud']}, {s['unique_words']:,} unique words). You choose your words deliberately, and it shows.")
    elif s["guiraud"] > 6:
        parts.append(f"Your vocabulary is solid (Guiraud {s['guiraud']}, {s['unique_words']:,} unique words). You have the words for what you mean.")
    else:
        parts.append(f"Your vocabulary is functional (Guiraud {s['guiraud']}). You prioritize clarity over variety.")

    # Question vs command style
    if s["question_ratio"] > 20:
        parts.append(f"{s['question_ratio']:.0f}% of your messages are questions. You think by inquiring, building understanding through dialogue rather than dictation.")
    elif s["question_ratio"] > 8:
        parts.append(f"{s['question_ratio']:.0f}% of your messages are questions, mixing inquiry with instruction. You know when to ask and when to tell.")
    elif s["question_ratio"] < 3:
        parts.append(f"Only {s['question_ratio']:.0f}% of your messages are questions. You give directives. You already know what you want.")

    # First message strategy
    if s["avg_first_msg_ratio"] > 60:
        parts.append(f"Your opening message carries {s['avg_first_msg_ratio']:.0f}% of the session's text. You front-load everything: context, goals, constraints. By the time you send the first message, the problem is already decomposed in your head.")
    elif s["avg_first_msg_ratio"] < 25:
        parts.append(f"Your first message is just {s['avg_first_msg_ratio']:.0f}% of the session. You build context incrementally, layering understanding through iteration.")

    # Structured thinking
    if s["numbered_steps_pct"] > 10:
        parts.append(f"You use numbered steps in {s['numbered_steps_pct']:.0f}% of your prompts. A structured thinker who breaks problems into sequences.")
    elif s["numbered_steps_pct"] < 2:
        parts.append("You rarely use numbered steps. Your thinking flows as prose, not procedures.")

    # Languages
    if s["lang_count"] >= 3:
        parts.append(f"You operate in {s['lang_count']} languages ({', '.join(s['languages'][:3])}). Multilingual thinking adds a dimension that monolingual users don't have.")
    elif s["lang_count"] == 2:
        parts.append(f"You switch between {s['languages'][0]} and {s['languages'][1]} mid-session, a bilingual mind that picks whichever language fits the thought.")

    # Interaction style
    if s["prompts_per_session"] > 15:
        parts.append(f"At {s['prompts_per_session']:.0f} prompts per session, you maintain rapid-fire dialogue. Your problem-solving is iterative, conversational, reactive.")
    elif s["prompts_per_session"] < 5:
        parts.append(f"At {s['prompts_per_session']:.0f} prompts per session, you work in large batches. Think long, speak once, let it run.")

    return " ".join(parts)


def build_your_habits(s):
    """Section 7: Routines, rituals, schedule, quirks."""
    parts = []

    # Time of day
    if s["night_session_pct"] > 40:
        parts.append(f"You're a night coder: {s['night_session_pct']:.0f}% of your sessions happen between 10pm and 6am. The world is quiet, and that's when your focus sharpens.")
    elif s["night_session_pct"] > 25:
        parts.append(f"A significant portion ({s['night_session_pct']:.0f}%) of your coding happens at night. You don't plan it that way; the work just extends past sunset.")
    elif s["morning_session_pct"] > 40:
        parts.append(f"You're a morning coder: {s['morning_session_pct']:.0f}% of sessions start before noon. Fresh mind, fresh code.")
    elif s["afternoon_session_pct"] > 40:
        parts.append(f"You peak in the afternoon: {s['afternoon_session_pct']:.0f}% of your sessions happen between noon and 6pm.")
    else:
        parts.append("Your coding hours are spread across the day, no strong time preference.")

    parts.append(f"Peak activity: {s['peak_start']}.")

    # Weekend patterns
    if s["weekend_pct"] > 40:
        parts.append(f"You code on weekends {s['weekend_pct']:.0f}% of the time. The line between work and life doesn't mean much to you, at least not for coding.")
    elif s["weekend_pct"] > 20:
        parts.append(f"Weekends see {s['weekend_pct']:.0f}% of your sessions. You mostly rest, but the code pulls you back regularly.")
    elif s["weekend_pct"] < 10:
        parts.append(f"Weekends are sacred: only {s['weekend_pct']:.0f}% of sessions fall on Saturday or Sunday. You maintain boundaries.")

    # Morning vs evening performance
    if s["morning_success"] > 0 and s["evening_success"] > 0:
        diff = abs(s["morning_success"] - s["evening_success"])
        if diff > 10:
            better = "morning" if s["morning_success"] > s["evening_success"] else "evening"
            worse = "evening" if better == "morning" else "morning"
            parts.append(f"You perform better in the {better} ({s['morning_success']:.0f}% vs {s['evening_success']:.0f}%). Your {worse} self would benefit from knowing this.")

    # Session rhythm
    if s["avg_duration"] > 90:
        parts.append(f"Your sessions run {s['avg_duration']:.0f} minutes on average. These are marathon sessions that suggest you need sustained focus to do your best work.")
    elif s["avg_duration"] > 40:
        parts.append(f"Sessions average {s['avg_duration']:.0f} minutes. Deep enough for real progress, bounded enough to stay fresh.")
    elif s["avg_duration"] < 15:
        parts.append(f"At {s['avg_duration']:.0f} minutes, your sessions are surgical. Quick problem, quick fix, move on.")

    # Streak
    if s["max_streak"] > 7:
        parts.append(f"Your longest consecutive coding streak: {s['max_streak']} days. That kind of consistency only comes from either discipline or obsession.")
    elif s["max_streak"] > 3:
        parts.append(f"Your longest streak is {s['max_streak']} days. You work in focused bursts rather than unbroken marathons.")

    # Prompting habits
    if s["prompts_per_session"] > 15:
        parts.append(f"You average {s['prompts_per_session']:.0f} prompts per session, a high-interaction style. You iterate rapidly, thinking out loud.")
    elif s["prompts_per_session"] < 5:
        parts.append(f"At {s['prompts_per_session']:.0f} prompts per session, you craft each message carefully. Quality over quantity.")

    # Top words as personality signal
    if s["top_words"]:
        word_str = ", ".join(s["top_words"][:7])
        parts.append(f"Your most-used words (excluding common terms): {word_str}.")

    return " ".join(parts)


def build_what_id_tell_you(s):
    """Section 8: Honest observations, blind spots, strengths you underestimate."""
    parts = []

    # Strength they likely underestimate
    if s["success_pct"] > 70 and s["frustration_per_session"] > 1:
        parts.append(f"You probably don't realize how effective you are. A {s['success_pct']:.0f}% success rate despite regular frustration means your process works even when it doesn't feel like it.")
    elif s["avg_niceness"] > 6 and s["correction_rate"] > 5:
        parts.append("You maintain warmth while still holding high standards. That combination is rarer than you think.")
    elif s["switched_pct"] > 30:
        parts.append(f"Your adaptability is a genuine strength. Switching approaches {s['switched_pct']:.0f}% of the time after errors is the sign of someone who values results over ego.")

    # Blind spot
    if s["night_session_pct"] > 30 and s["morning_success"] > s["evening_success"] + 10:
        parts.append(f"Here's something you might not see: you code most at night ({s['night_session_pct']:.0f}%), but your success rate is higher in the morning ({s['morning_success']:.0f}% vs {s['evening_success']:.0f}%). Your preference and your performance point in different directions.")
    elif s["retried_pct"] > 50:
        parts.append(f"When things fail, you retry the same approach {s['retried_pct']:.0f}% of the time. Persistence is a virtue, but there's a point where it becomes the obstacle. Pivoting earlier might save you hours.")
    elif s["frustration_per_session"] > 2 and s["avg_niceness"] > 5:
        parts.append(f"You're polite on the surface ({s['avg_niceness']}/10) but frustrated underneath ({s['frustration_per_session']:.1f} per session). The civility costs you something. It's worth asking whether expressing frustration earlier would reduce the buildup.")

    # Honest observation about work habits
    if s["weekend_pct"] > 40 and s["total_hours"] > 200:
        parts.append(f"You've spent {s['total_hours']:.0f} hours coding, {s['weekend_pct']:.0f}% on weekends. That's dedication, but it's also a sustainability question. The data can't tell me if this pace brings you energy or drains it.")
    elif s["max_streak"] > 14:
        parts.append(f"A {s['max_streak']}-day coding streak is impressive, but the body of research on sustained cognitive work says breaks aren't optional. Your best work probably didn't happen on day 14.")

    # Pattern they might not see
    if s["abandoned_pct"] > 25 and s["build_pct"] > 40:
        parts.append(f"You start a lot of things ({s['build_pct']:.0f}% build sessions) but abandon {s['abandoned_pct']:.0f}% of them. The ambition is real, but so is the pattern of starting more than you finish.")
    elif s["explore_pct"] > 25 and s["build_pct"] < 20:
        parts.append(f"You spend {s['explore_pct']:.0f}% of your time exploring and only {s['build_pct']:.0f}% building from scratch. If you feel like you're not shipping enough, this ratio is why. Understanding is eating into creation time.")
    elif s["fix_pct"] > s["build_pct"] + 20:
        parts.append(f"You spend {s['fix_pct']:.0f}% of your time fixing and only {s['build_pct']:.0f}% building. If that ratio doesn't match your aspirations, the gap is worth examining.")

    # Vocabulary / thinking pattern
    if s["question_ratio"] < 5 and s["avg_spec"] < 5:
        parts.append("You rarely ask questions and your specificity is moderate. That combination can lead to misunderstandings: you assume things are clear when they might not be. More questions, earlier, would sharpen your outcomes.")
    elif s["question_ratio"] > 20 and s["avg_spec"] > 7:
        parts.append("You ask a lot of questions and your prompts are highly specific. That's a powerful combination, but it can also mean you're solving problems in your head twice: once when formulating the question, and again when checking the answer.")

    # Closing - data-driven summary, not sentiment
    if s["total_hours"] > 500:
        parts.append(f"After {s['total_hours']:.0f} hours and {s['total_prompts']:,} prompts, the data paints a consistent picture: {s['success_pct']:.0f}% success rate, {s['deploy_count']:,} deployments, {s['total_commits']:,} commits. The numbers say you're productive. The {s['correction_rate']:.1f}% correction rate and {s['frustration_per_session']:.1f} frustration events per session say you're not satisfied with productive.")
    elif s["total_hours"] > 100:
        parts.append(f"Across {s['total_hours']:.0f} hours, the profile is internally consistent: your work habits, communication style, and error responses all point the same direction. You know what you want and you push until you get it.")
    else:
        parts.append(f"With {s['total_hours']:.0f} hours in the data, this portrait will sharpen with more sessions. The broad strokes are already visible, but the finer details need more data points.")

    return " ".join(parts)


# ---------------------------------------------------------------------------
# HTML Generation
# ---------------------------------------------------------------------------
def generate_html(data, signals):
    """Read template, substitute placeholders, return HTML string."""
    template = TEMPLATE_PATH.read_text()
    s = signals

    author = AUTHOR_NAME or "Claude Code User"

    # Date range
    all_ts = s.get("all_timestamps", [])
    if all_ts:
        start_date = min(all_ts).strftime("%b %d")
        end_date = max(all_ts).strftime("%b %d, %Y")
        date_range = f"{start_date} &ndash; {end_date}"
    else:
        date_range = "No data"

    # Build all section narratives
    first_impression = build_first_impression(s)
    what_you_care_about = build_what_you_care_about(s)
    how_you_treat_others = build_how_you_treat_others(s)
    your_drive = build_your_drive(s)
    temperament = build_temperament(s)
    your_mind = build_your_mind(s)
    your_habits = build_your_habits(s)
    what_id_tell_you = build_what_id_tell_you(s)

    # Heatmap
    rhythm = analyze_work_rhythm(data)
    heatmap_data = json.dumps(rhythm["grid"])

    # Sparse data disclaimer
    disclaimer = ""
    if s["sessions_analyzed"] < 50:
        disclaimer = f'<div class="callout" style="background:#FEF3C7;">Early portrait based on {s["sessions_analyzed"]} sessions. The picture gets sharper with more data.</div>'

    replacements = {
        "__PT_AUTHOR__": _html_escape(author),
        "__PT_DATE_RANGE__": date_range,
        "__PT_SESSION_COUNT__": str(s["sessions_analyzed"]),
        "__PT_TOTAL_HOURS__": str(s["total_hours"]),
        "__PT_TOTAL_PROMPTS__": str(s["total_prompts"]),
        "__PT_DISCLAIMER__": disclaimer,
        "__PT_FIRST_IMPRESSION__": _html_escape(first_impression),
        "__PT_WHAT_YOU_CARE_ABOUT__": _html_escape(what_you_care_about),
        "__PT_HOW_YOU_TREAT_OTHERS__": _html_escape(how_you_treat_others),
        "__PT_YOUR_DRIVE__": _html_escape(your_drive),
        "__PT_TEMPERAMENT__": _html_escape(temperament),
        "__PT_YOUR_MIND__": _html_escape(your_mind),
        "__PT_YOUR_HABITS__": _html_escape(your_habits),
        "__PT_WHAT_ID_TELL_YOU__": _html_escape(what_id_tell_you),
        "__PT_HEATMAP_DATA__": heatmap_data,
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
        print(f"Need at least {MIN_SESSIONS} sessions for a portrait. You have {n}.")
        sys.exit(1)

    print("Mining signals...")
    signals = mine_signals(data)

    print("Building portrait narratives...")
    html = generate_html(data, signals)

    OUTPUT_DIR.mkdir(exist_ok=True)
    OUTPUT_PATH.write_text(html)
    print(f"Wrote {OUTPUT_PATH} ({len(html):,} bytes)")

    print(f"\nPortrait Summary:")
    print(f"  Sessions: {n}")
    print(f"  Hours: {signals['total_hours']}")
    print(f"  Projects: {signals['unique_projects']}")
    print(f"  Niceness: {signals['avg_niceness']}/10")
    print(f"  Success: {signals['success_pct']}%")


if __name__ == "__main__":
    main()
