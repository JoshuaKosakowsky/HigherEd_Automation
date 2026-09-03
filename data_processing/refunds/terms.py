from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re


TERM_PATTERN = re.compile(r"^\d{4}(10|50|55|60|80)$")


def validate_term(term: str) -> str:
    """Return a stripped Banner term or raise for an unsupported term."""
    value = str(term).strip()
    if not TERM_PATTERN.fullmatch(value):
        raise ValueError(
            "Banner term must be six digits and end in 10, 50, 55, 60, or 80."
        )
    return value


def derive_target_term(run_date: date) -> str:
    """Return the Mines term containing *run_date*."""
    if run_date <= date(run_date.year, 5, 15):
        suffix = "10"
    elif run_date <= date(run_date.year, 7, 15):
        suffix = "55"
    else:
        suffix = "80"
    return f"{run_date.year}{suffix}"


def previous_term(target_term: str, override: str | None = None) -> str:
    """Return the immediately preceding Mines term."""
    if override is not None:
        return validate_term(override)

    term = validate_term(target_term)
    year = int(term[:4])
    suffix = term[-2:]
    values = {
        "10": f"{year - 1}80",
        "50": f"{year}10",
        "55": f"{year}10",
        "60": f"{year}50",
        "80": f"{year}55",
    }
    return values[suffix]


def fiscal_year_start(term: object) -> int | None:
    """Map a supported Banner term to the Mines Fall-through-Summer FY."""
    value = str(term).strip()
    if not TERM_PATTERN.fullmatch(value):
        return None
    year = int(value[:4])
    return year if value.endswith("80") else year - 1


@dataclass(frozen=True)
class RefundParameters:
    """Run-specific policy inputs for the local allocation engine."""

    target_term: str
    run_date: date
    previous_term_override: str | None = None
    title_iv_cross_fy_cap: str = "200.00"

    def __post_init__(self) -> None:
        validate_term(self.target_term)
        if self.previous_term_override is not None:
            validate_term(self.previous_term_override)

    @property
    def previous_term(self) -> str:
        return previous_term(self.target_term, self.previous_term_override)

    @property
    def current_fiscal_year_start(self) -> int:
        result = fiscal_year_start(self.target_term)
        if result is None:  # guarded by validation, retained for type checking
            raise ValueError(f"Unsupported target term: {self.target_term}")
        return result
