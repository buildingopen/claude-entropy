#!/usr/bin/env node

const { execSync, spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const os = require('os');

const HELP = `
Claude Code Entropy - Spotify Wrapped for your Claude Code usage

Usage: npx claude-entropy [options]

Options:
  --author NAME        Display name (default: git user.name)
  --tz HOURS           UTC offset for local time (default: auto-detect)
  --money USD          Total subscription cost for ROI slide
  --money-detail DESC  Subscription description
  --sanitize           Anonymize project names for sharing
  --publish            Publish to buildingopen.org/wrapped/
  -h, --help           Show this help

Output: ./wrapped.html (auto-opens in browser)
`.trim();

function parseArgs(argv) {
  const args = { _: [] };
  let i = 0;
  while (i < argv.length) {
    const arg = argv[i];
    if (arg === '-h' || arg === '--help') {
      args.help = true;
    } else if (arg === '--sanitize') {
      args.sanitize = true;
    } else if (arg === '--publish') {
      args.publish = true;
    } else if (arg === '--author' && i + 1 < argv.length) {
      args.author = argv[++i];
    } else if (arg === '--tz' && i + 1 < argv.length) {
      args.tz = argv[++i];
    } else if (arg === '--money' && i + 1 < argv.length) {
      args.money = argv[++i];
    } else if (arg === '--money-detail' && i + 1 < argv.length) {
      args.moneyDetail = argv[++i];
    } else {
      args._.push(arg);
    }
    i++;
  }
  return args;
}

function main() {
  const args = parseArgs(process.argv.slice(2));

  if (args.help) {
    console.log(HELP);
    process.exit(0);
  }

  // Check python3
  try {
    execSync('python3 --version', { stdio: 'pipe' });
  } catch {
    console.error('Error: python3 is required but not found on PATH.');
    console.error('Install Python 3.8+ from https://python.org');
    process.exit(1);
  }

  // Check Claude Code data exists
  const dataDir = process.env.CLAUDE_PROJECTS_DIR || path.join(os.homedir(), '.claude', 'projects');
  if (!fs.existsSync(dataDir)) {
    console.error('Error: No Claude Code data found at ' + dataDir);
    console.error('Make sure you have used Claude Code at least once.');
    console.error('Override with CLAUDE_PROJECTS_DIR env var if data is elsewhere.');
    process.exit(1);
  }

  // Build env vars
  const env = { ...process.env };

  // Author: CLI flag > env > git user.name > default
  if (args.author) {
    env.WRAPPED_AUTHOR = args.author;
  } else if (!env.WRAPPED_AUTHOR) {
    try {
      const name = execSync('git config user.name', { encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'] }).trim();
      if (name) env.WRAPPED_AUTHOR = name;
    } catch {
      // git not available or no user.name set, will use Python default
    }
  }

  // Timezone: CLI flag > env > auto-detect
  if (args.tz !== undefined) {
    env.WRAPPED_TZ_OFFSET = String(args.tz);
  } else if (!env.WRAPPED_TZ_OFFSET) {
    env.WRAPPED_TZ_OFFSET = String(-new Date().getTimezoneOffset() / 60);
  }

  if (args.money) env.WRAPPED_MONEY_PAID = args.money;
  if (args.moneyDetail) env.WRAPPED_MONEY_DETAIL = args.moneyDetail;
  if (args.sanitize) env.WRAPPED_SANITIZE = '1';

  // Build python args
  const pyArgs = [];
  if (args.publish) pyArgs.push('--publish');

  // Run generate_wrapped.py from the package directory
  const scriptDir = path.join(__dirname, '..');
  const scriptPath = path.join(scriptDir, 'generate_wrapped.py');

  console.log('Analyzing your Claude Code sessions...\n');

  const result = spawnSync('python3', [scriptPath, ...pyArgs], {
    cwd: scriptDir,
    env,
    stdio: 'inherit',
  });

  if (result.status !== 0) {
    console.error('\nGeneration failed (exit code ' + result.status + ')');
    process.exit(result.status || 1);
  }

  // Copy output to CWD
  const src = path.join(scriptDir, 'dist', 'wrapped.html');
  if (!fs.existsSync(src)) {
    console.error('Error: Expected output not found at ' + src);
    process.exit(1);
  }

  const dest = path.join(process.cwd(), 'wrapped.html');
  // Don't copy if CWD is the package dir (running from repo checkout)
  if (path.resolve(src) !== path.resolve(dest)) {
    fs.copyFileSync(src, dest);
  }

  console.log('\nOutput: ' + dest);

  // Open in browser
  try {
    const cmd = process.platform === 'darwin' ? 'open'
              : process.platform === 'win32' ? 'start ""'
              : 'xdg-open';
    execSync(cmd + ' "' + dest + '"', { stdio: 'ignore' });
  } catch {
    // Browser open is best-effort
  }
}

main();
