from __future__ import annotations

import os
import re
import logging
import asyncio
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv
from zoneinfo import ZoneInfo

from config import load_channel_configs, get_timezone_str, ChannelConfig
from database import Database
from x_client import XClient
from claude_client import ClaudeAnalyzer
from search_client import TavilySearch

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("techtalk")

# --- Config ---
DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
X_BEARER = os.getenv("X_BEARER_TOKEN", "")
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")
TAVILY_KEY = os.getenv("TAVILY_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-4-sonnet-20250514")
BOT_TZ = ZoneInfo(get_timezone_str())

CHANNEL_CONFIGS = load_channel_configs()

# --- Clients ---
x_client = XClient(X_BEARER)
tavily = TavilySearch(TAVILY_KEY)
analyzer = ClaudeAnalyzer(ANTHROPIC_KEY, tavily, model=CLAUDE_MODEL)
db = Database()

# --- Bot setup ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


# ===================== Helpers =====================

def _guild_id(interaction: discord.Interaction) -> int:
    return interaction.guild_id or 0


async def _resolve_channel_name(interaction: discord.Interaction) -> str | None:
    """Resolve the channel config name from the Discord channel the command is run in."""
    discord_channel_id = interaction.channel_id
    # Check DB mapping first
    name = await db.get_channel_name_by_discord_id(discord_channel_id)
    if name:
        return name
    # Fallback: match by channel name
    if interaction.channel and hasattr(interaction.channel, "name"):
        ch_name = interaction.channel.name
        if ch_name in CHANNEL_CONFIGS:
            return ch_name
    return None


async def _get_effective_sources(channel_name: str, guild_id: int) -> list[str]:
    """Get sources from DB, falling back to YAML defaults."""
    db_sources = await db.get_sources(channel_name, guild_id)
    if db_sources:
        return db_sources
    config = CHANNEL_CONFIGS.get(channel_name)
    return config.default_sources if config else []


async def _get_effective_prompt(channel_name: str, guild_id: int) -> str:
    """Get prompt overlay from DB, falling back to YAML defaults."""
    db_prompt = await db.get_prompt(channel_name, guild_id)
    if db_prompt:
        return db_prompt
    config = CHANNEL_CONFIGS.get(channel_name)
    return config.prompt_overlay if config else ""


async def _get_effective_schedule(channel_name: str, guild_id: int) -> tuple[str, int]:
    """Get schedule from DB, falling back to YAML defaults."""
    db_schedule = await db.get_schedule(channel_name, guild_id)
    if db_schedule:
        return db_schedule
    config = CHANNEL_CONFIGS.get(channel_name)
    if config:
        return config.cron_time, config.lookback_hours
    return "07:00", 24


async def _fetch_user_tweets(username: str, start_iso: str, end_iso: str) -> tuple[list[dict], str | None]:
    loop = asyncio.get_event_loop()
    try:
        uid = await loop.run_in_executor(None, x_client.get_user_id, username)
        posts = await loop.run_in_executor(
            None, lambda u=username, i=uid: x_client.get_posts(
                user_id=i, username=u,
                start_time_utc_iso=start_iso, end_time_utc_iso=end_iso,
            )
        )
        return posts, None
    except Exception as e:
        log.error("Failed to fetch tweets for @%s: %s", username, e)
        return [], f"@{username}: {e}"


async def fetch_x_digest(channel_name: str, guild_id: int, hours: int | None = None) -> str:
    sources = await _get_effective_sources(channel_name, guild_id)
    prompt = await _get_effective_prompt(channel_name, guild_id)

    if not sources:
        return "No sources configured for this channel."

    if hours is None:
        _, hours = await _get_effective_schedule(channel_name, guild_id)

    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=hours)
    start_iso = start.strftime("%Y-%m-%dT%H:%M:%SZ")
    end_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    results = await asyncio.gather(*[
        _fetch_user_tweets(username, start_iso, end_iso)
        for username in sources
    ])

    all_tweets = []
    errors = []
    for tweets, error in results:
        all_tweets.extend(tweets)
        if error:
            errors.append(error)

    if not all_tweets and errors:
        return "Failed to fetch tweets:\n" + "\n".join(errors)

    all_tweets.sort(key=lambda t: t.get("created_at", ""), reverse=True)
    loop = asyncio.get_event_loop()
    briefing = await loop.run_in_executor(None, analyzer.analyze_x_digest, all_tweets, prompt)

    if errors:
        briefing += "\n\n_Note: some sources had errors: " + ", ".join(errors) + "_"
    return briefing


async def fetch_web_digest(channel_name: str, guild_id: int) -> str:
    config = CHANNEL_CONFIGS.get(channel_name)
    queries = config.tavily_queries if config else []
    prompt = await _get_effective_prompt(channel_name, guild_id)

    if not queries:
        return "No web search queries configured for this channel."

    loop = asyncio.get_event_loop()
    results = await loop.run_in_executor(None, tavily.search_channel, queries)
    return await loop.run_in_executor(None, analyzer.analyze_web_digest, results, prompt)


async def fetch_combined_digest(channel_name: str, guild_id: int, hours: int | None = None) -> str:
    sources = await _get_effective_sources(channel_name, guild_id)
    config = CHANNEL_CONFIGS.get(channel_name)
    queries = config.tavily_queries if config else []
    prompt = await _get_effective_prompt(channel_name, guild_id)

    if hours is None:
        _, hours = await _get_effective_schedule(channel_name, guild_id)

    # Fetch X and web in parallel
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=hours)
    start_iso = start.strftime("%Y-%m-%dT%H:%M:%SZ")
    end_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    async def get_tweets():
        if not sources:
            return [], []
        results = await asyncio.gather(*[
            _fetch_user_tweets(username, start_iso, end_iso)
            for username in sources
        ])
        tweets, errors = [], []
        for t, e in results:
            tweets.extend(t)
            if e:
                errors.append(e)
        return tweets, errors

    async def get_web():
        if not queries:
            return []
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, tavily.search_channel, queries)

    (all_tweets, tweet_errors), web_results = await asyncio.gather(get_tweets(), get_web())

    all_tweets.sort(key=lambda t: t.get("created_at", ""), reverse=True)
    loop = asyncio.get_event_loop()
    briefing = await loop.run_in_executor(
        None, analyzer.analyze_combined_digest, all_tweets, web_results, prompt
    )

    if tweet_errors:
        briefing += "\n\n_Note: some X sources had errors: " + ", ".join(tweet_errors) + "_"
    return briefing


def build_embed(briefing: str, title: str, color: int = 0x1A1A2E, footer: str = "Powered by Claude") -> list[discord.Embed]:
    if len(briefing) <= 4096:
        embed = discord.Embed(title=title, description=briefing, color=color)
        embed.timestamp = datetime.now(timezone.utc)
        embed.set_footer(text=footer)
        return [embed]

    truncated = briefing[:4050] + "\n\n_...briefing truncated for length._"
    embed = discord.Embed(title=title, description=truncated, color=color)
    embed.timestamp = datetime.now(timezone.utc)
    embed.set_footer(text=footer)
    return [embed]


# ===================== Share Button =====================

class ShareView(discord.ui.View):
    """Adds a 'Share to Channel' button on ephemeral digest messages."""

    def __init__(self, embeds: list[discord.Embed]):
        super().__init__(timeout=300)  # 5 min timeout
        self._embeds = embeds

    @discord.ui.button(label="Share to Channel", style=discord.ButtonStyle.primary, emoji="\U0001F4E2")
    async def share_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.channel.send(embeds=self._embeds)
        button.disabled = True
        button.label = "Shared"
        button.style = discord.ButtonStyle.secondary
        await interaction.response.edit_message(view=self)


# ===================== /digest command =====================

@bot.tree.command(name="digest", description="Generate an intelligence digest for this channel")
@app_commands.describe(
    hours="Hours to look back (default: channel setting)",
    web="Include web search results (default: false)",
    share="Share publicly in channel (default: hidden)",
)
async def digest_cmd(interaction: discord.Interaction, hours: int | None = None, web: bool = False, share: bool = False):
    channel_name = await _resolve_channel_name(interaction)
    if not channel_name:
        await interaction.response.send_message(
            "This channel is not configured for digests. Run this in a monitored channel.",
            ephemeral=True,
        )
        return

    if hours is not None and (hours < 1 or hours > 168):
        await interaction.response.send_message("Hours must be between 1 and 168.", ephemeral=True)
        return

    config = CHANNEL_CONFIGS.get(channel_name)
    color = config.color if config else 0x1A1A2E

    await interaction.response.defer(ephemeral=not share)
    try:
        if web:
            briefing = await fetch_combined_digest(channel_name, _guild_id(interaction), hours)
            footer = "Powered by Claude | X + Web Sources"
        else:
            briefing = await fetch_x_digest(channel_name, _guild_id(interaction), hours)
            footer = "Powered by Claude | X Sources"

        display_hours = hours if hours else (config.lookback_hours if config else 24)
        title = f"{channel_name} Digest — Last {display_hours}h"
        embeds = build_embed(briefing, title, color=color, footer=footer)

        if share:
            await interaction.followup.send(embeds=embeds, ephemeral=False)
        else:
            view = ShareView(embeds)
            await interaction.followup.send(embeds=embeds, view=view, ephemeral=True)
    except Exception as e:
        log.error("digest failed for %s: %s", channel_name, e, exc_info=True)
        await interaction.followup.send(f"Something went wrong: {e}", ephemeral=True)


# ===================== /config group =====================

config_group = app_commands.Group(
    name="config",
    description="Configure channel sources, schedule, and prompts (Admin only)",
    default_permissions=discord.Permissions(manage_guild=True),
)


@config_group.command(name="sources_add", description="Add an X source to this channel")
@app_commands.describe(username="X username (with or without @)")
async def config_sources_add(interaction: discord.Interaction, username: str):
    channel_name = await _resolve_channel_name(interaction)
    if not channel_name:
        await interaction.response.send_message("Not a configured channel.", ephemeral=True)
        return

    clean = username.lstrip("@").strip()
    if not clean:
        await interaction.response.send_message("Please provide a valid username.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    # Validate X account exists
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, x_client.get_user_id, clean)
    except Exception:
        await interaction.followup.send(
            f"Could not find X account **@{clean}**. Check the username and try again.",
            ephemeral=True,
        )
        return

    guild_id = _guild_id(interaction)
    added = await db.add_source(channel_name, guild_id, clean)
    if added:
        await interaction.followup.send(f"Verified and added **@{clean}** to #{channel_name}.", ephemeral=True)
    else:
        await interaction.followup.send(f"@{clean} is already in #{channel_name} sources.", ephemeral=True)


@config_group.command(name="sources_remove", description="Remove an X source from this channel")
@app_commands.describe(username="X username (with or without @)")
async def config_sources_remove(interaction: discord.Interaction, username: str):
    channel_name = await _resolve_channel_name(interaction)
    if not channel_name:
        await interaction.response.send_message("Not a configured channel.", ephemeral=True)
        return

    clean = username.lstrip("@").strip()
    guild_id = _guild_id(interaction)
    removed = await db.remove_source(channel_name, guild_id, clean)
    if removed:
        await interaction.response.send_message(f"Removed **@{clean}** from #{channel_name}.", ephemeral=True)
    else:
        await interaction.response.send_message(f"@{clean} was not in #{channel_name} sources.", ephemeral=True)


@config_group.command(name="sources_list", description="List X sources for this channel")
async def config_sources_list(interaction: discord.Interaction):
    channel_name = await _resolve_channel_name(interaction)
    if not channel_name:
        await interaction.response.send_message("Not a configured channel.", ephemeral=True)
        return

    guild_id = _guild_id(interaction)
    sources = await _get_effective_sources(channel_name, guild_id)
    if not sources:
        await interaction.response.send_message(f"No sources configured for #{channel_name}.", ephemeral=True)
        return

    source_list = "\n".join(f"• @{s}" for s in sources)
    await interaction.response.send_message(
        f"**#{channel_name} X Sources:**\n{source_list}",
        ephemeral=True,
    )


@config_group.command(name="schedule", description="Set digest schedule for this channel")
@app_commands.describe(
    time="Time in HH:MM format (24h, in configured timezone)",
    lookback="Hours to look back (default: 24)",
)
async def config_schedule(interaction: discord.Interaction, time: str, lookback: int = 24):
    channel_name = await _resolve_channel_name(interaction)
    if not channel_name:
        await interaction.response.send_message("Not a configured channel.", ephemeral=True)
        return

    if not re.match(r"^\d{2}:\d{2}$", time):
        await interaction.response.send_message("Time must be in HH:MM format (e.g., 07:00).", ephemeral=True)
        return

    guild_id = _guild_id(interaction)
    await db.set_schedule(channel_name, guild_id, time, lookback)
    await interaction.response.send_message(
        f"Schedule for #{channel_name} set to **{time}** ({lookback}h lookback).",
        ephemeral=True,
    )


@config_group.command(name="prompt", description="Set custom analysis instructions for this channel")
@app_commands.describe(instructions="Custom instructions for the AI analyst (or 'reset' to clear)")
async def config_prompt(interaction: discord.Interaction, instructions: str):
    channel_name = await _resolve_channel_name(interaction)
    if not channel_name:
        await interaction.response.send_message("Not a configured channel.", ephemeral=True)
        return

    guild_id = _guild_id(interaction)
    if instructions.lower().strip() == "reset":
        await db.clear_prompt(channel_name, guild_id)
        await interaction.response.send_message(
            f"Prompt for #{channel_name} reset to default.", ephemeral=True
        )
    else:
        await db.set_prompt(channel_name, guild_id, instructions)
        await interaction.response.send_message(
            f"Custom prompt set for #{channel_name}.", ephemeral=True
        )


bot.tree.add_command(config_group)


# ===================== /status command =====================

@bot.tree.command(name="status", description="Check bot status and channel configuration")
async def status_cmd(interaction: discord.Interaction):
    guild_id = _guild_id(interaction)
    lines = [
        "**Bot Status:** Online",
        f"**Claude model:** {CLAUDE_MODEL}",
        f"**Configured channels:** {len(CHANNEL_CONFIGS)}",
        "",
    ]

    for ch_name, ch_config in CHANNEL_CONFIGS.items():
        sources = await _get_effective_sources(ch_name, guild_id)
        cron_time, lookback = await _get_effective_schedule(ch_name, guild_id)
        last_x = await db.get_last_digest(ch_name, guild_id, "x")
        last_web = await db.get_last_digest(ch_name, guild_id, "web")

        lines.append(f"**#{ch_name}**")
        lines.append(f"  Sources: {len(sources)} | Schedule: {cron_time} ({lookback}h)")
        if last_x:
            lines.append(f"  Last X digest: {last_x.strftime('%Y-%m-%d %H:%M UTC')}")
        if last_web:
            lines.append(f"  Last web digest: {last_web.strftime('%Y-%m-%d %H:%M UTC')}")

    await interaction.response.send_message("\n".join(lines), ephemeral=True)


# ===================== Scheduled Digests =====================

@tasks.loop(minutes=1)
async def scheduled_digest():
    now_tz = datetime.now(BOT_TZ)
    current_time = f"{now_tz.hour:02d}:{now_tz.minute:02d}"

    for guild in bot.guilds:
        guild_id = guild.id

        for ch_name, ch_config in CHANNEL_CONFIGS.items():
            cron_time, lookback = await _get_effective_schedule(ch_name, guild_id)

            if current_time != cron_time:
                continue

            # Check if already sent today for each type
            for digest_type in ("x", "web"):
                last = await db.get_last_digest(ch_name, guild_id, digest_type)
                if last:
                    last_tz = last.astimezone(BOT_TZ)
                    if last_tz.date() == now_tz.date():
                        continue

                # Find the Discord channel
                discord_channel_id = await db.get_channel_mapping(ch_name, guild_id)
                if not discord_channel_id:
                    # Try matching by name
                    for ch in guild.text_channels:
                        if ch.name == ch_name:
                            discord_channel_id = ch.id
                            await db.set_channel_mapping(ch_name, guild_id, ch.id)
                            break

                if not discord_channel_id:
                    continue

                channel = bot.get_channel(discord_channel_id)
                if not channel:
                    continue

                try:
                    if digest_type == "x":
                        log.info("Sending scheduled X digest for #%s in guild %s", ch_name, guild_id)
                        briefing = await fetch_x_digest(ch_name, guild_id, lookback)
                        title = f"{ch_name} — X Digest"
                        footer = "Powered by Claude | X Sources"
                    else:
                        log.info("Sending scheduled web digest for #%s in guild %s", ch_name, guild_id)
                        briefing = await fetch_web_digest(ch_name, guild_id)
                        title = f"{ch_name} — Web Intel Digest"
                        footer = "Powered by Claude | Web Sources via Tavily"

                    embeds = build_embed(briefing, title, color=ch_config.color, footer=footer)
                    await channel.send(embeds=embeds)
                    await db.set_last_digest(ch_name, guild_id, digest_type)
                    log.info("Scheduled %s digest sent for #%s", digest_type, ch_name)

                except Exception as e:
                    log.error("Scheduled %s digest failed for #%s: %s", digest_type, ch_name, e)


@scheduled_digest.before_loop
async def before_scheduled():
    await bot.wait_until_ready()


# ===================== Events =====================

@bot.event
async def on_ready():
    await db.connect()
    log.info("Database connected.")

    # Initialize default sources and channel mappings for all guilds
    for guild in bot.guilds:
        for ch_name, ch_config in CHANNEL_CONFIGS.items():
            await db.init_default_sources(ch_name, guild.id, ch_config.default_sources)
            # Auto-map channels by name
            for ch in guild.text_channels:
                if ch.name == ch_name:
                    await db.set_channel_mapping(ch_name, guild.id, ch.id)

    await bot.tree.sync()
    log.info("Slash commands synced.")

    if not scheduled_digest.is_running():
        scheduled_digest.start()

    log.info("Bot is ready as %s (ID: %s)", bot.user, bot.user.id)
    log.info("In %d guild(s)", len(bot.guilds))
    log.info("Monitoring %d channel configs", len(CHANNEL_CONFIGS))


@bot.event
async def on_guild_join(guild: discord.Guild):
    for ch_name, ch_config in CHANNEL_CONFIGS.items():
        await db.init_default_sources(ch_name, guild.id, ch_config.default_sources)
        for ch in guild.text_channels:
            if ch.name == ch_name:
                await db.set_channel_mapping(ch_name, guild.id, ch.id)
    log.info("Joined guild %s (%s), initialized channel configs.", guild.name, guild.id)


# ===================== Entry Point =====================

def main():
    if not DISCORD_TOKEN:
        print("ERROR: Set DISCORD_BOT_TOKEN in your .env file.")
        return
    bot.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
