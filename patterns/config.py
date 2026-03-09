"""Shared configuration for pattern analysis scripts."""

from pathlib import Path

CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"
PATTERNS_DIR = Path(__file__).parent
OUTPUT_DIR = PATTERNS_DIR  # outputs live alongside scripts
MIN_SESSION_SIZE = 100 * 1024  # 100KB default
MAX_SESSIONS = 50


def find_sessions(min_size=MIN_SESSION_SIZE, max_sessions=MAX_SESSIONS,
                  include_subagents=False):
    """Find recent JSONL sessions above min_size, sorted by recency."""
    sessions = []
    for jsonl in CLAUDE_PROJECTS_DIR.rglob("*.jsonl"):
        if not include_subagents and "subagent" in str(jsonl):
            continue
        try:
            stat = jsonl.stat()
            if stat.st_size >= min_size:
                sessions.append((stat.st_mtime, stat.st_size, jsonl))
        except OSError:
            continue
    sessions.sort(reverse=True)
    return sessions[:max_sessions]


def output_path(name, ext=".md"):
    """Return the output path for a pattern analysis."""
    return OUTPUT_DIR / f"{name}{ext}"
