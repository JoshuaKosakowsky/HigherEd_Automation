from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path



REQUIRED_COLUMNS = (
    "Row",
    "Term",
    "Term Desc",
    "FERPA Confidential",
    "Student Last Name",
    "Student First Name",
    "Student Middle Name",
    "CWID",
    "Primary Student Level Desc",
    "Student Classification",
    "Student Population Desc",
    "Primary Program",
    "Primary 1st Dept Desc",
    "Primary 1st Major Desc",
    "Registered Credits",
    "Cumulative Credits Earned",
    "Student Residency",
    "Student Residency Desc",
    "Primary Ethnicity",
    "Primary Ethnicity Desc",
    "Articulation Agreement Attribute",
    "Articulation Agreement Attribute Desc",
)

DEFAULT_INPUT_FILE = (
    Path("data")
    / "semester_testing"
    / "Testing Pop.xlsx"
)

DEFAULT_OUTPUT_FILE = (
    Path("data")
    / "semester_testing"
    / "Testing Pop - Bucketed.xlsx"
)

DEFAULT_SAMPLE_FRACTION = 0.25

DEFAULT_STAFF_NAMES = (
    "Jenny",
    "Stanley",
    "Josh",
    "Shawnti",
    "Anita",
    "Zule",
    "Sara",
    "Ashley",
    "Lacey",
    "Additional Accounts",
)

DEFAULT_RANDOM_SEED = int(
    date.today().strftime("%Y%m%d")
)


@dataclass(frozen=True)
class CreditBand:
    code: str
    description: str
    minimum: float
    maximum: float | None
    maximum_inclusive: bool = True
    minimum_inclusive: bool = True

    def contains(
        self,
        credits: float,
    ) -> bool:
        if self.minimum_inclusive:
            if credits < self.minimum:
                return False
        else:
            if credits <= self.minimum:
                return False

        if self.maximum is None:
            return True

        if self.maximum_inclusive:
            return credits <= self.maximum

        return credits < self.maximum


CREDIT_BANDS = {
    "Undergraduate": (
        CreditBand(
            "0-2.5",
            "Credits between 0 and 2.5",
            0,
            2.5,
        ),
        CreditBand(
            "3-5.5",
            "Credits between 3 and 5.5",
            3,
            5.5,
        ),
        CreditBand(
            "6-19",
            "Credits between 6 and 19",
            6,
            19,
        ),
        CreditBand(
            ">19",
            "Credits over 19",
            19,
            None,
            minimum_inclusive=False,
        ),
    ),
    "Graduate": (
        CreditBand(
            "0-2.5",
            "Credits between 0 and 2.5",
            0,
            2.5,
        ),
        CreditBand(
            "3-5.5",
            "Credits between 3 and 5.5",
            3,
            5.5,
        ),
        CreditBand(
            "6-15",
            "Credits between 6 and 15",
            6,
            15,
        ),
        CreditBand(
            ">15",
            "Credits over 15",
            15,
            None,
            minimum_inclusive=False,
        ),
    ),
}


@dataclass(frozen=True)
class PopulationTestingConfig:
    input_file: Path = DEFAULT_INPUT_FILE
    output_file: Path = DEFAULT_OUTPUT_FILE
    sheet_name: str | int = 0
    sample_fraction: float = DEFAULT_SAMPLE_FRACTION
    staff_names: tuple[str, ...] = DEFAULT_STAFF_NAMES
    random_seed: int = DEFAULT_RANDOM_SEED

    def __post_init__(self) -> None:
        if not 0 <= self.sample_fraction <= 1:
            raise ValueError(
                "sample_fraction must be between 0 and 1."
            )

        cleaned_staff = tuple(
            name.strip()
            for name in self.staff_names
            if name.strip()
        )

        if len(cleaned_staff) != len(set(cleaned_staff)):
            raise ValueError(
                "Staff names must be unique."
            )

        object.__setattr__(
            self,
            "staff_names",
            cleaned_staff,
        )