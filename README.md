# TechTalk Bot

Multi-channel Discord bot delivering AI-powered intelligence digests across cybersecurity and tech/AI. Each channel monitors curated X (Twitter) accounts and web sources, analyzes content with Claude AI, and delivers formatted briefings on a daily schedule.

## Architecture

```
bot.py              — Discord bot, slash commands, scheduled digests
claude_client.py    — Claude analysis engine (X-only, web-only, combined)
x_client.py         — X API v2 client (60s timeout, 2 retries, concurrent fetching)
search_client.py    — Tavily web search with multi-query deduplication
database.py         — SQLite: sources, schedules, prompts, channel mappings
config.py           — YAML config loader
channels.yaml       — Channel definitions (sources, schedules, prompts)
setup_server.py     — One-time Discord server setup script
```

## Channels & Default X Sources

### CYBERSECURITY

| Channel | Schedule | Sources |
|---------|----------|---------|
| **#cyber-threats-intel** | 7:00am CST | `@GossiTheDog` `@craiu` `@vxunderground` `@TheDFIRReport` `@CISAgov` `@campuscodi` `@RobertMLee` `@cyb3rops` |
| **#cyber-breaches** | 7:00am CST | `@troyhunt` `@briankrebs` `@BleepinComputer` `@DailyDarkWeb` `@FalconFeedsio` `@BushidoToken` `@gcluley` |
| **#cyber-vendor-pulse** | 8:00am CST | `@CrowdStrike` `@SentinelOne` `@PaloAltoNtwks` `@Fortinet` `@Zscaler` `@MicrosoftSecurity` `@George_Kurtz` `@JohnHultquist` `@KevinBeaumont` |
| **#osint-cyber** | 8:00am CST | `@OSINTtechniques` `@IntelTechniques` `@AricToler` `@dutch_osintguy` `@jms_dot_py` `@hasherezade` `@sentdefender` `@evacide` |

### TECH & AI

| Channel | Schedule | Sources |
|---------|----------|---------|
| **#ai-breakthroughs** | 9:00am CST | `@ylecun` `@karpathy` `@DrJimFan` `@_akhaliq` `@sama` `@DarioAmodei` `@emollick` `@swyx` |
| **#tech-innovations** | 9:00am CST | `@dylan522p` `@AsianometryYT` `@SpaceX` `@thesheetztweetz` `@MIT_CSAIL` `@SpaceNews_Inc` `@IBMQuantum` `@SemiEngineering` |

All sources are configurable at runtime via `/config` commands.

## Commands

### `/digest` (everyone, channel-aware)

Auto-detects which channel you're in and pulls the matching config.

| Parameter | Description | Default |
|-----------|-------------|---------|
| `hours` | Lookback window | Channel setting (24h) |
| `web` | Include Tavily web search results | `false` |
| `share` | Post publicly (vs ephemeral) | `false` |

### `/config` (admin only)

| Command | Description |
|---------|-------------|
| `sources_add <username>` | Add X source (validates account exists) |
| `sources_remove <username>` | Remove X source |
| `sources_list` | List current sources for this channel |
| `schedule <HH:MM> [lookback]` | Set cron time and lookback hours |
| `prompt <instructions>` | Set custom AI instructions (`reset` to clear) |

### `/status`

Shows bot health, per-channel source counts, schedules, and last digest timestamps.

## Scheduled Digests

Each channel receives **two embeds** at its scheduled time daily:

1. **X Digest** — Summarizes posts from monitored X accounts
2. **Web Intel Digest** — Summarizes Tavily web search results

The scheduler checks every minute and skips if already sent today.

## AI Analysis

### Base Persona (all channels)

> Senior intelligence analyst with deep expertise across cybersecurity, technology, and geopolitics. Writes like a professional intelligence briefer — concise, direct, no fluff. Prioritizes by significance and impact.

### Per-Channel Prompt Overlays

**#cyber-threats-intel**
> Prioritize by severity. Lead with actively exploited CVEs and zero-days. Flag nation-state attribution when available. Include affected products/versions when mentioned.

**#cyber-breaches**
> Lead with the largest/most impactful breaches. Include: who was breached, what data was exposed, how many affected, ransomware group if known, and whether a ransom was paid/demanded.

**#cyber-vendor-pulse**
> Focus on business moves: acquisitions, product launches, earnings highlights, partnerships, and competitive positioning. Note stock-moving news.

**#osint-cyber**
> Highlight new tools, techniques, and tradecraft. Cover dark web discoveries and notable investigations. Flag new OSINT methodologies.

**#ai-breakthroughs**
> Lead with the most significant model releases and research papers. Include benchmark results when available. Note competitive implications between labs (OpenAI vs Anthropic vs Google etc).

**#tech-innovations**
> Cover breakthroughs across semiconductors, quantum, space, and robotics. Lead with the most commercially or scientifically significant. Include launch dates and milestones.

All prompts are customizable at runtime via `/config prompt`.

### Output Format

- X digests are **grouped by source** (`**@username**` section headers), ordered by newsworthiness
- Inline hyperlinked citations: `[(1)](tweet_url)` / `[(2)](article_url)`
- Max 3500 characters per briefing (Discord embed limit)

## Config Hierarchy

1. `channels.yaml` — Defaults (sources, schedules, prompts, Tavily queries)
2. SQLite database — Runtime overrides via `/config` commands
3. Database takes priority when both exist

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DISCORD_BOT_TOKEN` | Yes | Discord bot token |
| `X_BEARER_TOKEN` | Yes | X API v2 bearer token (Basic tier) |
| `ANTHROPIC_API_KEY` | Yes | Anthropic API key |
| `TAVILY_API_KEY` | Yes | Tavily search API key |
| `CLAUDE_MODEL` | No | Default: `claude-4-sonnet-20250514` |
| `TIMEZONE` | No | Default: `America/Chicago` |
| `DB_PATH` | No | Default: `./bot_data.db` (set to `/data/bot_data.db` on Railway) |
| `OWNER_USER_ID` | Setup only | Discord user ID for server setup |
| `SETUP_GUILD_ID` | Setup only | Discord server ID for setup script |

## Deployment (Railway)

1. Connect repo to Railway
2. Add all env vars in the Railway dashboard
3. Add a persistent volume mounted at `/data`
4. Set `DB_PATH=/data/bot_data.db`
5. Railway auto-deploys on push to `main`

## Tech Stack

Python 3.14 · discord.py · Anthropic SDK · Tavily · X API v2 · aiosqlite · PyYAML
