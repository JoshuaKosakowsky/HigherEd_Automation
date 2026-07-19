from __future__ import annotations

import hashlib
import math

import pandas as pd


def _stable_seed(
    bucket_id: str,
    base_seed: int,
) -> int:
    """
    Create a repeatable random seed for each bucket.
    """
    value = f"{base_seed}:{bucket_id}"

    digest = hashlib.sha256(
        value.encode("utf-8")
    ).digest()

    return int.from_bytes(
        digest[:4],
        "big",
    )


def select_testing_sample(
    bucketed_df: pd.DataFrame,
    *,
    sample_fraction: float | None,
    random_seed: int,
) -> pd.DataFrame:
    """
    Select a reproducible proportional sample from
    each ordinary bucket.

    All Graduate Online students are selected.
    """
    result = bucketed_df.copy()

    result["SELECTED_FOR_TESTING"] = False

    online_mask = result["IS_GRAD_ONLINE"]

    result.loc[
        online_mask,
        "SELECTED_FOR_TESTING",
    ] = True

    if (
        sample_fraction is None
        or sample_fraction == 0
    ):
        return result

    standard_students = result.loc[
        ~online_mask
    ]

    grouped = standard_students.groupby(
        "BUCKET_ID",
        sort=True,
    )

    for bucket_id, group in grouped:
        # Upward rounding ensures that a small,
        # nonempty bucket receives at least one
        # selected student.
        sample_size = math.ceil(
            len(group) * sample_fraction
        )

        sample_size = min(
            len(group),
            sample_size,
        )

        selected_indexes = group.sample(
            n=sample_size,
            random_state=_stable_seed(
                str(bucket_id),
                random_seed,
            ),
        ).index

        result.loc[
            selected_indexes,
            "SELECTED_FOR_TESTING",
        ] = True

    return result