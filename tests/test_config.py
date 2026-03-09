import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from patterns.config import CLAUDE_PROJECTS_DIR, find_sessions, output_path, OUTPUT_DIR


class TestCLAUDEProjectsDir:
    def test_claude_projects_dir_path(self):
        expected = Path.home() / ".claude" / "projects"
        assert CLAUDE_PROJECTS_DIR == expected


class TestOutputPath:
    def test_output_path(self):
        result = output_path("foo")
        assert result == OUTPUT_DIR / "foo.md"
        assert result.name == "foo.md"

    def test_output_path_custom_ext(self):
        result = output_path("foo", ".txt")
        assert result == OUTPUT_DIR / "foo.txt"
        assert result.name == "foo.txt"


class TestFindSessions:
    def test_find_sessions_returns_list(self):
        result = find_sessions()
        assert isinstance(result, list)
