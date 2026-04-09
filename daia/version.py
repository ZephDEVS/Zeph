"""Shared version helpers for Zeph."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _runtime_root() -> Path:
    if hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parent.parent


VERSION_PATH = _runtime_root() / "VERSION"
DEFAULT_UPDATE_MANIFEST_URL = os.getenv(
    "ZEPH_UPDATE_MANIFEST_URL",
    "https://zeph-lake.vercel.app/downloads/latest-macos.json",
)


def get_app_version() -> str:
    """Return the current Zeph app version."""

    try:
        value = VERSION_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return "0.0.0"
    return value or "0.0.0"


APP_VERSION = get_app_version()
