"""Read the per-user settings written by ``shared/user_settings.ps1``."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


DEFAULT_FIRST_NAME = "User"


@dataclass(frozen=True)
class AutomationUserSettings:
    display_name: str
    initials: str

    @property
    def first_name(self) -> str:
        return self.display_name.split(maxsplit=1)[0]


def get_user_settings_path(
    environment: Mapping[str, str] | None = None,
) -> Path | None:
    values = os.environ if environment is None else environment
    local_app_data = values.get("LOCALAPPDATA", "").strip()
    if not local_app_data:
        return None
    return Path(local_app_data) / "HigherEdAutomation" / "user-settings.json"


def read_automation_user_settings(
    settings_path: Path | None = None,
) -> AutomationUserSettings | None:
    """Return valid settings, or ``None`` when setup has not supplied them."""
    path = settings_path if settings_path is not None else get_user_settings_path()
    if path is None or not path.is_file():
        return None

    try:
        # Windows PowerShell 5.1 may write a UTF-8 byte-order mark.
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None

    if not isinstance(payload, dict) or payload.get("SchemaVersion") != 1:
        return None

    display_name = payload.get("DisplayName")
    initials = payload.get("Initials")
    if not isinstance(display_name, str) or not isinstance(initials, str):
        return None

    display_name = display_name.strip()
    initials = initials.strip().upper()
    if (
        not display_name
        or len(display_name) > 100
        or "\n" in display_name
        or "\r" in display_name
        or not (2 <= len(initials) <= 6)
        or not initials.isascii()
        or not initials.isalpha()
    ):
        return None

    return AutomationUserSettings(display_name=display_name, initials=initials)


def get_automation_user_first_name(settings_path: Path | None = None) -> str:
    settings = read_automation_user_settings(settings_path)
    return settings.first_name if settings is not None else DEFAULT_FIRST_NAME
