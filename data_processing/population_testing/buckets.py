from __future__ import annotations

import re

import pandas as pd

from .config import CREDIT_BANDS


RESIDENCY_GROUPS = {
    "R": "RL",
    "L": "RL",
    "N": "N",
}

RESIDENCY_DESCRIPTIONS = {
    "RL": "Resident (R and L)",
    "N": "Nonresident",
}


def _credit_band(
    level: str,
    credits: float,
) -> tuple[str, str] | None:
    """
    Return the student's registered-credit bucket.
    """
    if pd.isna(credits):
        return None

    for band in CREDIT_BANDS.get(
        level,
        (),
    ):
        if band.contains(
            float(credits)
        ):
            return (
                band.code,
                band.description,
            )

    return None


def _sheet_name(
    bucket_id: str,
    residency_bucket: str,
    level: str,
    credit_code: str,
) -> str:
    """
    Create a compact Excel-safe worksheet name.
    """
    level_code = (
        "UG"
        if level == "Undergraduate"
        else "GR"
    )

    name = (
        f"{bucket_id} "
        f"{residency_bucket} "
        f"{level_code} "
        f"{credit_code}"
    )

    name = re.sub(
        r"[\\/*?:\[\]]",
        "-",
        name,
    )

    return name[:31]


def assign_population_buckets(
    df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Assign each student to one mutually exclusive
    population-testing bucket.

    Ordinary buckets use:

        Residency group
        Student level
        Registered-credit range

    Primary Program, department, and major values are
    ignored, except that programs beginning with X
    are placed in the Graduate Online bucket.
    """
    result = df.copy()

    # Preserve the original Student Residency value.
    # RESIDENCY_BUCKET is used only for grouping.
    result["RESIDENCY_BUCKET"] = ""

    result["IS_GRAD_ONLINE"] = (
        result["Primary Program"]
        .str.upper()
        .str.startswith(
            "X",
            na=False,
        )
    )

    online_mask = result[
        "IS_GRAD_ONLINE"
    ]

    standard_mask = ~online_mask

    standard_residency_codes = (
        result.loc[
            standard_mask,
            "Student Residency",
        ]
        .str.upper()
    )

    invalid_residency_codes = sorted(
        set(standard_residency_codes)
        - set(RESIDENCY_GROUPS)
    )

    if invalid_residency_codes:
        raise ValueError(
            "Unsupported Student Residency values: "
            f"{invalid_residency_codes}"
        )

    result.loc[
        standard_mask,
        "RESIDENCY_BUCKET",
    ] = standard_residency_codes.map(
        RESIDENCY_GROUPS
    )

    # The source Student Residency column is not
    # modified. An L student continues to display L.
    result.loc[
        online_mask,
        "RESIDENCY_BUCKET",
    ] = "ALL"

    result["CREDIT_BUCKET"] = ""
    result["__CREDIT_DESCRIPTION__"] = ""

    standard = result.loc[
        standard_mask
    ]

    invalid_levels = sorted(
        set(
            standard[
                "Primary Student Level Desc"
            ]
        )
        - set(CREDIT_BANDS)
    )

    if invalid_levels:
        raise ValueError(
            "Unsupported Primary Student Level Desc "
            f"values: {invalid_levels}"
        )

    unmatched_rows: list[int] = []

    for index, row in standard.iterrows():
        band = _credit_band(
            row["Primary Student Level Desc"],
            row["Registered Credits"],
        )

        if band is None:
            unmatched_rows.append(
                int(row["__SOURCE_ROW__"])
            )
            continue

        result.at[
            index,
            "CREDIT_BUCKET",
        ] = band[0]

        result.at[
            index,
            "__CREDIT_DESCRIPTION__",
        ] = band[1]

    if unmatched_rows:
        raise ValueError(
            "Some Registered Credits values do not "
            "fit the stated credit bands. "
            f"Excel rows: {unmatched_rows[:30]}"
        )

    result["BUCKET_ID"] = ""
    result["BUCKET_SHEET"] = ""
    result["BUCKET_NAME"] = ""

    # All X programs are placed together and tested
    # at 100%.
    if online_mask.any():
        result.loc[
            online_mask,
            "BUCKET_ID",
        ] = "B000"

        result.loc[
            online_mask,
            "BUCKET_SHEET",
        ] = "B000 Graduate Online"

        result.loc[
            online_mask,
            "BUCKET_NAME",
        ] = (
            "Graduate Online - all Primary Programs "
            "beginning with X"
        )

        result.loc[
            online_mask,
            "CREDIT_BUCKET",
        ] = "ALL"

    group_columns = [
        "RESIDENCY_BUCKET",
        "Primary Student Level Desc",
        "CREDIT_BUCKET",
    ]

    grouped = (
        result.loc[standard_mask]
        .groupby(
            group_columns,
            sort=True,
            dropna=False,
        )
    )

    for number, (
        key,
        indexes,
    ) in enumerate(
        grouped.groups.items(),
        start=1,
    ):
        (
            residency_bucket,
            level,
            credit_code,
        ) = key

        bucket_id = f"B{number:03d}"

        credit_description = result.loc[
            indexes[0],
            "__CREDIT_DESCRIPTION__",
        ]

        residency_description = (
            RESIDENCY_DESCRIPTIONS[
                residency_bucket
            ]
        )

        bucket_name = ", ".join(
            (
                residency_description,
                str(level),
                str(credit_description),
            )
        )

        result.loc[
            indexes,
            "BUCKET_ID",
        ] = bucket_id

        result.loc[
            indexes,
            "BUCKET_SHEET",
        ] = _sheet_name(
            bucket_id,
            str(residency_bucket),
            str(level),
            str(credit_code),
        )

        result.loc[
            indexes,
            "BUCKET_NAME",
        ] = bucket_name

    return result.drop(
        columns=[
            "__CREDIT_DESCRIPTION__",
        ]
    )