# TechTalk Bot — Project Context

## Overview

Multi-channel Discord bot delivering AI-powered intelligence digests across cybersecurity and tech/AI topics. Each channel has its own X sources, web search queries, custom AI prompts, and scheduled cron digests.

**Repo:** https://github.com/amin-hamidi/techtalk
**Hosting:** Railway.app (auto-deploys from main branch)
**Owner:** amin-hamidi

## Architecture

```
bot.py              — Main Discord bot, slash commands, scheduled digests
claude_client.py    — Claude analysis (X-only, web-only, or combined modes)
x_client.py         — X API v2 client with retry logic + concurrent fetching
search_client.py    — Tavily search with multi-query deduplication
database.py         — SQLite (aiosqlite): sources, schedules, prompts, mappings
config.py           — YAML config loader for channel definitions
channels.yaml       — Default channel configs (sources, schedules, prompts)
setup_server.py     — One-time script to create Discord server + channels programmatically
```

## Channel Structure

| Channel | Category | Cron | Focus |
|---------|----------|------|-------|
| #cyber-threats-intel | CYBERSECURITY | 07:00 CST | Active threats, APTs, CVEs, zero-days |
| #cyber-breaches | CYBERSECURITY | 07:00 CST | Data breaches, ransomware, compromises |
| #cyber-vendor-pulse | CYBERSECURITY | 08:00 CST | CrowdStrike, SentinelOne, Palo Alto, etc. |
| #osint-cyber | CYBERSECURITY | 08:00 CST | OSINT tools, dark web, threat hunting |
| #ai-breakthroughs | TECH & AI | 09:00 CST | AI/ML models, research, benchmarks |
| #tech-innovations | TECH & AI | 09:00 CST | Semiconductors, quantum, space, robotics |

## Commands

**`/digest` (everyone, channel-aware):**
- Auto-detects which channel config to use based on where it's run
- `hours` — lookback window (default: channel setting)
- `web` — include Tavily web search results (default: false)
- `share` — post publicly (default: ephemeral)

**`/config` group (admin only, manage_guild):**
- `sources_add <username>` — Add X source (validates account exists)
- `sources_remove <username>` — Remove X source
- `sources_list` — List current sources
- `schedule <time> [lookback]` — Set cron time (HH:MM) and lookback hours
- `prompt <instructions>` — Set custom AI instructions ("reset" to clear)

**`/status`** — Bot health and per-channel config overview

## Config Hierarchy

1. **channels.yaml** — Default structure, sources, schedules, prompts
2. **SQLite database** — Runtime overrides (admin changes via /config)
3. DB takes priority over YAML when both exist

## Scheduled Digests

- Each channel gets TWO scheduled digests at the same cron time:
  1. **X Digest** — Posts from monitored X accounts only
  2. **Web Digest** — Tavily web search results
- Posted as separate embeds in the channel
- Checks every minute, fires at exact cron_time match
- Skips if already sent today for that digest type

## Key Design Decisions

- **Channel-aware commands:** Bot auto-detects config from which Discord channel the command is run in
- **Grouped-by-source output:** X digests organized with **@username** section headers, ordered by newsworthiness
- **Base persona + overlay:** All channels share an intel briefer persona, each has custom instructions layered on top
- **Concurrent X fetching:** All sources fetched in parallel via asyncio.gather
- **X account validation:** /config sources_add validates username exists on X before adding
- **60s timeout + 2 retries:** X API client handles slow/flaky responses gracefully

## Environment Variables

```
DISCORD_BOT_TOKEN     — Discord bot token (shared with OSINT bot)
X_BEARER_TOKEN        — X API v2 bearer token
ANTHROPIC_API_KEY     — Anthropic API key
TAVILY_API_KEY        — Tavily search API key
CLAUDE_MODEL          — Default: claude-4-sonnet-20250514
TIMEZONE              — Default: America/Chicago
DB_PATH               — Database path (set to /data/bot_data.db on Railway)
OWNER_USER_ID         — Discord user ID (setup script only)
```

## Deployment

- Railway.app auto-deploys on push to main
- Persistent volume mounted at /data for SQLite
- DB_PATH=/data/bot_data.db in Railway env vars
- Procfile: `worker: python bot.py`
- runtime.txt: Python 3.14

## Workflow

1. Edit files locally
2. `git add <files> && git commit -m "message" && git push`
3. Railway auto-redeploys
4. Always push to GitHub after changes — no need to ask

## Setup (new server)

1. Set DISCORD_BOT_TOKEN and OWNER_USER_ID in .env
2. Run `python setup_server.py` to create server + channels
3. Join server via invite link
4. Deploy bot to Railway with all env vars
