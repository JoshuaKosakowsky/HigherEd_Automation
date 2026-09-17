"""Resolve institution-managed local paths without workstation-specific names."""

from __future__ import annotations

import ctypes
import os
import sys
from collections.abc import Mapping
from pathlib import Path


ONEDRIVE_ENVIRONMENT_VARIABLE = "OneDriveCommercial"
ONEDRIVE_FALLBACK_DIRECTORY = "OneDrive - Colorado School of Mines"
GUI_ACCESS_RELATIVE_DIRECTORY = Path(
    "GRP-Bursar Office - General",
    "Y-Brswork",
    "Staff Folders",
    ".highered_automation",
)
GUI_ACCESS_FILENAME = "gui_access.json"
WINDOWS_HIDDEN_ATTRIBUTE = 0x2
INVALID_WINDOWS_ATTRIBUTES = 0xFFFFFFFF


class MinesPathError(RuntimeError):
    """Raised when a required Mines-managed local path cannot be resolved."""


def get_mines_onedrive_root(
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Return the locally synchronized Mines OneDrive root."""
    values = os.environ if environment is None else environment
    configured = values.get(ONEDRIVE_ENVIRONMENT_VARIABLE, "").strip()
    if configured:
        return Path(configured)

    user_profile = values.get("USERPROFILE", "").strip()
    if user_profile:
        return Path(user_profile) / ONEDRIVE_FALLBACK_DIRECTORY

    raise MinesPathError(
        "The Mines OneDrive location could not be resolved. Confirm OneDrive "
        "is signed in and OneDriveCommercial is available."
    )


def get_shared_gui_access_path(
    environment: Mapping[str, str] | None = None,
) -> Path:
    """Return the shared Bursar GUI access-policy path."""
    return (
        get_mines_onedrive_root(environment)
        / GUI_ACCESS_RELATIVE_DIRECTORY
        / GUI_ACCESS_FILENAME
    )


def ensure_hidden_directory(
    directory: Path,
    *,
    platform: str = sys.platform,
) -> None:
    """Create a directory and apply Windows' cosmetic Hidden attribute."""
    directory.mkdir(parents=True, exist_ok=True)
    if platform != "win32":
        return

    kernel32 = ctypes.windll.kernel32
    attributes = kernel32.GetFileAttributesW(str(directory))
    if attributes == INVALID_WINDOWS_ATTRIBUTES:
        raise MinesPathError(f"Windows could not inspect the folder: {directory}")
    if not kernel32.SetFileAttributesW(
        str(directory), attributes | WINDOWS_HIDDEN_ATTRIBUTE
    ):
        raise MinesPathError(f"Windows could not hide the folder: {directory}")
