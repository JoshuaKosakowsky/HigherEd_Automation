"""Read the same Banner term configuration used by the PowerShell workflows."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = (
    PROJECT_ROOT / "config" / "institutions" / "mines" / "banner_terms.json"
)


@dataclass(frozen=True)
class BannerTerm:
    code: str
    name: str
    start_date: date
    end_date: date


def get_banner_term(
    target_date: date | None = None,
    *,
    config_path: Path = DEFAULT_CONFIG_PATH,
) -> BannerTerm:
    """Resolve a date using the institution's audited term boundaries."""
    selected_date = target_date or date.today()
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Banner term configuration must be a JSON object.")
    if payload.get("schemaVersion") != 1:
        raise ValueError("Unsupported Banner term configuration schema.")
    if payload.get("termCodeYear") != "calendarYear":
        raise ValueError("Unsupported Banner term year rule.")

    definitions = payload.get("terms")
    if not isinstance(definitions, list):
        raise ValueError("Banner term configuration has no term list.")

    for definition in definitions:
        if not isinstance(definition, dict):
            raise ValueError("Banner term configuration contains an invalid term.")
        try:
            start_date = date.fromisoformat(
                f"{selected_date.year}-{definition['startMonthDay']}"
            )
            end_date = date.fromisoformat(
                f"{selected_date.year}-{definition['endMonthDay']}"
            )
            code_suffix = str(definition["codeSuffix"])
            term_name = str(definition["name"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(
                "Banner term configuration contains an invalid term."
            ) from error
        if start_date <= selected_date <= end_date:
            return BannerTerm(
                code=f"{selected_date.year}{code_suffix}",
                name=f"{term_name} {selected_date.year}",
                start_date=start_date,
                end_date=end_date,
            )

    raise ValueError(f"No Banner term is configured for {selected_date:%Y-%m-%d}.")
