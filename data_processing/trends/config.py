from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


DEFAULT_INPUT_DIR = (
    Path("data")
    / "statistics"
    / "fy_tgiaccd"
)

DEFAULT_DETAIL_CODES_FILE = (
    Path("data")
    / "banner"
    / "detail_codes.json"
)

DEFAULT_OUTPUT_FILE = (
    Path("data")
    / "statistics"
    / "TGIACCD_Fiscal_Year_Analysis.xlsx"
)

DEFAULT_FILE_PATTERN = "TGIACCD_fy*.xlsx"

PIPELINE_VERSION = "Yearly Analytics"

DEFAULT_COLLECTION_CODES = (
    "COLL",
    "PCCS",
)

DEFAULT_CHARGE_GROUPS = (
    (
        "Tuition",
        ("TUI",),
    ),
    (
        "Room and Board",
        ("HOU", "MEA"),
    ),
    (
        "Fees",
        ("FEE",),
    ),
)

REQUIRED_COLUMNS = (
    "ID",
    "Detail Code",
    "Description",
    "Amount",
    "Balance",
    "Term",
)


@dataclass(frozen=True)
class TrendsConfig:
    input_dir: Path = DEFAULT_INPUT_DIR
    detail_codes_file: Path = DEFAULT_DETAIL_CODES_FILE
    output_file: Path = DEFAULT_OUTPUT_FILE
    file_pattern: str = DEFAULT_FILE_PATTERN
    tuition_category: str = "TUI"
    writeoff_code: str = "WOFF"
    collection_codes: tuple[
        str,
        ...,
    ] = DEFAULT_COLLECTION_CODES
    charge_groups: tuple[
        tuple[str, tuple[str, ...]], ...
    ] = DEFAULT_CHARGE_GROUPS
    strict_detail_codes: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "tuition_category",
            self.tuition_category.strip().upper(),
        )
        object.__setattr__(
            self,
            "writeoff_code",
            self.writeoff_code.strip().upper(),
        )
        object.__setattr__(
            self,
            "collection_codes",
            tuple(
                code.strip().upper()
                for code in self.collection_codes
                if code.strip()
            ),
        )

        cleaned_groups = tuple(
            (
                name.strip(),
                tuple(
                    category.strip().upper()
                    for category in categories
                    if category.strip()
                ),
            )
            for name, categories in self.charge_groups
            if name.strip()
        )

        group_names = [
            name
            for name, _ in cleaned_groups
        ]

        if len(group_names) != len(set(group_names)):
            raise ValueError(
                "Charge group names must be unique."
            )

        object.__setattr__(
            self,
            "charge_groups",
            cleaned_groups,
        )