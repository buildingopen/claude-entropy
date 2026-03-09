# Transcript Analyzer

Analyzes Claude Code (and future: Codex, OpenCode) conversation transcripts to find patterns, issues, and prompting quality insights.

## Architecture

- `extract.py` - Parses JSONL conversation files from `~/.claude/projects/`, extracts structured data (messages, tool usage, errors, tokens)
- `analyze.py` - Three analysis modes:
  - `local` - Pure Python stats aggregation (no API call)
  - `batch` - Sends aggregate stats to Gemini for pattern analysis
  - `deep` - Sends full conversation transcripts to Gemini for detailed analysis
- `reports/` - Generated analysis reports (gitignored)

## Usage

```bash
# Local stats (no API, fast)
python3 analyze.py local --limit 100

# Batch analysis (Gemini, aggregate stats)
python3 analyze.py batch --limit 50

# Deep analysis (Gemini, full transcripts)
python3 analyze.py deep --limit 3 --min-size 1000
```

## Data Source

Claude Code stores conversations as JSONL in `~/.claude/projects/`. Each line is one of:
- `assistant` - Model response with content blocks (text, tool_use) and token usage
- `user` - Human input or tool results (including errors/rejections)
- `progress` - Streaming progress updates (skipped during extraction)
- `file-history-snapshot` - File state snapshots (skipped)
- `system` - System messages
