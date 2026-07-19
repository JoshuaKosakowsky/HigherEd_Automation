from __future__ import annotations

import pandas as pd

from ..shared.cwid import clean_cwid
from .config import REQUIRED_COLUMNS


KEY_TEXT_COLUMNS = (
    "Primary Student Level Desc",
    "Primary Program",
    "Student Residency",
    "Student Residency Desc",
)


def _clean_column_name(
    value: object,
) -> str:
    """
    Remove leading, trailing, and repeated spaces
    from an Excel column name.
    """
    return " ".join(
        str(value).strip().split()
    )


def clean_population(
    df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Clean and validate the source student population.
    """
    cleaned = df.copy()

    cleaned.columns = [
        _clean_column_name(column)
        for column in cleaned.columns
    ]

    missing_columns = sorted(
        set(REQUIRED_COLUMNS)
        - set(cleaned.columns)
    )

    if missing_columns:
        raise ValueError(
            "Population workbook is missing columns: "
            f"{missing_columns}"
        )

    cleaned = cleaned.loc[
        :,
        list(REQUIRED_COLUMNS),
    ].copy()

    # Preserve the original Excel row number before
    # removing report footers.
    cleaned["__SOURCE_ROW__"] = range(
        2,
        len(cleaned) + 2,
    )

    # Remove the report footer.
    footer_mask = (
        cleaned
        .astype("string")
        .apply(
            lambda column: (
                column
                .str.strip()
                .str.startswith(
                    "Overall Count Distinct",
                    na=False,
                )
            )
        )
        .any(axis=1)
    )

    cleaned = cleaned.loc[
        ~footer_mask
    ].copy()

    for column in KEY_TEXT_COLUMNS:
        cleaned[column] = (
            cleaned[column]
            .fillna("")
            .astype(str)
            .str.strip()
        )

    cleaned["CWID"] = cleaned[
        "CWID"
    ].apply(clean_cwid)

    # Graduate Online students are identified only
    # by Primary Program beginning with X.
    online_mask = (
        cleaned["Primary Program"]
        .str.upper()
        .str.startswith(
            "X",
            na=False,
        )
    )

    standard_mask = ~online_mask

    # Only ordinary buckets require level and
    # residency values. Graduate Online students
    # are placed in their own combined bucket.
    blank_required = {
        column: cleaned.loc[
            standard_mask
            & cleaned[column].eq(""),
            "__SOURCE_ROW__",
        ].tolist()
        for column in (
            "Primary Student Level Desc",
            "Student Residency",
        )
        if (
            standard_mask
            & cleaned[column].eq("")
        ).any()
    }

    if blank_required:
        details = "; ".join(
            f"{column}: rows {rows[:20]}"
            for column, rows
            in blank_required.items()
        )

        raise ValueError(
            "Required bucket fields are blank. "
            f"{details}"
        )

    raw_credits = cleaned[
        "Registered Credits"
    ]

    normalized_credits = raw_credits.apply(
        lambda value: (
            value.strip()
            if isinstance(value, str)
            else value
        )
    )

    blank_credit_mask = (
        normalized_credits.isna()
        | normalized_credits.eq("")
    )

    numeric_credits = pd.to_numeric(
        normalized_credits,
        errors="coerce",
    )

    # Credit values are required only for ordinary
    # buckets. Graduate Online students are tested
    # at 100% regardless of their registered credits.
    invalid_credit_mask = (
        standard_mask
        & ~blank_credit_mask
        & numeric_credits.isna()
    )

    if invalid_credit_mask.any():
        bad_values = cleaned.loc[
            invalid_credit_mask,
            [
                "__SOURCE_ROW__",
                "CWID",
                "Student Last Name",
                "Student First Name",
                "Registered Credits",
            ],
        ]

        details = bad_values.to_dict(
            orient="records"
        )

        raise ValueError(
            "Registered Credits contains "
            "nonnumeric values:\n"
            f"{details[:20]}"
        )

    missing_credit_mask = (
        standard_mask
        & blank_credit_mask
    )

    if missing_credit_mask.any():
        missing_values = cleaned.loc[
            missing_credit_mask,
            [
                "__SOURCE_ROW__",
                "CWID",
                "Student Last Name",
                "Student First Name",
            ],
        ]

        details = missing_values.to_dict(
            orient="records"
        )

        raise ValueError(
            "Registered Credits is blank for "
            "the following students:\n"
            f"{details[:20]}"
        )

    cleaned[
        "Registered Credits"
    ] = numeric_credits

    return cleaned