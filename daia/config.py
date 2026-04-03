"""Configuration management for Zeph."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


APP_DIR = Path.home() / ".daia"
CONFIG_PATH = APP_DIR / "config.json"
SCRIPTS_DIR = APP_DIR / "scripts"
LOG_PATH = APP_DIR / "activity.log"
DB_PATH = APP_DIR / "memory.db"


@dataclass(slots=True)
class ConfirmConfig:
    """Describes which action types need user confirmation."""

    delete_file: bool = True
    kill_process: bool = True
    submit_form: bool = True
    close_window: bool = False
    browser_navigation: bool = False
    script_execution: bool = True


@dataclass(slots=True)
class AgentConfig:
    """Persistent user and runtime settings."""

    agent_name: str = "Zeph"
    user_name: str = ""
    ai_provider: str = "anthropic"
    ai_model: str = "claude-sonnet-4-20250514"
    browser_mode: str = "default"
    api_key: str = ""
    preferred_wpm: int = 80
    wake_word: str = "Hey DAIA"
    voice_rate: int = 180
    voice_language: str = "en-US"
    speed_mode: str = "normal"
    speed_multiplier: float = 1.0
    dry_run_default: bool = False
    typing_typo_rate: float = 0.02
    pause_after_punctuation: bool = True
    clipboard_history_limit: int = 20
    confirm: ConfirmConfig = field(default_factory=ConfirmConfig)
    per_app_profiles: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert config to a JSON-serializable mapping."""

        data = asdict(self)
        data["confirm"] = asdict(self.confirm)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentConfig":
        """Create config from a dictionary."""

        confirm = ConfirmConfig(**data.get("confirm", {}))
        merged = {**data, "confirm": confirm}
        return cls(**merged)


class ConfigManager:
    """Loads and stores Zeph configuration."""

    def __init__(self, path: Path = CONFIG_PATH) -> None:
        self.path = path
        self.ensure_directories()

    @staticmethod
    def ensure_directories() -> None:
        """Create all app directories if they do not already exist."""

        APP_DIR.mkdir(parents=True, exist_ok=True)
        SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)

    def exists(self) -> bool:
        """Return whether the config file exists."""

        return self.path.exists()

    def load(self) -> AgentConfig:
        """Load config from disk or return defaults."""

        if not self.path.exists():
            return AgentConfig()
        with self.path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return AgentConfig.from_dict(payload)

    def save(self, config: AgentConfig) -> None:
        """Persist config to disk."""

        self.ensure_directories()
        with self.path.open("w", encoding="utf-8") as handle:
            json.dump(config.to_dict(), handle, indent=2)

    def update(self, **fields: Any) -> AgentConfig:
        """Update a subset of config fields and save them."""

        config = self.load()
        for key, value in fields.items():
            if key == "confirm" and isinstance(value, dict):
                config.confirm = ConfirmConfig(**value)
            else:
                setattr(config, key, value)
        self.save(config)
        return config
