# Claude Code Entropy

Spotify Wrapped for Claude Code. Analyzes your `~/.claude/projects/` session data and generates a visual HTML report with usage stats, coding patterns, and personalized insights.

## Quick Start

```bash
npx claude-entropy                    # Wrapped report (default)
npx claude-entropy prompt-coach       # Prompt coaching report
npx claude-entropy user-profile       # Personality & character profile
npx claude-entropy soul               # Deep personality profile
npx claude-entropy portrait           # "How AI Sees You" character study
```

Requires: Node.js 14+ and Python 3.8+ on PATH.

## Reports

### Wrapped (default)
A self-contained HTML report with 20+ slides covering:

- **Sessions & hours** coded with Claude, daily streaks, peak coding days
- **Lines of code** generated across all projects
- **Token usage** and estimated cost (input, output, cache)
- **Project breakdown** with per-project stats
- **Prompting style** analysis: length, specificity, effectiveness
- **Error patterns**: taxonomy of 14 error categories
- **Retry loops**: wasted tokens from stuck patterns
- **Communication tone**: niceness score, swear tracking
- **Self-scoring bias**: how accurately Claude rates its own work
- **Tool usage**: misuse detection (Bash vs Read, etc.)
- **Coding personality**: archetype based on your usage patterns
- **Percentile ranking**: how you compare to other Claude Code users

### Prompt Coach
A coaching report analyzing your prompting patterns across 12 sections:

- **Prompt Score** (0-100) across 5 dimensions: specificity, context, first message, clarity, outcome lift
- **Session openers**: success rate by opener type (bug report, feature request, etc.)
- **Context signals**: impact of code blocks, file paths, error pastes on success
- **Sweet spot**: optimal word count range for your prompts
- **Session arc**: how your prompt quality evolves within sessions
- **Before/After**: matched comparisons of similar tasks with different prompt quality
- **Anti-patterns**: 6 patterns to avoid with success rate impact
- **Success recipes**: prompt combos that work best for you
- **Correction trend**: monthly improvement tracking
- **Personalized tips**: 5 data-driven coaching suggestions

### User Profile
A personality and character report analyzing how you communicate, work, and relate to Claude across 15 sections:

- **7 Personality Dimensions** (0-100): Patience, Precision, Warmth, Ambition, Persistence, Autonomy, Night Owl
- **Archetype**: one of 12 coding personas (Architect, Speedrunner, Perfectionist, Whisperer, Commander, etc.)
- **Communication style**: top words/phrases, vocab richness, detected languages
- **Emotional timeline**: nice vs harsh words by hour of day
- **Work rhythm**: 7x24 heatmap, peak hours, weekend %, rhythm label
- **Project loyalty**: monogamous vs polyamorous project distribution
- **Builder identity**: BUILD vs FIX vs EXPLORE trend over time
- **Error personality**: Bulldozer, Adapter, Quitter, or Balanced
- **Delegation style**: micromanager to full delegator gauge
- **Swear report**: vocabulary breakdown with peak hour
- **Quirks**: unique fun facts from your usage data
- **Evolution**: monthly niceness, specificity, success trends
- **AI relationship**: how you treat your AI (Best Friends, Boss & Employee, etc.)

### Soul
A deep personality profile using Big Five trait analysis, narrative prose, and contradiction detection. Explores who you really are beneath your coding habits.

### Portrait
"How AI Sees You" -- a long-form character study written as personal prose. How Claude perceives your personality, communication style, and working patterns.

## Options

```bash
npx claude-entropy --author "Your Name"         # Display name (default: git user.name)
npx claude-entropy --tz 1                        # UTC offset (default: auto-detect)
npx claude-entropy --money 600                   # Subscription cost for ROI slide
npx claude-entropy --money-detail "3 Max"        # Subscription description
npx claude-entropy --sanitize                    # Anonymize project names for sharing
npx claude-entropy --publish                     # Publish to entropy.buildingopen.org
npx claude-entropy prompt-coach                  # Prompt coaching report
npx claude-entropy prompt-coach --sanitize       # Coaching report, anonymized
npx claude-entropy user-profile                  # Personality & character profile
npx claude-entropy soul                          # Deep personality profile (Big Five)
npx claude-entropy portrait                      # "How AI Sees You" character study
npx claude-entropy --help                        # Show all options
```

## Output

Generates `./<report>.html` in your current directory and opens it in your browser (`wrapped.html`, `prompt_coach.html`, or `user_profile.html`).

## How It Works

1. Reads Claude Code session files from `~/.claude/projects/` (JSONL format)
2. Runs 10 pattern analyzers in parallel (pure Python, no pip dependencies)
3. Computes aggregated stats, percentiles, and a personality archetype
4. Generates a single self-contained HTML file with animated slides

All processing happens locally. No data is sent anywhere unless you use `--publish`.

## Requirements

- **Node.js** 14+ (for `npx`)
- **Python** 3.8+ (for analysis, uses only stdlib)
- **Claude Code** session data in `~/.claude/projects/`

Override the data directory with `CLAUDE_PROJECTS_DIR` env var. Supports multiple directories with `:` separator (`;` on Windows):

```bash
# Combine data from multiple machines
CLAUDE_PROJECTS_DIR="/path/to/mac-sessions:/path/to/server-sessions" npx claude-entropy
```

## Privacy

Your session data never leaves your machine. The `--sanitize` flag strips 5 categories of identifying data: project names, prompt examples, swear quotes, uncensored swear words, and machine names. The `--publish` flag uploads only the final HTML report (not raw session data) to a public URL, and always auto-sanitizes regardless of the `--sanitize` flag.

## License

MIT
