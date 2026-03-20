# Claude Code Wrapped

Spotify Wrapped for Claude Code. Generates a visual HTML report from session data.

## Architecture

- `bin/claude-wrapped.js` - CLI entry point, finds Python, runs generate_wrapped.py
- `generate_wrapped.py` - Main report generator (single-pass JSONL iteration, all pattern analyzers, string-substitution into wrapped.html template)
- `wrapped.html` - Template with `__PLACEHOLDER__` markers
- `patterns/` - 10 standalone pattern analysis scripts + shared config
- `patterns/config.py` - Shared configuration (paths, session finder)
- `extract.py` - JSONL parser (standalone, used by analyze.py)
- `analyze.py` - Gemini analysis modes (local, batch, deep)
- `run_all.py` - Pattern runner + findings generation
- `generate_findings.py` - Aggregates pattern outputs into FINDINGS.md
- `tests/` - Test suite

## Usage

```bash
# npm (one-liner)
npx claude-wrapped

# Direct Python
WRAPPED_AUTHOR="Your Name" python3 generate_wrapped.py

# Publish (auto-sanitized)
python3 generate_wrapped.py --publish

# Run tests
python3 -m pytest tests/ -v
```

## Repo structure

This repo (`buildingopen/claude-wrapped`) contains only the Wrapped report.
Other reports (prompt-coach, user-profile, soul, portrait) live in `buildingopen/claude-wrapped-lab`.
The private dev repo is `federicodeponte/transcript-analyzer`.

## npm package

Published as `claude-wrapped` on npm. Version bump + `npm publish` from this repo.
