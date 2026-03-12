from __future__ import annotations

import os
import yaml
from dataclasses import dataclass, field
from typing import Optional

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "channels.yaml")


@dataclass
class ChannelConfig:
    name: str
    category: str
    description: str
    cron_time: str  # "HH:MM" in configured timezone
    lookback_hours: int
    color: int
    default_sources: list[str]
    tavily_queries: list[str]
    prompt_overlay: str

    @property
    def cron_hour(self) -> int:
        return int(self.cron_time.split(":")[0])

    @property
    def cron_minute(self) -> int:
        return int(self.cron_time.split(":")[1])


def load_channel_configs(path: str = CONFIG_PATH) -> dict[str, ChannelConfig]:
    with open(path) as f:
        raw = yaml.safe_load(f)

    configs = {}
    for name, data in raw.get("channels", {}).items():
        configs[name] = ChannelConfig(
            name=name,
            category=data.get("category", "GENERAL"),
            description=data.get("description", ""),
            cron_time=data.get("cron_time", "07:00"),
            lookback_hours=data.get("lookback_hours", 24),
            color=data.get("color", 0x1A1A2E),
            default_sources=data.get("default_sources", []),
            tavily_queries=data.get("tavily_queries", []),
            prompt_overlay=data.get("prompt_overlay", ""),
        )
    return configs


def get_timezone_str(path: str = CONFIG_PATH) -> str:
    with open(path) as f:
        raw = yaml.safe_load(f)
    return raw.get("timezone", "America/Chicago")
