import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from generate_findings import extract_summary, main, OUTPUT_FILE, PATTERNS_DIR


class TestExtractSummary:
    def test_empty_input(self):
        assert extract_summary("") == ""

    def test_normal_content(self):
        content = "Line 1\nLine 2\nLine 3"
        assert extract_summary(content) == content

    def test_skips_per_session_details(self):
        content = "Summary here\nMore summary\n## Per-Session Details\nDetail 1\nDetail 2"
        result = extract_summary(content)
        assert "Summary here" in result
        assert "More summary" in result
        assert "Detail 1" not in result
        assert "Detail 2" not in result

    def test_skips_detailed_findings(self):
        content = "Top section\n## Detailed Findings\nShould be skipped"
        result = extract_summary(content)
        assert "Top section" in result
        assert "Should be skipped" not in result

    def test_skips_all_instances(self):
        content = "Summary\n## All Instances\nInstance 1"
        result = extract_summary(content)
        assert "Summary" in result
        assert "Instance 1" not in result

    def test_skips_full_listing(self):
        content = "Summary\n## Full Listing\nListed item"
        result = extract_summary(content)
        assert "Summary" in result
        assert "Listed item" not in result

    def test_skips_raw_data(self):
        content = "Summary\n## Raw Data\nRaw line"
        result = extract_summary(content)
        assert "Summary" in result
        assert "Raw line" not in result

    def test_max_lines_truncation(self):
        content = "\n".join(f"Line {i}" for i in range(100))
        result = extract_summary(content, max_lines=10)
        lines = result.split("\n")
        # 10 content lines + 1 truncation notice
        assert len(lines) == 11
        assert "truncated" in lines[-1]

    def test_case_insensitive_skip(self):
        content = "Summary\n## per-session details\nHidden"
        result = extract_summary(content)
        assert "Summary" in result
        assert "Hidden" not in result


class TestGenerateFindings:
    def test_generate_findings_creates_file(self, tmp_path, monkeypatch):
        """Test that main() creates FINDINGS.md by reading from patterns/*.md."""
        import generate_findings

        # Point PATTERNS_DIR and OUTPUT_FILE to tmp_path
        patterns_dir = tmp_path / "patterns"
        patterns_dir.mkdir()
        output_file = tmp_path / "FINDINGS.md"

        monkeypatch.setattr(generate_findings, "PATTERNS_DIR", patterns_dir)
        monkeypatch.setattr(generate_findings, "OUTPUT_FILE", output_file)

        # Create a sample pattern file matching one of the PATTERN_ORDER entries
        (patterns_dir / "error_taxonomy.md").write_text("Error stats: 5 total errors")

        main()

        assert output_file.exists()
        content = output_file.read_text()
        assert "Transcript Analysis Findings" in content
        assert "Error Taxonomy" in content
        assert "Error stats: 5 total errors" in content
        # Patterns without files get "Not yet generated" message
        assert "Not yet generated" in content
