"""
Floom wrapper for claude-wrapped.

Accepts one or more Claude Code session transcripts (JSONL) pasted as text,
writes them into a temp directory that mimics ~/.claude/projects/<slug>/,
runs generate_wrapped.py, and returns the generated HTML report.
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from floom import app, save_artifact

REPO_ROOT = Path(__file__).parent
GENERATOR = REPO_ROOT / "generate_wrapped.py"


def _materialise_sessions(jsonl_text: str, project_slug: str, base: Path) -> int:
    """Write pasted JSONL content into base/projects/<slug>/session.jsonl.

    Multiple sessions can be pasted, separated by a line '---' on its own.
    Returns the number of session files created.
    """
    projects_dir = base / "projects" / (project_slug or "default-project")
    projects_dir.mkdir(parents=True, exist_ok=True)

    chunks = [chunk.strip() for chunk in jsonl_text.split("\n---\n")]
    chunks = [c for c in chunks if c]
    if not chunks:
        return 0

    for i, chunk in enumerate(chunks):
        path = projects_dir / f"session-{i+1:03d}.jsonl"
        path.write_text(chunk + ("\n" if not chunk.endswith("\n") else ""))
    return len(chunks)


@app.action
def generate(jsonl_sessions: str, author: str = "Claude Code User", project_slug: str = "my-project") -> dict:
    """
    Generate a Claude Code Wrapped HTML report from pasted session transcripts.

    jsonl_sessions: one or more JSONL session files. Separate multiple sessions
                    with a line containing only '---'.
    author: display name for the report
    project_slug: directory slug used when the report groups by project
    """
    if not jsonl_sessions or not jsonl_sessions.strip():
        return {"error": "jsonl_sessions is empty", "sessions": 0}

    tmp = tempfile.mkdtemp(prefix="claude-wrapped-")
    try:
        count = _materialise_sessions(jsonl_sessions, project_slug, Path(tmp))
        if count == 0:
            return {"error": "no sessions parsed from input", "sessions": 0}

        env = os.environ.copy()
        env["CLAUDE_PROJECTS_DIR"] = str(Path(tmp) / "projects")
        env["WRAPPED_AUTHOR"] = author

        result = subprocess.run(
            [sys.executable, str(GENERATOR)],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=600,
        )

        dist_html = REPO_ROOT / "dist" / "wrapped.html"
        if result.returncode != 0 or not dist_html.exists():
            return {
                "error": f"wrapped generation failed (exit {result.returncode})",
                "stdout": (result.stdout or "")[-1500:],
                "stderr": (result.stderr or "")[-1500:],
                "sessions": count,
            }

        html = dist_html.read_text()

        # Artifact for download, plus inline HTML for the UI.
        save_artifact("wrapped.html", html)

        # Clean up the generated dist file so subsequent runs start fresh.
        try:
            dist_html.unlink()
        except OSError:
            pass

        return {
            "sessions": count,
            "html": html,
            "log": (result.stdout or "")[-2000:],
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
