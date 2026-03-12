from __future__ import annotations

import os
import aiosqlite
from datetime import datetime, timezone


DB_PATH = os.getenv("DB_PATH", os.path.join(os.path.dirname(__file__), "bot_data.db"))


class Database:
    def __init__(self, path: str = DB_PATH):
        self.path = path
        self._db: aiosqlite.Connection | None = None

    async def connect(self):
        self._db = await aiosqlite.connect(self.path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS channel_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_name TEXT NOT NULL,
                guild_id INTEGER NOT NULL,
                username TEXT NOT NULL,
                added_at TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_channel_sources
                ON channel_sources(channel_name, guild_id, username);

            CREATE TABLE IF NOT EXISTS channel_schedules (
                channel_name TEXT NOT NULL,
                guild_id INTEGER NOT NULL,
                cron_time TEXT NOT NULL,
                lookback_hours INTEGER NOT NULL DEFAULT 24,
                PRIMARY KEY (channel_name, guild_id)
            );

            CREATE TABLE IF NOT EXISTS channel_prompts (
                channel_name TEXT NOT NULL,
                guild_id INTEGER NOT NULL,
                prompt_overlay TEXT NOT NULL,
                PRIMARY KEY (channel_name, guild_id)
            );

            CREATE TABLE IF NOT EXISTS channel_mappings (
                channel_name TEXT NOT NULL,
                guild_id INTEGER NOT NULL,
                discord_channel_id INTEGER NOT NULL,
                PRIMARY KEY (channel_name, guild_id)
            );

            CREATE TABLE IF NOT EXISTS last_digest (
                channel_name TEXT NOT NULL,
                guild_id INTEGER NOT NULL,
                digest_type TEXT NOT NULL DEFAULT 'x',
                sent_at TEXT NOT NULL,
                PRIMARY KEY (channel_name, guild_id, digest_type)
            );
        """)
        await self._db.commit()

    async def close(self):
        if self._db:
            await self._db.close()

    # -- Channel source management --

    async def get_sources(self, channel_name: str, guild_id: int) -> list[str]:
        cursor = await self._db.execute(
            "SELECT username FROM channel_sources WHERE channel_name = ? AND guild_id = ? ORDER BY username",
            (channel_name, guild_id),
        )
        rows = await cursor.fetchall()
        return [r["username"] for r in rows]

    async def add_source(self, channel_name: str, guild_id: int, username: str) -> bool:
        username = username.lstrip("@").lower()
        try:
            await self._db.execute(
                "INSERT INTO channel_sources (channel_name, guild_id, username, added_at) VALUES (?, ?, ?, ?)",
                (channel_name, guild_id, username, datetime.now(timezone.utc).isoformat()),
            )
            await self._db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

    async def remove_source(self, channel_name: str, guild_id: int, username: str) -> bool:
        username = username.lstrip("@").lower()
        cursor = await self._db.execute(
            "DELETE FROM channel_sources WHERE channel_name = ? AND guild_id = ? AND username = ?",
            (channel_name, guild_id, username),
        )
        await self._db.commit()
        return cursor.rowcount > 0

    async def init_default_sources(self, channel_name: str, guild_id: int, defaults: list[str]):
        existing = await self.get_sources(channel_name, guild_id)
        if not existing:
            for username in defaults:
                await self.add_source(channel_name, guild_id, username)

    # -- Schedule overrides --

    async def get_schedule(self, channel_name: str, guild_id: int) -> tuple[str, int] | None:
        cursor = await self._db.execute(
            "SELECT cron_time, lookback_hours FROM channel_schedules WHERE channel_name = ? AND guild_id = ?",
            (channel_name, guild_id),
        )
        row = await cursor.fetchone()
        if row:
            return row["cron_time"], row["lookback_hours"]
        return None

    async def set_schedule(self, channel_name: str, guild_id: int, cron_time: str, lookback_hours: int = 24):
        await self._db.execute(
            "INSERT OR REPLACE INTO channel_schedules (channel_name, guild_id, cron_time, lookback_hours) VALUES (?, ?, ?, ?)",
            (channel_name, guild_id, cron_time, lookback_hours),
        )
        await self._db.commit()

    # -- Prompt overrides --

    async def get_prompt(self, channel_name: str, guild_id: int) -> str | None:
        cursor = await self._db.execute(
            "SELECT prompt_overlay FROM channel_prompts WHERE channel_name = ? AND guild_id = ?",
            (channel_name, guild_id),
        )
        row = await cursor.fetchone()
        return row["prompt_overlay"] if row else None

    async def set_prompt(self, channel_name: str, guild_id: int, prompt: str):
        await self._db.execute(
            "INSERT OR REPLACE INTO channel_prompts (channel_name, guild_id, prompt_overlay) VALUES (?, ?, ?)",
            (channel_name, guild_id, prompt),
        )
        await self._db.commit()

    async def clear_prompt(self, channel_name: str, guild_id: int):
        await self._db.execute(
            "DELETE FROM channel_prompts WHERE channel_name = ? AND guild_id = ?",
            (channel_name, guild_id),
        )
        await self._db.commit()

    # -- Channel mappings (channel_name -> discord channel ID) --

    async def set_channel_mapping(self, channel_name: str, guild_id: int, discord_channel_id: int):
        await self._db.execute(
            "INSERT OR REPLACE INTO channel_mappings (channel_name, guild_id, discord_channel_id) VALUES (?, ?, ?)",
            (channel_name, guild_id, discord_channel_id),
        )
        await self._db.commit()

    async def get_channel_mapping(self, channel_name: str, guild_id: int) -> int | None:
        cursor = await self._db.execute(
            "SELECT discord_channel_id FROM channel_mappings WHERE channel_name = ? AND guild_id = ?",
            (channel_name, guild_id),
        )
        row = await cursor.fetchone()
        return row["discord_channel_id"] if row else None

    async def get_channel_name_by_discord_id(self, discord_channel_id: int) -> str | None:
        cursor = await self._db.execute(
            "SELECT channel_name FROM channel_mappings WHERE discord_channel_id = ?",
            (discord_channel_id,),
        )
        row = await cursor.fetchone()
        return row["channel_name"] if row else None

    async def get_all_channel_mappings(self, guild_id: int) -> dict[str, int]:
        cursor = await self._db.execute(
            "SELECT channel_name, discord_channel_id FROM channel_mappings WHERE guild_id = ?",
            (guild_id,),
        )
        rows = await cursor.fetchall()
        return {r["channel_name"]: r["discord_channel_id"] for r in rows}

    # -- Last digest tracking --

    async def set_last_digest(self, channel_name: str, guild_id: int, digest_type: str = "x"):
        await self._db.execute(
            "INSERT OR REPLACE INTO last_digest (channel_name, guild_id, digest_type, sent_at) VALUES (?, ?, ?, ?)",
            (channel_name, guild_id, digest_type, datetime.now(timezone.utc).isoformat()),
        )
        await self._db.commit()

    async def get_last_digest(self, channel_name: str, guild_id: int, digest_type: str = "x") -> datetime | None:
        cursor = await self._db.execute(
            "SELECT sent_at FROM last_digest WHERE channel_name = ? AND guild_id = ? AND digest_type = ?",
            (channel_name, guild_id, digest_type),
        )
        row = await cursor.fetchone()
        if row:
            return datetime.fromisoformat(row["sent_at"])
        return None
