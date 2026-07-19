from __future__ import annotations

import hashlib

import pandas as pd


ADDITIONAL_ACCOUNTS = "Additional Accounts"


def _stable_seed(
    purpose: str,
    group_name: str,
    base_seed: int,
) -> int:
    """
    Create a reproducible seed for an assignment
    operation.
    """
    value = (
        f"{purpose}:"
        f"{base_seed}:"
        f"{group_name}"
    )

    digest = hashlib.sha256(
        value.encode("utf-8")
    ).digest()

    return int.from_bytes(
        digest[:4],
        "big",
    )


def assign_testing_staff(
    sampled_df: pd.DataFrame,
    *,
    staff_names: tuple[str, ...],
    random_seed: int,
) -> pd.DataFrame:
    """
    Assign selected students to staff while keeping
    total assignment counts as equal as possible.
    """
    result = sampled_df.copy()

    result["ASSIGNED_TO"] = ""

    if not staff_names:
        return result

    assignment_counts = {
        name: 0
        for name in staff_names
    }

    selected = result[
        result["SELECTED_FOR_TESTING"]
    ]

    grouped = selected.groupby(
        "BUCKET_ID",
        sort=True,
    )

    for bucket_id, group in grouped:
        shuffled = group.sample(
            frac=1,
            random_state=_stable_seed(
                "staff",
                str(bucket_id),
                random_seed,
            ),
        )

        for index in shuffled.index:
            assignee = min(
                staff_names,
                key=lambda name: (
                    assignment_counts[name],
                    staff_names.index(name),
                ),
            )

            result.at[
                index,
                "ASSIGNED_TO",
            ] = assignee

            assignment_counts[assignee] += 1

    return result


def assign_testing_environments(
    assigned_df: pd.DataFrame,
    *,
    staff_names: tuple[str, ...],
    random_seed: int,
) -> pd.DataFrame:
    """
    Split each regular staff member's assignments
    approximately equally between TEST and PROD.

    Additional Accounts assignments are always TEST.
    """
    result = assigned_df.copy()

    result["TESTING_ENVIRONMENT"] = ""

    if not staff_names:
        return result

    selected = result[
        result["SELECTED_FOR_TESTING"]
    ]

    for staff_name in staff_names:
        staff_group = selected[
            selected["ASSIGNED_TO"]
            == staff_name
        ]

        if staff_group.empty:
            continue

        if staff_name == ADDITIONAL_ACCOUNTS:
            result.loc[
                staff_group.index,
                "TESTING_ENVIRONMENT",
            ] = "TEST"

            continue

        shuffled = staff_group.sample(
            frac=1,
            random_state=_stable_seed(
                "environment",
                staff_name,
                random_seed,
            ),
        )

        # When the count is odd, TEST receives the
        # additional account.
        test_count = (
            len(shuffled) + 1
        ) // 2

        test_indexes = shuffled.index[
            :test_count
        ]

        prod_indexes = shuffled.index[
            test_count:
        ]

        result.loc[
            test_indexes,
            "TESTING_ENVIRONMENT",
        ] = "TEST"

        result.loc[
            prod_indexes,
            "TESTING_ENVIRONMENT",
        ] = "PROD"

    return result