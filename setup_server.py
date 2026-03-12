"""
Discord server setup script.

Creates the TechTalk server with all channels, categories, roles,
and transfers ownership to the specified user.

Usage:
    python setup_server.py

Requires DISCORD_BOT_TOKEN and OWNER_USER_ID in .env
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

SERVER_NAME = "TechTalk"
SERVER_ICON = None  # Set to path of icon file if desired


async def run_setup():
    intents = discord.Intents.default()
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        log.info("Bot logged in as %s", client.user)

        if not OWNER_ID:
            log.error("OWNER_USER_ID not set in .env — cannot transfer ownership.")
            await client.close()
            return

        # --- Create server ---
        log.info("Creating server '%s'...", SERVER_NAME)
        guild = await client.create_guild(name=SERVER_NAME)
        log.info("Server created: %s (ID: %s)", guild.name, guild.id)

        # Refetch guild to get full data
        await asyncio.sleep(2)
        guild = client.get_guild(guild.id)
        if not guild:
            # Fallback: fetch from API
            guild = await client.fetch_guild(guild.id)

        # --- Delete default channels ---
        for ch in guild.channels:
            try:
                await ch.delete()
            except Exception:
                pass

        # --- Create roles ---
        log.info("Creating roles...")
        admin_role = await guild.create_role(
            name="Admin",
            permissions=discord.Permissions(administrator=True),
            color=discord.Color.red(),
            hoist=True,
        )
        log.info("  Created @Admin role")

        member_role = await guild.create_role(
            name="Member",
            permissions=discord.Permissions(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                embed_links=True,
                attach_files=True,
                add_reactions=True,
            ),
            color=discord.Color.blue(),
            hoist=True,
        )
        log.info("  Created @Member role")

        bot_role = await guild.create_role(
            name="TechTalk Bot",
            permissions=discord.Permissions(
                view_channel=True,
                send_messages=True,
                embed_links=True,
                read_message_history=True,
                manage_channels=True,
                manage_guild=True,
            ),
            color=discord.Color.green(),
        )
        log.info("  Created @TechTalk Bot role")

        # Assign bot role to self
        bot_member = guild.get_member(client.user.id)
        if bot_member:
            await bot_member.add_roles(bot_role)

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
            log.info("  #%s", channel.name)

        # --- Create general channels ---
        log.info("Creating category 'GENERAL'...")
        general_cat = await guild.create_category("GENERAL")
        general_ch = await guild.create_text_channel(
            name="general",
            category=general_cat,
            topic="General discussion",
        )
        bot_commands_ch = await guild.create_text_channel(
            name="bot-commands",
            category=general_cat,
            topic="Bot configuration and commands",
        )
        log.info("  #general")
        log.info("  #bot-commands")

        # --- Create invite ---
        invite = await general_ch.create_invite(max_age=0, max_uses=0)
        log.info("Invite link: %s", invite.url)

        # --- Transfer ownership ---
        log.info("Transferring ownership to user ID %s...", OWNER_ID)
        try:
            await guild.edit(owner=discord.Object(id=OWNER_ID))
            log.info("Ownership transferred successfully!")
        except discord.HTTPException as e:
            log.error("Could not transfer ownership: %s", e)
            log.info("You may need to join the server first, then run transfer manually.")
            log.info("The bot will remain as owner until transferred.")

        # --- Summary ---
        print("\n" + "=" * 50)
        print(f"  Server: {guild.name}")
        print(f"  ID: {guild.id}")
        print(f"  Invite: {invite.url}")
        print(f"  Channels: {len(guild.channels)}")
        print(f"  Owner transfer: {'Success' if guild.owner_id == OWNER_ID else 'Pending — join server first'}")
        print("=" * 50)
        print("\nNext steps:")
        print("1. Join the server using the invite link above")
        print("2. If ownership wasn't transferred, run: /config transfer_ownership")
        print("3. Set up the bot with: python bot.py")
        print("4. Add DISCORD_BOT_TOKEN and other env vars to Railway")

        await client.close()

    await client.start(BOT_TOKEN)


def main():
    if not BOT_TOKEN:
        print("ERROR: Set DISCORD_BOT_TOKEN in .env")
        return
    if not OWNER_ID:
        print("ERROR: Set OWNER_USER_ID in .env (your Discord user ID)")
        print("To find your ID: Settings > Advanced > Developer Mode > Right-click your name > Copy User ID")
        return

    asyncio.run(run_setup())


if __name__ == "__main__":
    main()
