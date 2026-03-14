# Transcript Analyzer

Analyzes Claude Code (and future: Codex, OpenCode) conversation transcripts to find patterns, issues, and prompting quality insights.

## Architecture

- `extract.py` - Parses JSONL conversation files from `~/.claude/projects/`, extracts structured data (messages, tool usage, errors, tokens). Supports `--include-subagents` flag.
- `analyze.py` - Three analysis modes:
  - `local` - Pure Python stats aggregation (no API call)
  - `batch` - Sends aggregate stats to Gemini for pattern analysis
  - `deep` - Sends full conversation transcripts to Gemini for detailed analysis
- `patterns/` - 10 standalone pattern analysis scripts, each outputs a `.md` report
- `patterns/config.py` - Shared configuration (paths, session finder)
- `generate_findings.py` - Auto-generates `FINDINGS.md` from pattern outputs
- `generate_wrapped.py` - Generates self-contained `dist/wrapped.html` from session data (imports all pattern analyzers, single-pass iteration, string-substitution into `wrapped.html` template)
- `wrapped.html` - Template for wrapped report (contains `__PLACEHOLDER__` markers)
- `run_all.py` - Unified runner for all pattern scripts + findings generation
- `tests/` - Test suite for core extraction logic
- `reports/` - Generated Gemini analysis reports (gitignored)
- `dist/` - Generated wrapped output (gitignored)

## Usage

```bash
# Run all pattern analyses + generate FINDINGS.md
python3 run_all.py --patterns-only

# Run single pattern
python3 run_all.py --pattern self_scoring

# Local stats (no API, fast)
python3 analyze.py local --limit 100

# Batch analysis (Gemini, aggregate stats)
python3 analyze.py batch --limit 50

# Deep analysis (Gemini, full transcripts)
python3 analyze.py deep --limit 3 --min-size 1000

# Generate wrapped.html report
python3 run_all.py --wrapped

# Generate with custom config
WRAPPED_AUTHOR="Your Name" WRAPPED_TZ_OFFSET=2 python3 generate_wrapped.py

# Generate and publish to buildingopen.org/wrapped/<hash>
WRAPPED_AUTHOR="Your Name" WRAPPED_SUPABASE_KEY="service_role_key" python3 generate_wrapped.py --publish

# Run tests
python3 -m pytest tests/ -v
```

## Configuration

- `CLAUDE_PROJECTS_DIR` env var overrides the default `~/.claude/projects/` data path
- Default Gemini model: `gemini-3-flash-preview` (override with `--model`)

### Wrapped report env vars
- `WRAPPED_AUTHOR` - Display name (default: "Claude Code User")
- `WRAPPED_TZ_OFFSET` - Hours from UTC for local time display (default: 0)
- `WRAPPED_MONEY_PAID` - Total subscription cost in USD for ROI comparison (optional)
- `WRAPPED_MONEY_DETAIL` - Description of subscription (e.g. "3 Claude Max accounts")
- `WRAPPED_SHARE_URL` - Public URL for share buttons (auto-set with `--publish`)
- `WRAPPED_SUPABASE_KEY` - Supabase service_role key for publishing (project: cbhbfutssknfjvgvavnt)

## Adding New Projects

Add project directory mappings in `patterns/config.py` via `PROJECT_NAME_MAP`:
```python
PROJECT_NAME_MAP = {
    "directory-basename": "Friendly Name",
}
```

## Data Source

Claude Code stores conversations as JSONL in `~/.claude/projects/`. Each line is one of:
- `assistant` - Model response with content blocks (text, tool_use) and token usage
- `user` - Human input or tool results (including errors/rejections)
- `progress` - Streaming progress updates (skipped during extraction)
- `file-history-snapshot` - File state snapshots (skipped)
- `system` - System messages

## Pattern Scripts

All in `patterns/`, each produces a `.md` output file:
- `error_taxonomy` - Classifies 14 error categories across all sessions
- `hook_rejections` - Hook rejection analysis with agent reaction tracking
- `large_file_errors` - "File exceeds maximum" errors and recovery behavior
- `project_stats` - Per-project stats, time-of-day usage, cost estimation
- `prompting_style` - User prompting patterns, length distribution, effectiveness
- `retry_loops` - Retry loops, wasted tokens, stuck patterns
- `self_scoring` - Self-rating patterns, score distribution, optimism bias
- `session_outcomes` - Session outcome classification (success/failure/partial)
- `tool_misuse` - Wrong tool usage detection (Bash vs Read, etc.)
- `communication_tone` - Communication tone, niceness scoring, swear tracking
