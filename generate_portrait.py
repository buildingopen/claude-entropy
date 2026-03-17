#!/usr/bin/env python3
"""
Generate a self-contained portrait.html - "How AI Sees You".

A personal character study written as long-form prose in second person.
Reads like a letter from someone who's watched you work for 1,400 hours.
Minimal charts, mostly narrative prose. Every claim backed by data.
Personal content (projects, people, locations, interests) leads each section.

Outputs dist/portrait.html.
"""

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
# Identity Mining from Config Files (CLAUDE.md, memory files)
# ---------------------------------------------------------------------------

# Paths to check for CLAUDE.md and memory files
_CLAUDE_MD_PATHS = [
    Path.home() / ".claude" / "CLAUDE.md",      # Global instructions
    Path.home() / "CLAUDE.md",                    # Server-level instructions
]

# Memory directory
_MEMORY_DIR = None
for _p in [
    Path.home() / ".claude" / "projects" / "-root" / "memory",
    Path.home() / ".claude" / "projects",
]:
    if _p.is_dir():
        _MEMORY_DIR = _p
        break


def mine_identity_from_config():
    """
    Read CLAUDE.md files and memory files to extract explicit identity themes.
    Returns structured identity data that builders can reference.

    This captures what the user has EXPLICITLY written about their preferences,
    principles, and pet peeves, things that are harder to infer from session data alone.
    """
    identity = {
        "principles": [],           # Engineering principles (KISS, DRY, etc.)
        "communication_style": [],  # How they want to communicate
        "design_values": [],        # Design anti-patterns and preferences
        "pet_peeves": [],           # Things they explicitly hate
        "infrastructure": [],       # Infrastructure philosophy
        "work_methodology": [],     # How they approach work
        "quality_bar": [],          # Quality standards
        "projects_described": [],   # Projects with descriptions from config
        "raw_sections": {},         # Section name -> content for deep mining
    }

    if SANITIZE:
        return identity

    # Read all CLAUDE.md files
    all_config_text = []
    for path in _CLAUDE_MD_PATHS:
        if path.exists():
            try:
                text = path.read_text(errors="replace")
                all_config_text.append(text)
                _parse_claude_md(text, identity)
            except (OSError, PermissionError):
                pass

    # Read select memory files (identity-relevant only, skip credentials/technical)
    if _MEMORY_DIR and _MEMORY_DIR.is_dir():
        identity_files = ["MEMORY.md", "workspace-plan.md", "daily-ai-vision.md"]
        for fname in identity_files:
            fpath = _MEMORY_DIR / fname
            if fpath.exists():
                try:
                    text = fpath.read_text(errors="replace")
                    _parse_memory_file(fname, text, identity)
                except (OSError, PermissionError):
                    pass

    return identity


def _parse_claude_md(text, identity):
    """Extract identity themes from a CLAUDE.md file."""
    lines = text.split("\n")

    # --- Engineering Principles ---
    in_principles = False
    for line in lines:
        if "## Engineering Principles" in line:
            in_principles = True
            continue
        if in_principles:
            if line.startswith("## "):
                break
            if line.strip().startswith("- **"):
                # Extract principle name and description
                m = re.match(r"\s*-\s*\*\*(.+?)\*\*\s*[-–]\s*(.+)", line)
                if m:
                    identity["principles"].append({
                        "name": m.group(1).strip(),
                        "description": m.group(2).strip(),
                    })

    # --- Communication Style (Don't Be Annoying section) ---
    in_comm = False
    for line in lines:
        if "## Don't Be Annoying" in line or "## Communication Standards" in line:
            in_comm = True
            continue
        if in_comm:
            if line.startswith("## ") or line.startswith("---"):
                in_comm = False
                continue
            if line.strip().startswith("- **"):
                m = re.match(r"\s*-\s*\*\*(.+?)\*\*\s*[-–]\s*(.+)", line)
                if m:
                    identity["communication_style"].append({
                        "rule": m.group(1).strip(),
                        "detail": m.group(2).strip(),
                    })

    # --- Design Anti-Patterns ---
    in_design = False
    for line in lines:
        if "## Design Anti-Patterns" in line:
            in_design = True
            continue
        if in_design:
            if line.startswith("## "):
                break
            m = re.match(r"\s*\d+\.\s*\*\*(.+?)\*\*\s*[-–]\s*(.+)", line)
            if m:
                identity["design_values"].append({
                    "rule": m.group(1).strip(),
                    "detail": m.group(2).strip(),
                })

    # --- Quality Standards ---
    in_quality = False
    for line in lines:
        if "## Quality Standards" in line:
            in_quality = True
            continue
        if in_quality:
            if line.startswith("## ") and "Quality" not in line:
                break
            # Capture the 10/10 philosophy
            if "10/10" in line and "Keep working" not in line:
                identity["quality_bar"].append(line.strip().lstrip("- *"))
            if "Keep working" in line:
                identity["quality_bar"].append(line.strip().lstrip("- *"))

    # --- Infrastructure philosophy ---
    in_infra = False
    for line in lines:
        if "## Infrastructure" in line:
            in_infra = True
            continue
        if in_infra:
            if line.startswith("## "):
                break
            # Capture the philosophy lines (not the tables)
            if line.strip().startswith("- ") and "→" in line:
                identity["infrastructure"].append(line.strip().lstrip("- "))

    # --- Work methodology ---
    in_method = False
    for line in lines:
        if "## Read First, Code Later" in line or "## Work Plans" in line or "## Stop and Re-Plan" in line:
            in_method = True
            continue
        if in_method:
            if line.startswith("## ") and "Read First" not in line and "Work Plan" not in line and "Stop" not in line:
                in_method = False
                continue
            if line.strip().startswith("**") and "ratio" in line.lower():
                identity["work_methodology"].append(line.strip().strip("*"))
            elif "detective" in line.lower() or "surgeon" in line.lower():
                identity["work_methodology"].append(line.strip().strip("*"))
            elif "sunk cost" in line.lower():
                identity["work_methodology"].append(line.strip())

    # --- Extract pet peeves from various sections ---
    # Only explicit bans/rejections, not engineering principles
    principle_names = {p["name"].lower() for p in identity["principles"]}
    for line in lines:
        lower = line.lower()
        if "never" in lower and ("say" in lower or "use " in lower) and line.strip().startswith("- **"):
            m = re.match(r"\s*-\s*\*\*(.+?)\*\*\s*[-–]\s*(.+)", line)
            if m:
                rule_name = m.group(1).strip()
                # Skip if it's already captured as an engineering principle
                if rule_name.lower() in principle_names:
                    continue
                identity["pet_peeves"].append({
                    "rule": rule_name,
                    "detail": m.group(2).strip(),
                })

    # Also extract "No X" communication rules as pet peeves
    comm_peeves = [c for c in identity["communication_style"]
                   if c["rule"].lower().startswith("no ") or "banned" in c.get("detail", "").lower()]
    for cp in comm_peeves:
        # Avoid duplicates
        existing = {p["rule"].lower() for p in identity["pet_peeves"]}
        if cp["rule"].lower() not in existing:
            identity["pet_peeves"].append({"rule": cp["rule"], "detail": cp["detail"]})


def _parse_memory_file(fname, text, identity):
    """Extract identity themes from a memory file."""
    if fname == "MEMORY.md":
        # Writing preferences, corrections
        lines = text.split("\n")
        in_writing = False
        for line in lines:
            if "# Writing Preferences" in line:
                in_writing = True
                continue
            if in_writing:
                if line.startswith("# ") and "Writing" not in line:
                    break
                if line.strip().startswith("- **"):
                    m = re.match(r"\s*-\s*\*\*(.+?)\*\*\s*(.+)", line)
                    if m:
                        identity["communication_style"].append({
                            "rule": m.group(1).strip(),
                            "detail": m.group(2).strip(),
                        })

    elif fname == "workspace-plan.md":
        # Extract project list
        lines = text.split("\n")
        for line in lines:
            m = re.match(r"\s*\d+\.\s*\*\*(\w+)\*\*\s*[-–]\s*(.+)", line)
            if m:
                identity["projects_described"].append({
                    "name": m.group(1).strip(),
                    "description": m.group(2).strip(),
                })

    elif fname == "daily-ai-vision.md":
        # Product vision
        lines = text.split("\n")
        for line in lines:
            if line.startswith("**") and "—" in line:
                identity["projects_described"].append({
                    "name": "Brief",
                    "description": line.strip().strip("*"),
                })


# ---------------------------------------------------------------------------
# Personal Content Mining - entity discovery from prompt text
# ---------------------------------------------------------------------------

# Words that look capitalized but are tech terms, not people
TECH_PROPER_NOUNS = frozenset(
    "Docker Chrome React Python GitHub Supabase Vercel Next Tailwind TypeScript "
    "JavaScript Node Vue Angular Svelte Redis Postgres PostgreSQL MySQL SQLite "
    "MongoDB Firebase AWS Azure GCP Lambda CloudFlare Netlify Render Heroku "
    "Prisma Drizzle Express FastAPI Flask Django Rails Spring Kubernetes Helm "
    "Linux Ubuntu Debian Alpine MacOS Windows WSL Homebrew Brew Nix Ansible "
    "Terraform Pulumi Nginx Apache Caddy Traefik GraphQL REST API JSON YAML "
    "TOML Markdown HTML CSS SCSS LESS Webpack Vite Rollup ESBuild Turbo Bun "
    "Deno Rust Go Java Kotlin Swift Dart Flutter Electron Tauri Playwright "
    "Puppeteer Cypress Jest Vitest Mocha Pytest Cargo Maven Gradle NPM PNPM "
    "Yarn Pip Conda Poetry Hatch UV Ruff Black Prettier ESLint Biome "
    "Sentry PostHog Stripe Resend Twilio SendGrid Mailgun Notion Slack Figma "
    "OpenAI Anthropic Claude Gemini Codex GPT Llama Mistral Ollama "
    "Remotion FFmpeg ImageMagick Sharp Chromium Firefox Safari "
    "WhatsApp Telegram Signal Discord Twitter Reddit LinkedIn GitLab "
    "Bitbucket JIRA Confluence Trello Asana Monday Linear Coda Airtable "
    "Zod Yup Joi Ajv Pydantic Celery RabbitMQ Kafka SQS SNS PubSub "
    "Zustand Redux MobX Jotai Recoil XState TanStack SWR Apollo Relay "
    "Storybook Docusaurus Nextra VitePress Astro Gatsby Hugo Jekyll "
    "Neon PlanetScale Turso Upstash Convex Hasura PostgREST "
    "Bash Zsh Fish PowerShell CMD Terminal iTerm Alacritty Warp Kitty "
    "VSCode Neovim Vim Emacs Sublime Cursor Windsurf "
    "Expo EAS Capacitor Ionic "
    "Hono Elysia Nitro Nuxt Remix Qwik SolidJS Preact Alpine HTMX Stimulus "
    "Inngest Trigger Defer QStash BullMQ "
    "Framer Motion GSAP Lottie Three ThreeJS WebGL Canvas SVG "
    "Pinecone Weaviate Qdrant ChromaDB LangChain LlamaIndex AutoGen CrewAI "
    "OAuth JWT SAML SSO PKCE CORS CSRF XSS OWASP Helmet "
    "RFC HTTP HTTPS TCP UDP DNS SMTP IMAP "
    "Google Apple Microsoft Amazon Meta Facebook Instagram YouTube "
    "Gmail Replit Bubble Crawlee Yahoo Wispr".split()
)

# Common words that start sentences (skip when looking for names)
CAPS_STOPWORDS = frozenset(
    # Determiners, pronouns, conjunctions, prepositions, auxiliaries
    "The This That What When Where Which Who How Why Are Is Was Were "
    "Has Had Have Does Did Can Could Would Should Will Shall May Might "
    "Let But And Not Yet Just Also Each Some Any All Both Few Many Much "
    "Most More Less Than Then Now Here There After Before Since While "
    "Until Once Only Even Still Again Too Very So Such No Yes Please "
    "Thanks Thank Great Good Nice Fine Sure Okay Actually Really "
    # Common verbs that start sentences
    "Note Fix Add Update Remove Delete Create Use Run Build Test Check "
    "Set Get Make Tell Send Show Read Write Open Close Start Stop Move "
    "Copy Find Look Call Help Try Keep Need Want Give Take Put Change "
    "Turn Work Done Added Made Found Used Based Step Never Always "
    # Common nouns/adjectives in coding contexts
    "Error Warning Info Debug File Page Session Agent Score Review Issue "
    "Query Table Column Field Value Status Result Output Input Config "
    "Setup Install Deploy Merge Branch Commit Push Pull Request Response "
    "Server Client Route Handler Model View Controller Service Worker "
    "Module Package Import Export Class Method Function Variable Type "
    "String Number Boolean Array Object Interface Schema Format Path "
    "Search Filter Sort Order Group Count Total Average Source Audit "
    "Project Users User Image Backend Frontend Desktop Domain Architecture "
    "Screenshot Description Content Section Component Style Layout Version "
    "System Data Code Line Block Header Footer Button Link Text Color "
    "Primary Default Custom Local Global Public Private Internal External "
    "Main Index Home Profile Settings About Loading Success Failure "
    "Simple First Last Next Previous Current Final Complete "
    "Invalid Missing Required Optional Available Enabled Disabled "
    "Active Inactive Pending Running Completed Failed Deleted "
    "Compliance Runtime Store Everything Anything Nothing Something "
    "Account Post Verification Live Support Skill Components Progress "
    "Wireframe Tools Slide Reply Testing Question Brand Channel "
    "Feature Template Dashboard Platform Provider Production Staging "
    "Endpoint Webhook Callback Token Secret Access Permission Admin "
    "Pipeline Workflow Trigger Action Event Notification Alert Monitor "
    "Analytics Report Summary Overview Detail Record Entry Item "
    "Upload Download Stream Socket Connection Port Host Address "
    "Container Volume Mount Proxy Cache Queue Stack Heap Memory "
    "Thread Pool Batch Chunk Buffer Pipe Fork Spawn "
    "Africa Asia Europe America".split()
)

# ~100 major world cities (single-word only for simple matching,
# multi-word cities listed separately for phrase matching)
_SINGLE_WORD_CITIES = frozenset(
    "Amsterdam Athens Auckland Baghdad Bangkok Barcelona Beijing Berlin Bogota "
    "Boston Brussels Budapest Cairo Caracas Casablanca "
    "Chennai Chicago Copenhagen Dallas Delhi Detroit Dhaka Dubai Dublin "
    "Edinburgh Frankfurt Geneva Guangzhou Hamburg Hanoi Havana Helsinki "
    "Houston Hyderabad Istanbul Jakarta Jeddah "
    "Johannesburg Karachi Kathmandu Kinshasa Kolkata "
    "Lagos Lima Lisbon London Lyon Madrid Manchester Manila "
    "Marrakech Melbourne Miami Milan Montreal Moscow Mumbai "
    "Munich Nairobi Naples Osaka Oslo Ottawa Paris "
    "Perth Philadelphia Porto Prague Riyadh Rome Santiago "
    "Seoul Shanghai Singapore Stockholm Stuttgart Sydney "
    "Taipei Tehran Tokyo Toronto Vancouver Vienna Warsaw "
    "Washington Zurich Bangalore Pune Goa Austin Denver Seattle Portland".split()
)
_MULTI_WORD_CITIES = frozenset([
    "Buenos Aires", "Cape Town", "Hong Kong", "Los Angeles",
    "Mexico City", "New Delhi", "New York", "San Francisco",
])
CITY_SEEDS = _SINGLE_WORD_CITIES | frozenset(
    w for phrase in _MULTI_WORD_CITIES for w in [phrase]
)

# ~50 countries
COUNTRY_SEEDS = frozenset(
    "Afghanistan Argentina Australia Austria Bangladesh Belgium Bolivia Brazil "
    "Cambodia Canada Chile China Colombia Croatia Cuba Denmark Ecuador "
    "Egypt Estonia Ethiopia Finland France Germany Ghana Greece Guatemala "
    "Hungary Iceland India Indonesia Iran Iraq Ireland Israel Italy Jamaica "
    "Japan Jordan Kenya Latvia Lebanon Lithuania Malaysia Mexico Morocco "
    "Netherlands Nigeria Norway Pakistan Panama Peru Philippines "
    "Poland Portugal Romania Russia Scotland Senegal Singapore "
    "Slovenia Spain Sweden Switzerland Taiwan Tanzania Thailand Tunisia Turkey "
    "Uganda Ukraine Uruguay Venezuela Vietnam Wales Zimbabwe".split()
)

# Interest category seed terms
INTEREST_SEEDS = {
    # Only include terms that are unambiguous outside coding contexts.
    # Excluded: "run" (run tests), "training" (model training), "design" (UI design),
    # "library" (code library), "book" (booking), "game" (game theory), etc.
    "fitness": {"marathon", "gym", "workout", "exercise", "cycling", "hiking",
                "swimming", "yoga", "crossfit", "weights", "cardio", "strava",
                "running shoes", "half marathon", "5k", "10k"},
    "music": {"spotify", "playlist", "concert", "festival",
              "keinemusik", "techno", "rave", "dj set",
              "soundcloud", "vinyl", "ableton", "guitar", "piano"},
    "design": {"figma", "typography", "wireframe", "mockup", "prototype",
               "illustration", "photoshop", "canva"},
    "travel": {"travel", "hotel", "airbnb", "passport", "airport",
               "backpack", "hostel", "vacation", "holiday", "tourist",
               "nomad", "expat", "abroad"},
    "food": {"cooking", "recipe", "restaurant", "espresso",
             "barista", "wine", "cocktail", "baking",
             "cuisine", "sushi", "pizza", "brunch"},
    "photography": {"camera", "lens", "lightroom", "drone",
                    "fujifilm", "canon", "nikon"},
    "gaming": {"gaming", "playstation", "xbox", "nintendo", "twitch",
               "esports", "minecraft", "valorant", "steam deck"},
    "reading": {"kindle", "novel", "fiction", "audiobook", "goodreads",
                "reading list", "book club"},
}

# Value detection patterns (regex)
VALUE_PATTERNS = {
    "quality_obsession": [
        r"\b10/10\b", r"\bnot good enough\b", r"\bperfect\b",
        r"\bpolish\b", r"\bquality\b", r"\bpixel.?perfect\b",
        r"\bclean code\b", r"\brefactor\b", r"\bcraft\b",
        r"\bexcellence\b", r"\bmeticulous\b",
    ],
    "shipping_velocity": [
        r"\bship\b", r"\bdeploy\b", r"\blaunch\b", r"\brelease\b",
        r"\bpush to prod\b", r"\bgo live\b", r"\bpublish\b",
        r"\bjust ship\b", r"\bget it out\b",
    ],
    "systematic_thinking": [
        r"\bsystem\b", r"\barchitect\b", r"\bpattern\b",
        r"\bframework\b", r"\bworkflow\b", r"\bpipeline\b",
        r"\bautomation\b", r"\bscalable\b", r"\bmodular\b",
        r"\babstraction\b",
    ],
    "autonomy": [
        r"\bmy own\b", r"\bindependent\b", r"\bautonomy\b",
        r"\bfreedom\b", r"\bself.?hosted\b", r"\bopen.?source\b",
        r"\bown it\b", r"\bcontrol\b",
    ],
    "aesthetics": [
        r"\bbeautiful\b", r"\bclean\b", r"\bminimal\b",
        r"\belegant\b", r"\bsleek\b", r"\bpolished\b",
        r"\baesthetic\b",
    ],
    "user_empathy": [
        r"\buser experience\b", r"\bthe user\b", r"\bcustomer\b",
        r"\bonboarding\b", r"\bfriction\b", r"\bintuitive\b",
        r"\baccessib\b", r"\busability\b",
    ],
}

# Self-reference patterns
SELF_PATTERNS = [
    r"(?:i am|i'm)\s+(?:a\s+)?(\w[\w\s]{2,30}?)(?:\.|,|!|\band\b)",
    r"(?:my goal|my vision|my plan|my dream)\s+is\s+(.{5,80}?)(?:\.|!)",
    r"(?:i believe|i think|i feel)\s+(?:that\s+)?(.{5,80}?)(?:\.|!)",
    r"(?:i (?:really )?(?:love|enjoy|hate|despise))\s+(.{3,50}?)(?:\.|,|!)",
    r"(?:i've been|i have been|i was)\s+(.{5,60}?)(?:\.|,|!)",
]

# Goal extraction patterns
GOAL_PATTERNS = [
    r"(?:i want to|i wanna)\s+(.{5,100}?)(?:\.|!|$)",
    r"(?:the goal is|our goal is)\s+(.{5,100}?)(?:\.|!|$)",
    r"(?:we're building|i'm building)\s+(.{5,100}?)(?:\.|!|$)",
    r"(?:trying to)\s+(.{5,80}?)(?:\.|!|$)",
    r"(?:i need to)\s+(.{5,80}?)(?:\.|!|$)",
]


def _extract_context(text, start, end, window=150):
    """Extract surrounding sentence context around a match."""
    ctx_start = max(0, start - window // 2)
    ctx_end = min(len(text), end + window // 2)
    # Try to snap to sentence start
    for i in range(ctx_start, max(0, ctx_start - 50), -1):
        if text[i] in ".!?\n":
            ctx_start = i + 1
            break
    # Try to snap to sentence end
    for i in range(ctx_end, min(len(text), ctx_end + 50)):
        if text[i] in ".!?\n":
            ctx_end = i + 1
            break
    return text[ctx_start:ctx_end].strip()


def mine_personal_content(data):
    """
    Scan all user texts for personal entities: people, locations, interests,
    ventures, values, self-references, and goals. No external APIs needed.

    Performance: optimized for 12K+ texts / 6MB+ joined text.
    Uses str.count() for simple seeds, regex only where needed.
    """
    all_texts = data["all_user_texts"]
    sessions = data["sessions"]

    if not all_texts:
        return {
            "people": [], "locations": {}, "location_contexts": {},
            "interests": {}, "ventures": [], "values": Counter(),
            "self_references": [], "goals": [],
        }

    joined_lower = "\n".join(t.lower() for t in all_texts)

    # Collect project names early so we can filter them from people detection
    project_names = frozenset(s["project"] for s in sessions)

    # --- People: capitalized words in relational contexts ---
    people_counter = Counter()
    people_contexts = defaultdict(list)

    # First pass: collect candidate names (single capitalized words)
    single_name_pat = re.compile(r"\b([A-Z][a-z]{2,})\b")
    candidate_names = Counter()
    # Track unique text indices containing each name (for relational check + context)
    name_texts = defaultdict(list)
    _name_text_set = defaultdict(set)  # for dedup
    for i, text in enumerate(all_texts):
        for m in single_name_pat.finditer(text):
            name = m.group(1)
            if name in TECH_PROPER_NOUNS or name in CAPS_STOPWORDS:
                continue
            if name in CITY_SEEDS or name in COUNTRY_SEEDS:
                continue
            if name in project_names:
                continue
            if len(name) < 4:
                continue
            candidate_names[name] += 1
            if i not in _name_text_set[name]:
                name_texts[name].append(i)
                _name_text_set[name].add(i)
    del _name_text_set

    # Second pass: require strong relational context to confirm it's a person.
    # Patterns must be tight: "@name" (not @name-library), "tell name" (not "ask question").
    _PRONOUN_SET = {"they", "them", "you", "your", "we", "our", "it", "its", "he", "she", "who"}
    for name, count in candidate_names.items():
        if count < 3:
            continue
        name_lower = name.lower()
        # Skip common pronouns/words that match person patterns generically
        if name_lower in _PRONOUN_SET:
            continue
        # Skip if lowercase form massively outnumbers capitalized (common word, not a name).
        # Names like "Federico" appear lowercase in paths but ratio stays under 8x.
        # Words like "tools", "slide" have 50x+ ratio.
        lower_count = joined_lower.count(" " + name_lower + " ")
        if lower_count > count * 8:
            continue
        name_esc = re.escape(name_lower)
        # Strong person indicators:
        # 1. Direct address: "tell gourav" (but not "ask question")
        # 2. "X said/says" (but not "they said")
        _person_pats = [
            re.compile(r"\b(?:tell|ping|notify|remind|inform|talk to|meet with|meeting with|called|told|sent to)\s+" + name_esc + r"\b"),
            re.compile(r"\b(?:ask|update|email|message)\s+" + name_esc + r"\s+(?:about|to|if|whether|for)\b"),
            re.compile(r"\b" + name_esc + r"\s+(?:said|says|asked|told|mentioned|suggested|wants|needs|thinks)\b"),
        ]
        has_relational = False
        for idx in name_texts[name]:
            text_lower = all_texts[idx].lower()
            for pat in _person_pats:
                if pat.search(text_lower):
                    has_relational = True
                    break
            if has_relational:
                break
        if has_relational:
            people_counter[name] = count

        # Extract contexts from stored text indices
        if name in people_counter:
            for idx in name_texts[name]:
                if len(people_contexts[name]) >= 3:
                    break
                text = all_texts[idx]
                pos = text.find(name)
                if pos >= 0:
                    try:
                        ctx = _extract_context(text, pos, pos + len(name))
                        if ctx:
                            people_contexts[name].append(ctx)
                    except (IndexError, ValueError):
                        pass

    # Merge possessive/plural forms: "Federicos" -> "Federico" if both exist
    merged_away = set()
    for name in list(people_counter):
        if name.endswith("s") and name[:-1] in people_counter:
            people_counter[name[:-1]] += people_counter[name]
            people_contexts[name[:-1]].extend(people_contexts.get(name, []))
            merged_away.add(name)
    for name in merged_away:
        del people_counter[name]

    # --- Locations: use str.count() on lowered text for speed ---
    location_counter = Counter()
    location_contexts = defaultdict(list)
    all_location_seeds = CITY_SEEDS | COUNTRY_SEEDS
    for loc in all_location_seeds:
        loc_lower = loc.lower()
        # Use simple string count (much faster than regex per-seed)
        cnt = joined_lower.count(loc_lower)
        if cnt == 0:
            continue
        # Verify at least one is a word boundary match (not substring of another word)
        # by checking a few texts
        real_count = 0
        pat = re.compile(r"\b" + re.escape(loc) + r"\b", re.IGNORECASE)
        for text in all_texts:
            if loc_lower in text.lower():
                real_count += len(pat.findall(text))
                if real_count > 0 and len(location_contexts[loc]) < 3:
                    for m in pat.finditer(text):
                        try:
                            ctx = _extract_context(text, m.start(), m.end())
                            if ctx:
                                location_contexts[loc].append(ctx)
                        except (IndexError, ValueError):
                            pass
                        if len(location_contexts[loc]) >= 3:
                            break
        if real_count > 0:
            location_counter[loc] = real_count

    # --- Interests: use str.count() for speed ---
    interests = {}
    for category, seeds in INTEREST_SEEDS.items():
        total = 0
        matched_terms = Counter()
        for seed in seeds:
            seed_lower = seed.lower()
            # Quick substring check first
            cnt = joined_lower.count(seed_lower)
            if cnt > 0:
                matched_terms[seed] = cnt
                total += cnt
        if total > 0:
            interests[category] = {"total": total, "terms": dict(matched_terms.most_common(5))}

    # --- Ventures (from project data + text mentions) ---
    project_counts = Counter(s["project"] for s in sessions)
    GENERIC_PROJECTS = {"AX41 General", "Mac General", "General", "Unknown", "unknown"}
    ventures = []
    for proj, sess_count in project_counts.most_common(20):
        if proj in GENERIC_PROJECTS:
            continue
        text_mentions = 0
        proj_lower = proj.lower()
        if len(proj_lower) > 2:
            text_mentions = joined_lower.count(proj_lower)
        proj_sessions = [s for s in sessions if s["project"] == proj]
        cat_counts = Counter(s["category"] for s in proj_sessions)
        dominant_cat = cat_counts.most_common(1)[0][0] if cat_counts else "BUILD"
        success_count = sum(1 for s in proj_sessions if s["outcome"] in ("SUCCESS", "PARTIAL_SUCCESS"))
        success_rate = success_count / max(len(proj_sessions), 1) * 100

        ventures.append({
            "name": proj,
            "sessions": sess_count,
            "text_mentions": text_mentions,
            "dominant_category": dominant_cat,
            "success_rate": round(success_rate, 1),
        })

    # --- Values: compile patterns once, search per-text for speed ---
    values = Counter()
    compiled_value_pats = []
    for value_name, patterns in VALUE_PATTERNS.items():
        for pat_str in patterns:
            compiled_value_pats.append((value_name, re.compile(pat_str, re.IGNORECASE)))
    for text in all_texts:
        text_lower = text.lower()
        for value_name, pat in compiled_value_pats:
            values[value_name] += len(pat.findall(text))

    # --- Self-references: search per-text ---
    self_references = []
    compiled_self_pats = [re.compile(p, re.IGNORECASE) for p in SELF_PATTERNS]
    for text in all_texts:
        if len(self_references) >= 20:
            break
        for pat in compiled_self_pats:
            for m in pat.finditer(text):
                snippet = m.group(1).strip() if m.lastindex else m.group(0).strip()
                if len(snippet) > 3 and snippet not in self_references:
                    self_references.append(snippet)
                if len(self_references) >= 20:
                    break

    # --- Goals: search per-text ---
    goals = []
    compiled_goal_pats = [re.compile(p, re.IGNORECASE | re.MULTILINE) for p in GOAL_PATTERNS]
    for text in all_texts:
        if len(goals) >= 30:
            break
        for pat in compiled_goal_pats:
            for m in pat.finditer(text):
                snippet = m.group(1).strip() if m.lastindex else m.group(0).strip()
                if any(c in snippet for c in ["{", "}", "()", "=>", "import ", "const ", "def "]):
                    continue
                if len(snippet) > 5 and snippet not in goals:
                    goals.append(snippet)
                if len(goals) >= 30:
                    break

    return {
        "people": [
            {"name": name, "count": count, "contexts": people_contexts.get(name, [])}
            for name, count in people_counter.most_common(20)
        ],
        "locations": dict(location_counter.most_common(15)),
        "location_contexts": dict(location_contexts),
        "interests": interests,
        "ventures": ventures,
        "values": values,
        "self_references": self_references[:15],
        "goals": goals[:20],
    }


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
# Narrative Builders - one per section (personal content leads, stats support)
# ---------------------------------------------------------------------------
def _proj_list(top_projects, limit=5):
    """Format top projects as a readable list."""
    parts = []
    for name, count in top_projects[:limit]:
        if SANITIZE:
            name = f"Project {len(parts) + 1}"
        parts.append(f"{name} ({count} sessions)")
    return ", ".join(parts)


def _sanitize_name(name, idx):
    """Replace a person name with Person A/B/C when sanitizing."""
    labels = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    return f"Person {labels[idx % len(labels)]}"


def _sanitize_location(loc, idx):
    """Replace a location with Location 1/2/3 when sanitizing."""
    return f"Location {idx + 1}"


def _venture_list(ventures, limit=5):
    """Format ventures for narrative use."""
    parts = []
    for v in ventures[:limit]:
        name = v["name"]
        if SANITIZE:
            name = f"Project {len(parts) + 1}"
        parts.append(f"{name} ({v['sessions']} sessions, {v['dominant_category'].lower()}-focused)")
    return ", ".join(parts)


def _people_summary(personal, limit=5):
    """Format people list for narrative, respecting sanitization."""
    people = personal.get("people", [])
    if not people:
        return ""
    parts = []
    for i, p in enumerate(people[:limit]):
        name = _sanitize_name(p["name"], i) if SANITIZE else p["name"]
        parts.append(f"{name} ({p['count']} mentions)")
    return ", ".join(parts)


def _location_summary(personal, limit=5):
    """Format location list for narrative, respecting sanitization."""
    locations = personal.get("locations", {})
    if not locations:
        return ""
    parts = []
    for i, (loc, count) in enumerate(sorted(locations.items(), key=lambda x: -x[1])[:limit]):
        loc_name = _sanitize_location(loc, i) if SANITIZE else loc
        parts.append(f"{loc_name} ({count} mentions)")
    return ", ".join(parts)


def _interest_summary(personal):
    """Format interests for narrative."""
    interests = personal.get("interests", {})
    if not interests:
        return ""
    sorted_interests = sorted(interests.items(), key=lambda x: -x[1]["total"])
    parts = []
    for cat, info in sorted_interests[:4]:
        top_terms = list(info["terms"].keys())[:3]
        parts.append(f"{cat} ({', '.join(top_terms)})")
    return ", ".join(parts)


def _is_real_goal(text):
    """Filter out task-level instructions that got mined as goals."""
    lower = text.lower()
    # Too short to be a real goal
    if len(text.split()) < 5:
        return False
    # Task-level language
    task_markers = ["load a", "get a ", "fix the", "run the", "open the", "check the",
                    "test the", "use the", "set the", "add the", "update the",
                    "see the", "find the", "read the", "send the", "copy the",
                    "install", "click", "navigate", "deploy the", "push the",
                    "revert", "restart", "ssh ", "import ", "fetch ", "curl ",
                    "book the", "let's", "lets ", "prio ",
                    "show me", "see proof", "make sure", "try the", "start the",
                    "move the", "put the", "change the", "remove the", "delete the",
                    "create the", "write the", "edit the", "verify"]
    if any(lower.startswith(m) or m in lower for m in task_markers):
        return False
    # Reject if it has semicolons (multiple task instructions)
    if ";" in text:
        return False
    # Reject if it's clearly a debugging/testing instruction
    debug_markers = ["password", "login", "endpoint", "sign out", "sign in",
                     "clear the", "enter the", "type a", "type the",
                     "scroll", "render", "deploy to", "on the .* page",
                     "wrong account", "rate limit", "convert free"]
    for m in debug_markers:
        if re.search(m, lower):
            return False
    return True


def _is_real_self_ref(text):
    """Filter out task fragments that got mined as self-references."""
    lower = text.lower()
    if len(text.split()) < 3:
        return False
    # Task fragments, not identity
    noise = ["about to", "going to", "just ", "wrong ", "seeing ", "trying to",
             "looking at", "testing", "checking", "waiting", "debugging",
             "to run", "to test", "to check", "to see", "to fix", "to get",
             "to open", "to load", "to read", "to send", "to push",
             "acepted", "accepted", "still on", "on the "]
    if any(lower.startswith(n) for n in noise):
        return False
    # Must contain identity-like language, not page navigation
    identity_signals = ["build", "founder", "developer", "engineer", "designer",
                        "entrepreneur", "freelanc", "consultant", "solo",
                        "bangalore", "berlin", "italian", "german"]
    # If it's short enough (< 6 words), require an identity signal
    if len(text.split()) < 6 and not any(s in lower for s in identity_signals):
        return False
    return True


def _filter_people(personal):
    """Remove the user's own name from the people list."""
    author_lower = (AUTHOR_NAME or "").lower().split()
    people = personal.get("people", [])
    return [p for p in people if p["name"].lower() not in author_lower]


def _filter_ventures(ventures):
    """Remove temp/worktree ventures."""
    return [v for v in ventures if not v["name"].startswith("-tmp-")
            and not v["name"].startswith("tmp-")
            and "wt-" not in v["name"]
            and v["sessions"] >= 3]


def build_how_you_see_the_world(s, personal, identity=None):
    """Section 1: Philosophy, beliefs about building, work, autonomy."""
    parts = []
    identity = identity or {}

    values = personal.get("values", Counter())
    self_refs = [r for r in personal.get("self_references", []) if _is_real_self_ref(r)]
    goals = [g for g in personal.get("goals", []) if _is_real_goal(g)]
    ventures = _filter_ventures(personal.get("ventures", []))
    principles = identity.get("principles", [])

    # Lead with worldview inferred from values
    autonomy_score = values.get("autonomy", 0)
    systematic_score = values.get("systematic_thinking", 0)
    quality_score = values.get("quality_obsession", 0)

    if autonomy_score > 10 and len(ventures) > 3:
        parts.append("You believe one person with the right tools can outperform a team.")
        parts.append(f"That's not a slogan, it's a pattern: {len(ventures)} projects, most of them solo, built with self-hosted infrastructure and open-source conviction.")
    elif autonomy_score > 5:
        parts.append("Independence isn't just a preference for you, it's a principle.")
        if s["total_hours"] > 100:
            parts.append(f"Across {s['total_hours']:.0f} hours of work, you've consistently chosen control over convenience.")
    elif systematic_score > 10:
        parts.append("You see the world in systems.")
        parts.append("Not individual problems to solve, but patterns to build infrastructure around.")
    else:
        parts.append("Your worldview shows up in how you work, not what you say about it.")

    # Self-references that reveal beliefs (only strong identity claims)
    if self_refs and not SANITIZE:
        identity_keywords = {"builder", "founder", "developer", "engineer", "solo",
                             "entrepreneur", "freelanc", "consultant", "creator"}
        belief_refs = [r for r in self_refs
                       if len(r.split()) > 2 and len(r.split()) < 10
                       and any(k in r.lower() for k in identity_keywords)][:2]
        if belief_refs:
            parts.append(f"You've described yourself as \"{belief_refs[0]}\", and that self-image runs through everything you build.")

    # Open-source / building-in-public pattern
    if autonomy_score > 5 and len(ventures) > 2:
        open_pattern = any("open" in (v["name"].lower() if not SANITIZE else "") for v in ventures)
        if open_pattern and not SANITIZE:
            open_projects = [v["name"] for v in ventures if "open" in v["name"].lower()][:3]
            parts.append(f"The naming alone tells a story: {', '.join(open_projects)}. Building in the open isn't marketing for you, it's worldview.")

    # Systematic thinking as philosophy
    if systematic_score > 15:
        parts.append(f"You think in frameworks and workflows. Your language is full of systems language, and your projects reflect it: you don't solve problems once, you build the machine that solves them.")
    elif systematic_score > 5:
        parts.append("There's a systems thinker underneath: you reach for patterns, pipelines, and automation before manual fixes.")

    # Engineering principles from CLAUDE.md
    if principles and len(principles) >= 3:
        # Pick 2-3 principles that reveal worldview
        worldview_principles = [p for p in principles if p["name"].lower() in
                                {"engine, not template", "root cause, not quick fix", "kiss",
                                 "fail fast", "least surprise", "never hardcode",
                                 "check existing before creating", "incremental, not big bang"}]
        if worldview_principles:
            names = [p["name"] for p in worldview_principles[:3]]
            parts.append(f"Your engineering philosophy is explicit: {', '.join(names)}. These aren't aspirational, they're codified rules you enforce on every session.")

    # Quality as worldview, not metric
    if quality_score > 20:
        parts.append("Good enough isn't in your vocabulary. The relentless push toward quality isn't perfectionism, it's a belief that craft matters, that the details are the product.")
    elif quality_score > 10:
        parts.append("You care about getting things right, not just getting them done.")

    return " ".join(parts)


def build_what_you_care_about(s, personal, identity=None):
    """Section 2: The deeper WHY behind the projects, the connective tissue."""
    parts = []
    identity = identity or {}

    ventures = _filter_ventures(personal.get("ventures", []))
    interests = personal.get("interests", {})
    values = personal.get("values", Counter())
    goals = [g for g in personal.get("goals", []) if _is_real_goal(g)]

    # Lead with the connective tissue, not the project list
    top_values = values.most_common(3)
    _VALUE_LABELS = {
        "autonomy": "doing things your own way",
        "systematic_thinking": "building systems instead of one-offs",
        "shipping_velocity": "getting things into the world fast",
        "quality_obsession": "making things right, not just done",
        "aesthetics": "how things look and feel",
        "user_empathy": "caring about who uses what you build",
    }
    if len(ventures) > 3 and top_values and top_values[0][1] > 5:
        val_labels = [_VALUE_LABELS.get(v[0], v[0].replace("_", " ")) for v in top_values]
        parts.append(f"Across {len(ventures)} projects, the same thread keeps appearing: {', '.join(val_labels)}.")
        parts.append("That's not a portfolio, it's a pattern. Every project is a different angle on the same set of beliefs.")
    elif len(ventures) > 1:
        parts.append(f"You care about more than one thing, and you're not pretending otherwise.")
        if top_values and top_values[0][1] > 5:
            label = _VALUE_LABELS.get(top_values[0][0], top_values[0][0].replace("_", " "))
            parts.append(f"But look closer and there's a common thread: {label}.")
    elif len(ventures) == 1 and not SANITIZE:
        parts.append(f"Your energy is concentrated: {ventures[0]['name']} gets everything.")
    else:
        parts.append("What you care about shows up in how you spend your time, not in what you declare.")

    # Interests as what matters beyond code
    if interests:
        sorted_interests = sorted(interests.items(), key=lambda x: -x[1]["total"])
        lifestyle = [(k, v) for k, v in sorted_interests if k in {"fitness", "music", "food", "travel", "photography", "gaming", "reading"}]
        if lifestyle:
            top = lifestyle[0]
            terms = list(top[1]["terms"].keys())[:2]
            parts.append(f"{top[0].capitalize()} ({', '.join(terms)}) isn't a side interest. It's all over your conversations.")
            if len(lifestyle) > 1:
                others = [l[0] for l in lifestyle[1:3]]
                parts.append(f"Same with {' and '.join(others)}. You're not just a builder, you have a life outside the terminal.")

    # Goals as deeper motivation
    if goals and not SANITIZE:
        meaningful = [g for g in goals if len(g.split()) > 4][:2]
        if meaningful:
            parts.append(f"In your own words: \"{meaningful[0]}\". That's not a task, it's what gets you out of bed.")

    # What drives the work
    if s["build_pct"] > 50:
        parts.append(f"Creation is the default: {s['build_pct']:.0f}% of your sessions are building something new, not maintaining what exists.")
    if s["deploy_count"] > 50:
        parts.append(f"And you don't hoard what you build. You've shipped it {s['deploy_count']:,} times.")

    if s["total_goal_phrases"] > 20:
        gp = s["goal_phrases"]
        if gp.get("want to", 0) > gp.get("need to", 0) * 2:
            parts.append("The language gives it away: you say \"want to\" far more than \"need to.\" This is desire, not obligation.")
        elif gp.get("need to", 0) > gp.get("want to", 0):
            parts.append("You frame what you care about as necessities, not desires. The work feels like responsibility.")

    return " ".join(parts)


def build_your_mission(s, personal, identity=None):
    """Section 3: Where all of this is going. The arc, what keeps getting rebuilt."""
    parts = []
    identity = identity or {}

    goals = [g for g in personal.get("goals", []) if _is_real_goal(g)]
    ventures = _filter_ventures(personal.get("ventures", []))
    values = personal.get("values", Counter())
    self_refs = [r for r in personal.get("self_references", []) if _is_real_self_ref(r)]

    # The arc: what do the projects have in common?
    if len(ventures) > 3:
        build_ventures = [v for v in ventures if v["dominant_category"] == "BUILD"]
        if len(build_ventures) > 2:
            if not SANITIZE:
                names = [v["name"] for v in build_ventures[:4]]
                parts.append(f"Look at what you keep building: {', '.join(names)}.")
            else:
                parts.append(f"You keep building. {len(build_ventures)} active creation projects, not maintenance.")
            parts.append("The mission isn't stated anywhere, but it's obvious from the pattern: you're building tools that give individuals power.")
        else:
            parts.append(f"Across {len(ventures)} projects, a direction emerges even if you haven't named it.")
    elif len(ventures) > 0:
        if not SANITIZE:
            parts.append(f"Your focus on {ventures[0]['name']} ({ventures[0]['sessions']} sessions) tells a clear story about where your energy goes.")
        else:
            parts.append(f"Your primary project ({ventures[0]['sessions']} sessions) shows a clear direction.")

    # Goals as repeated aspirations (only if multiple, to avoid repeating section 2)
    if goals and not SANITIZE:
        meaningful = [g for g in goals if len(g.split()) > 4][:3]
        if len(meaningful) >= 2:
            parts.append(f"Your goals keep circling the same territory: \"{meaningful[0]}\" and \"{meaningful[1]}\". These aren't one-off tasks, they're the mission restated in different ways.")

    # What keeps getting rebuilt (venture trajectory)
    if len(ventures) > 3:
        categories = Counter(v["dominant_category"] for v in ventures)
        if categories.get("BUILD", 0) > categories.get("FIX", 0) * 2:
            parts.append("You're not maintaining the past, you're building the future. Most of your projects are in creation mode, not maintenance.")
        total_sessions = sum(v["sessions"] for v in ventures)
        if total_sessions > 100:
            parts.append(f"With {total_sessions} sessions spread across your ventures, this isn't a hobby. It's a body of work.")

    # Self-references about mission/identity
    if self_refs and not SANITIZE:
        mission_refs = [r for r in self_refs if any(w in r.lower() for w in ["build", "creat", "found", "launch", "ship"])][:2]
        if mission_refs:
            parts.append(f"You've called yourself \"{mission_refs[0]}\". That's the mission in a sentence.")

    # Values as direction
    shipping_score = values.get("shipping_velocity", 0)
    user_empathy = values.get("user_empathy", 0)
    if shipping_score > 10 and user_empathy > 5:
        parts.append("The direction is clear: build things that reach people, and get them out fast. Shipping isn't a step in your process, it's the point.")
    elif shipping_score > 15:
        parts.append(f"You've shipped {s['deploy_count']:,} times. The mission is in the doing, not the planning.")

    if s["success_pct"] > 70 and s["total_hours"] > 100:
        parts.append(f"And you're making it work: {s['success_pct']:.0f}% success rate across {s['total_hours']:.0f} hours of focused effort.")

    return " ".join(parts)


def build_your_vibe(s, personal, identity=None):
    """Section 4: Energy, aesthetic, cultural references, how you show up."""
    parts = []
    identity = identity or {}

    locations = personal.get("locations", {})
    interests = personal.get("interests", {})
    values = personal.get("values", Counter())
    comm_style = identity.get("communication_style", [])

    # Communication style as vibe
    if s["avg_words_per_prompt"] < 15:
        parts.append("You talk like you text: short, direct, no filler.")
        parts.append("Every word earns its place. You don't explain what's obvious, you don't soften what's clear.")
    elif s["avg_words_per_prompt"] < 30:
        parts.append("Your communication style is direct without being terse. You give enough context to be useful, then stop.")
    elif s["avg_words_per_prompt"] > 80:
        parts.append("You communicate in depth. Not verbose, but thorough, someone who thinks by writing long-form.")
    else:
        parts.append(f"You write at a natural pace, around {s['avg_words_per_prompt']:.0f} words per thought. Clear, not rushed, not padded.")

    # Cultural identity from locations
    if locations and not SANITIZE:
        top_locs = sorted(locations.items(), key=lambda x: -x[1])[:3]
        primary = top_locs[0][0]
        parts.append(f"{primary} energy runs through your work.")
        if len(top_locs) >= 2:
            parts.append(f"With {top_locs[1][0]} as a second reference point, you carry a geography that shapes how you think and build.")
    elif locations and SANITIZE:
        parts.append(f"Your geographic identity spans {len(locations)} places, grounding your digital work in real-world context.")

    # Music/aesthetic interests as vibe
    music_interest = interests.get("music", {})
    if music_interest and music_interest.get("total", 0) > 5:
        terms = list(music_interest.get("terms", {}).keys())[:3]
        parts.append(f"Your taste shows up in the data: {', '.join(terms)}. That aesthetic, clean, direct, rhythmic, mirrors how you build.")

    # Communication philosophy from config
    if comm_style:
        directness_rules = [c for c in comm_style if any(k in c.get("rule", "").lower() for k in ["just do it", "be direct", "be concise", "no confirmation"])]
        if directness_rules:
            parts.append("Your communication rules are codified: no preambles, no filler, no \"would you like me to.\" You've written explicit instructions banning pleasantries and requiring directness. The vibe isn't accidental, it's designed.")

    # Aesthetic values
    aesthetic_score = values.get("aesthetics", 0)
    design_vals = identity.get("design_values", [])
    if design_vals:
        anti_patterns = [d["rule"] for d in design_vals if "emoji" in d["rule"].lower() or "slop" in d.get("detail", "").lower() or "ai" in d.get("detail", "").lower()]
        if anti_patterns:
            parts.append("Design sensibility matters to you. Not decoration, but the feel of things, the gap between functional and beautiful. You've explicitly banned emojis, colored borders, gradient overuse, anything that smells like AI-generated design.")
        elif aesthetic_score > 5:
            parts.append("Design sensibility matters to you. Not decoration, but the feel of things, the gap between functional and beautiful.")
    elif aesthetic_score > 10:
        parts.append("Design sensibility matters to you. Not decoration, but the feel of things, the gap between functional and beautiful.")
    elif aesthetic_score > 5:
        parts.append("You notice when things look right. Aesthetics aren't an afterthought.")

    # Directness / niceness as social vibe
    if s["avg_niceness"] < 4:
        parts.append("Socially, you're all signal, no noise. No pleasantries, no warm-up, straight to what matters.")
    elif s["avg_niceness"] < 6:
        parts.append("You're polite but efficient. The warmth is real but never at the cost of clarity.")
    elif s["avg_niceness"] > 7:
        parts.append("You bring warmth to interactions that don't require it. That's character, not strategy.")

    # Time-of-day as energy signature
    if s["night_session_pct"] > 40:
        parts.append(f"You come alive at night. {s['night_session_pct']:.0f}% of your sessions happen after dark, and that's not a schedule, it's a rhythm.")
    elif s["morning_session_pct"] > 40:
        parts.append(f"Morning person. {s['morning_session_pct']:.0f}% of your work happens before noon, riding the first energy of the day.")

    # Weekend habits as lifestyle signal
    if s["weekend_pct"] > 40:
        parts.append("Weekends don't mean off. The work continues because you want it to, not because someone's making you.")
    elif s["weekend_pct"] < 10:
        parts.append("You protect your weekends. The work gets boundaries.")

    return " ".join(parts)


def build_what_you_love(s, personal, identity=None):
    """Section 5: Things that light you up. Shipping, design, interests, what triggers excitement."""
    parts = []
    identity = identity or {}

    interests = personal.get("interests", {})
    values = personal.get("values", Counter())
    ventures = _filter_ventures(personal.get("ventures", []))

    # Shipping as love
    shipping_score = values.get("shipping_velocity", 0)
    if shipping_score > 15 or s["deploy_count"] > 50:
        parts.append(f"You love shipping. Not in the abstract, motivational-poster way, but in the way someone who has deployed {s['deploy_count']:,} times loves it. The moment something goes live is clearly where the energy peaks.")
    elif shipping_score > 5 or s["deploy_count"] > 10:
        parts.append(f"Getting things out the door matters to you. You've shipped {s['deploy_count']} times, and the language around launches carries real energy.")

    # Quality / craft as love
    quality_score = values.get("quality_obsession", 0)
    aesthetic_score = values.get("aesthetics", 0)
    if quality_score > 15 and aesthetic_score > 5:
        parts.append("You love things that are well-made. Clean design, polished interfaces, code that reads well. The craft matters as much as the outcome.")
    elif quality_score > 10:
        parts.append("Getting it right gives you energy. You keep pushing past good enough because the gap between fine and excellent is where you come alive.")

    # Building from scratch
    if s["build_pct"] > 50 and len(ventures) > 2:
        parts.append(f"Starting things from zero lights you up. {s['build_pct']:.0f}% of your sessions are building new things, and you keep starting new projects when you could be polishing old ones.")

    # Interests with high engagement
    if interests:
        sorted_interests = sorted(interests.items(), key=lambda x: -x[1]["total"])
        high_interests = [(cat, info) for cat, info in sorted_interests if info["total"] > 10]
        low_interests = [(cat, info) for cat, info in sorted_interests if 3 < info["total"] <= 10]

        if len(high_interests) >= 2:
            first = high_interests[0]
            terms_first = list(first[1]["terms"].keys())[:2]
            rest_names = [cat for cat, _ in high_interests[1:3]]
            parts.append(f"{first[0].capitalize()} ({', '.join(terms_first)}), {', '.join(rest_names)}: these aren't casual mentions. They show up hundreds of times in your conversations, woven into how you think and talk.")
        elif high_interests:
            cat, info = high_interests[0]
            terms = list(info["terms"].keys())[:2]
            parts.append(f"{cat.capitalize()} ({', '.join(terms)}) is a real part of your life, not a side interest.")

        if low_interests:
            low_names = [cat for cat, _ in low_interests[:3]]
            parts.append(f"And then there's {', '.join(low_names)}, quieter but real.")

    # Ventures with high success as things that energize
    if ventures and not SANITIZE:
        high_energy = [v for v in ventures if v["sessions"] > 10 and v["success_rate"] > 70]
        if high_energy:
            names = [v["name"] for v in high_energy[:2]]
            parts.append(f"The projects where you're most alive: {', '.join(names)}. High engagement, high success. That's what flow looks like in data.")

    # Deep work as love signal
    if s["avg_duration"] > 60:
        parts.append(f"Your average session runs {s['avg_duration']:.0f} minutes. You don't check in, you sit down and go deep. That kind of focus is its own form of love for the work.")
    elif s["max_streak"] > 14:
        parts.append(f"A {s['max_streak']}-day streak says everything. You don't do this because you have to.")

    return " ".join(parts)


def build_what_you_cant_stand(s, personal, identity=None):
    """Section 6: Pet peeves, rejections. What frustration data reveals as preferences."""
    parts = []
    identity = identity or {}

    values = personal.get("values", Counter())
    ventures = _filter_ventures(personal.get("ventures", []))
    pet_peeves = identity.get("pet_peeves", [])
    design_vals = identity.get("design_values", [])

    # Over-engineering (from correction patterns)
    if s["correction_rate"] > 10:
        parts.append("You can't stand sloppy work. When output isn't right, you fix it immediately, no matter how small the issue. You've corrected course over a thousand times across your sessions.")
    elif s["correction_rate"] > 5:
        parts.append("When something isn't right, you can't leave it alone. That's not indecisiveness, it's standards.")

    # Frustration patterns as pet peeves
    if s["frustration_per_session"] > 1:
        parts.append("You don't suffer broken things quietly. Frustration is a regular presence in your sessions.")
        if s["all_caps_count"] > 50:
            parts.append("The ALL_CAPS moments are emphasis, not tantrums. When something repeatedly breaks, your patience has a clear limit.")
    elif s["frustration_per_session"] > 0.3:
        parts.append("You have a clear threshold for things that don't work. Once it's crossed, the tone shifts.")

    # Things breaking repeatedly
    if s["retried_pct"] > 50 and s["total_errors"] > 10:
        parts.append("Repeated failures clearly get under your skin. When the same approach fails and you retry anyway, it's not optimism, it's frustration channeled into persistence.")

    # Being asked for obvious things
    quality_score = values.get("quality_obsession", 0)
    if s["question_ratio"] < 5 and s["avg_spec"] > 6:
        parts.append("You give clear, specific instructions. The implication: you can't stand being asked to clarify things that were already obvious.")
    elif s["avg_spec"] > 7:
        parts.append("Your instructions are precise. You front-load context to avoid back-and-forth, which says a lot about how you feel about unnecessary clarification.")

    # Explicit pet peeves from config
    if pet_peeves and not SANITIZE:
        peeve_names = [p["rule"] for p in pet_peeves[:4]]
        if peeve_names:
            parts.append(f"Your config files spell out what you reject: {', '.join(peeve_names)}. These aren't guidelines, they're battle scars from watching AI get it wrong.")

    # AI slop / low quality output
    if design_vals:
        slop_rules = [d for d in design_vals if "emoji" in d.get("rule", "").lower() or "slop" in d.get("detail", "").lower() or "gradient" in d.get("rule", "").lower()]
        if slop_rules:
            parts.append("Low-quality output is a trigger. You've codified your rejection of AI slop: no emojis in UI, no colored borders on cards, no gradient backgrounds on everything, restrained palette only. The specificity reveals how often you've been burned.")
        elif quality_score > 15:
            parts.append("Low-quality output is a trigger. Your language around quality ('perfect', 'not good enough', 'clean') reveals what you reject: anything that feels generated, generic, or half-done.")
    elif quality_score > 15:
        parts.append("Low-quality output is a trigger. Your language around quality ('perfect', 'not good enough', 'clean') reveals what you reject: anything that feels generated, generic, or half-done.")
    elif quality_score > 5:
        parts.append("You push back on output that isn't good enough. 'Good enough' isn't good enough.")

    # Wasted time
    if s["abandoned_pct"] > 15:
        parts.append(f"You've walked away from {s['abandoned_pct']:.0f}% of sessions. You can tell when something isn't going anywhere, and you don't waste time on sunk costs.")

    # Fix-heavy projects as pain points
    fix_heavy = [v for v in ventures if v["dominant_category"] == "FIX" and v["sessions"] > 5]
    if fix_heavy:
        if not SANITIZE:
            names = [v["name"] for v in fix_heavy[:2]]
            parts.append(f"Debugging {', '.join(names)} seems to test your patience most. These are the projects where frustration concentrates.")
        else:
            parts.append(f"Some projects are frustration magnets, {len(fix_heavy)} of your ventures are stuck in fix-mode, and it shows in your tone.")

    return " ".join(parts)


def build_how_you_connect(s, personal, identity=None):
    """Section 7: Named people, relationship style, communication directness."""
    parts = []
    identity = identity or {}

    people = _filter_people(personal)

    # Lead with named relationships
    if people:
        top = people[:3]
        if len(top) >= 2:
            name1 = _sanitize_name(top[0]["name"], 0) if SANITIZE else top[0]["name"]
            name2 = _sanitize_name(top[1]["name"], 1) if SANITIZE else top[1]["name"]
            parts.append(f"The people in your world: {name1} ({top[0]['count']} mentions) and {name2} ({top[1]['count']} mentions).")
            if not SANITIZE and top[0].get("contexts"):
                parts.append(f"The way you talk about {top[0]['name']} suggests a co-builder, not just a colleague. Someone you coordinate with regularly, trust with real decisions.")
            if len(top) >= 3:
                name3 = _sanitize_name(top[2]["name"], 2) if SANITIZE else top[2]["name"]
                parts.append(f"{name3} appears too ({top[2]['count']} mentions), expanding the circle.")
        elif len(top) == 1:
            name1 = _sanitize_name(top[0]["name"], 0) if SANITIZE else top[0]["name"]
            parts.append(f"{name1} is your primary collaborator, appearing {top[0]['count']} times. You build together.")
    else:
        parts.append("You work mostly solo, at least in this tool. Few named people surface in your sessions.")

    # Communication style as relationship style
    if s["avg_niceness"] > 7:
        parts.append("Your communication style is warm. Not performatively polite, but genuinely courteous in a context where courtesy is entirely optional.")
        if s["nice_word_count"] > 100:
            parts.append(f"'Please' and 'thanks' show up hundreds of times. That's not habit, it's how you connect.")
    elif s["avg_niceness"] > 4.5:
        parts.append("You're direct but not cold. There's enough warmth to show you see interactions as conversations, not command lines.")
    else:
        parts.append("You skip pleasantries and get to the point. You trust people to handle honesty without padding.")

    # Directness indicators
    if s["question_ratio"] < 5:
        parts.append("You give directives more than you ask questions. In relationships, you probably lead with clarity, not consensus.")
    elif s["question_ratio"] > 20:
        parts.append("You connect by asking. Questions make up a large part of how you interact, curious and collaborative.")

    # Trust signals
    if s["positive_ending_pct"] > 40:
        parts.append(f"You end {s['positive_ending_pct']:.0f}% of sessions on a positive note. Closing with appreciation is part of how you maintain connections.")

    # Low-ceremony, high-trust pattern
    if s["avg_words_per_prompt"] < 20 and s["avg_spec"] > 5:
        parts.append("Short instructions, high specificity. You connect with people the same way: low-ceremony, high-trust. Say what you mean, skip the rest.")

    # Language as connection
    if s["lang_count"] >= 2:
        parts.append(f"You operate in {s['lang_count']} languages ({', '.join(s['languages'][:3])}). That's not just skill, it's how you bridge worlds and connect across cultures.")

    return " ".join(parts)


def build_the_tension(s, personal, identity=None):
    """Section 8: The honest part. What pulls in opposite directions."""
    parts = []
    identity = identity or {}

    ventures = _filter_ventures(personal.get("ventures", []))
    values = personal.get("values", Counter())
    interests = personal.get("interests", {})
    quality_bar = identity.get("quality_bar", [])
    principles = identity.get("principles", [])
    work_method = identity.get("work_methodology", [])

    # Quality vs speed
    quality_score = values.get("quality_obsession", 0)
    shipping_score = values.get("shipping_velocity", 0)
    if quality_score > 10 and shipping_score > 5:
        parts.append("The central tension: you want everything to be perfect, and you want it shipped yesterday.")
        if quality_bar:
            parts.append("Your own rules say \"Do NOT return until genuinely 10/10\" and \"8/10? Keep working. 9/10? Keep working.\" But your shipping data says deploy, launch, go live. These two impulses pull in opposite directions, and you live in the gap between them.")
        else:
            parts.append(f"The data backs both sides. Your language is full of quality language ('perfect', 'clean', '10/10') and just as full of shipping urgency ('deploy', 'launch', 'go live'). These two impulses pull in opposite directions, and you live in the gap between them.")

    # Too many projects vs focus
    if len(ventures) > 5:
        parts.append(f"You're running {len(ventures)} projects. That's ambition, but it's also scattered energy.")
        high_success = [v for v in ventures if v["success_rate"] > 80 and v["sessions"] > 5]
        low_success = [v for v in ventures if v["success_rate"] < 50 and v["sessions"] > 5]
        if high_success and low_success:
            good_name = "your strongest project" if SANITIZE else high_success[0]["name"]
            weak_name = "a struggling one" if SANITIZE else low_success[0]["name"]
            parts.append(f"The gap between {good_name} ({high_success[0]['success_rate']:.0f}% success) and {weak_name} ({low_success[0]['success_rate']:.0f}%) asks the question you might be avoiding: does everything deserve your time?")
        else:
            parts.append("The breadth is impressive, but breadth has a cost. Not every project gets your best energy.")

    # Night preference vs morning performance
    if s["night_session_pct"] > 30 and s["morning_success"] > s["evening_success"] + 10:
        parts.append(f"You prefer the night ({s['night_session_pct']:.0f}% of sessions after dark), but you perform better in the morning ({s['morning_success']:.0f}% vs {s['evening_success']:.0f}% success). Preference and performance pointing different directions is a tension worth noticing.")

    # Work-life balance
    if s["weekend_pct"] > 35 and s["total_hours"] > 200:
        parts.append(f"{s['total_hours']:.0f} hours logged, {s['weekend_pct']:.0f}% of them on weekends. That's either passion or a sustainability problem, and from the outside, both look the same.")
    elif s["max_streak"] > 14:
        parts.append(f"A {s['max_streak']}-day streak without a break. Impressive and unsustainable in the same breath.")

    # Persistence vs flexibility
    if s["retried_pct"] > 50 and s["total_errors"] > 10:
        parts.append(f"When something fails, you retry the same approach {s['retried_pct']:.0f}% of the time. That's determination, but it's also stubbornness. Pivoting earlier might save hours you're currently burning.")

    # Warmth vs standards
    if s["avg_niceness"] > 6 and s["correction_rate"] > 8:
        parts.append("You're warm and you're demanding. Those coexist, but they create their own tension: high expectations delivered gently still create pressure.")

    # Code vs life
    if interests and not SANITIZE:
        top_interest = max(interests.items(), key=lambda x: x[1]["total"])
        if top_interest[1]["total"] > 10 and s["total_hours"] > 200:
            parts.append(f"You clearly care about {top_interest[0]}. It shows up in your data. The tension is whether {s['total_hours']:.0f} hours at the keyboard leave enough room for it.")

    # Read First vs Ship Fast (principle tension)
    if principles and work_method:
        read_first = any("read" in p["name"].lower() or "80%" in p.get("description", "") for p in principles)
        yagni = any("yagni" in p["name"].lower() for p in principles)
        if read_first and shipping_score > 10:
            parts.append("You've written \"80% reading, 20% writing\" as a rule, but your shipping count tells a different story. The investigator and the shipper coexist, and they negotiate every session.")

    # Closing acknowledgment
    if not parts:
        parts.append("Every person has contradictions. Yours are just better documented than most.")
    parts.append("These tensions aren't flaws. They're the engine. The pull between competing values is what keeps the work honest and the ambition in check.")

    return " ".join(parts)


# ---------------------------------------------------------------------------
# HTML Generation
# ---------------------------------------------------------------------------
def generate_html(data, signals, personal=None, identity=None):
    """Read template, substitute placeholders, return HTML string."""
    template = TEMPLATE_PATH.read_text()
    s = signals

    # Mine personal content (use pre-computed if provided)
    if personal is None:
        personal = mine_personal_content(data)

    # Mine identity from config files (use pre-computed if provided)
    if identity is None:
        identity = mine_identity_from_config()

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
    how_you_see_the_world = build_how_you_see_the_world(s, personal, identity)
    what_you_care_about = build_what_you_care_about(s, personal, identity)
    your_mission = build_your_mission(s, personal, identity)
    your_vibe = build_your_vibe(s, personal, identity)
    what_you_love = build_what_you_love(s, personal, identity)
    what_you_cant_stand = build_what_you_cant_stand(s, personal, identity)
    how_you_connect = build_how_you_connect(s, personal, identity)
    the_tension = build_the_tension(s, personal, identity)

    # Sparse data disclaimer
    disclaimer = ""
    if s["sessions_analyzed"] < 50:
        disclaimer = f'<div class="callout" style="background:#FEF3C7;">Early portrait based on {s["sessions_analyzed"]} sessions. The picture gets sharper with more data.</div>'

    replacements = {
        "__PT_AUTHOR__": _html_escape(author),
        "__PT_DATE_RANGE__": date_range,
        "__PT_SESSION_COUNT__": str(s["sessions_analyzed"]),
        "__PT_TOTAL_PROMPTS__": str(s["total_prompts"]),
        "__PT_DISCLAIMER__": disclaimer,
        "__PT_HOW_YOU_SEE_THE_WORLD__": _html_escape(how_you_see_the_world),
        "__PT_WHAT_YOU_CARE_ABOUT__": _html_escape(what_you_care_about),
        "__PT_YOUR_MISSION__": _html_escape(your_mission),
        "__PT_YOUR_VIBE__": _html_escape(your_vibe),
        "__PT_WHAT_YOU_LOVE__": _html_escape(what_you_love),
        "__PT_WHAT_YOU_CANT_STAND__": _html_escape(what_you_cant_stand),
        "__PT_HOW_YOU_CONNECT__": _html_escape(how_you_connect),
        "__PT_THE_TENSION__": _html_escape(the_tension),
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

    print("Mining personal content...")
    personal = mine_personal_content(data)

    print("Mining identity from config files...")
    identity = mine_identity_from_config()

    print("Building portrait narratives...")
    html = generate_html(data, signals, personal=personal, identity=identity)

    OUTPUT_DIR.mkdir(exist_ok=True)
    OUTPUT_PATH.write_text(html)
    print(f"Wrote {OUTPUT_PATH} ({len(html):,} bytes)")

    print(f"\nPortrait Summary:")
    print(f"  Sessions: {n}")
    print(f"  Hours: {signals['total_hours']}")
    print(f"  Projects: {signals['unique_projects']}")
    print(f"  Ventures: {len(personal['ventures'])}")
    print(f"  People discovered: {len(personal['people'])}")
    print(f"  Locations: {len(personal['locations'])}")
    print(f"  Interests: {list(personal['interests'].keys())}")
    print(f"  Goals extracted: {len(personal['goals'])}")
    print(f"  Values: {dict(personal['values'].most_common(3))}")
    print(f"  Niceness: {signals['avg_niceness']}/10")
    print(f"  Success: {signals['success_pct']}%")
    if identity:
        print(f"  Config principles: {len(identity.get('principles', []))}")
        print(f"  Config comm rules: {len(identity.get('communication_style', []))}")
        print(f"  Config design rules: {len(identity.get('design_values', []))}")
        print(f"  Config pet peeves: {len(identity.get('pet_peeves', []))}")


if __name__ == "__main__":
    main()
