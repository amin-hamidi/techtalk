"""
Discord server setup script.

Sets up all channels, categories, and roles on an EXISTING server.
The bot must already be invited to the server.

Usage:
    1. Create a Discord server manually (just click + in Discord)
    2. Invite the bot using the OAuth2 URL (with manage_channels, manage_guild, manage_roles)
    3. Set SETUP_GUILD_ID in .env to the server ID
    4. Run: python setup_server.py

Requires DISCORD_BOT_TOKEN, OWNER_USER_ID, and SETUP_GUILD_ID in .env
"""

from __future__ import annotations

import os
import asyncio
import logging

import discord
from dotenv import load_dotenv

from config import load_channel_configs

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("setup")

BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
OWNER_ID = int(os.getenv("OWNER_USER_ID", "0"))
GUILD_ID = int(os.getenv("SETUP_GUILD_ID", "0"))


async def run_setup():
    intents = discord.Intents.default()
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        log.info("Bot logged in as %s", client.user)

        guild = client.get_guild(GUILD_ID)
        if not guild:
            try:
                guild = await client.fetch_guild(GUILD_ID)
            except Exception:
                log.error("Could not find guild %s. Is the bot invited?", GUILD_ID)
                await client.close()
                return

        log.info("Connected to server: %s (ID: %s)", guild.name, guild.id)

        # --- Delete existing channels (clean slate) ---
        log.info("Cleaning existing channels...")
        for ch in guild.channels:
            try:
                await ch.delete()
                log.info("  Deleted: %s", ch.name)
            except Exception as e:
                log.warning("  Could not delete %s: %s", ch.name, e)

        await asyncio.sleep(1)

        # --- Roles skipped (set up manually in Server Settings > Roles) ---
        log.info("Skipping role creation (configure roles manually in Discord)")

        # --- Create categories and channels ---
        configs = load_channel_configs()
        categories_created: dict[str, discord.CategoryChannel] = {}

        for ch_name, ch_config in configs.items():
            cat_name = ch_config.category
            if cat_name not in categories_created:
                log.info("Creating category '%s'...", cat_name)
                cat = await guild.create_category(cat_name)
                categories_created[cat_name] = cat

            category = categories_created[cat_name]
            channel = await guild.create_text_channel(
                name=ch_name,
                category=category,
                topic=ch_config.description,
            )
            log.info("  #%s — %s", channel.name, ch_config.description)

        # --- Create general channels ---
        log.info("Creating category 'GENERAL'...")
        general_cat = await guild.create_category("GENERAL")
        general_ch = await guild.create_text_channel(
            name="general",
            category=general_cat,
            topic="General discussion",
        )
        await guild.create_text_channel(
            name="bot-commands",
            category=general_cat,
            topic="Bot configuration and commands",
        )
        log.info("  #general")
        log.info("  #bot-commands")

        # --- Create invite ---
        invite = await general_ch.create_invite(max_age=0, max_uses=0)

        # --- Summary ---
        print("\n" + "=" * 50)
        print(f"  Server: {guild.name}")
        print(f"  ID: {guild.id}")
        print(f"  Invite: {invite.url}")
        print(f"  Categories: {len(categories_created) + 1}")
        print(f"  Channels: {len(configs) + 2}")
        print("=" * 50)
        print("\nSetup complete! Next steps:")
        print(f"1. Share invite: {invite.url}")
        print("2. Deploy bot to Railway with env vars")
        print("3. Bot will auto-detect channels and start scheduling digests")

        await client.close()

    await client.start(BOT_TOKEN)


def main():
    if not BOT_TOKEN:
        print("ERROR: Set DISCORD_BOT_TOKEN in .env")
        return
    if not GUILD_ID:
        print("ERROR: Set SETUP_GUILD_ID in .env")
        print("\nTo get your server ID:")
        print("1. Create a new Discord server (click + in Discord)")
        print("2. Right-click the server name → Copy Server ID")
        print("3. Add SETUP_GUILD_ID=<id> to .env")
        print("4. Invite the bot using its OAuth2 URL")
        print("5. Re-run this script")
        return

    asyncio.run(run_setup())


if __name__ == "__main__":
    main()
