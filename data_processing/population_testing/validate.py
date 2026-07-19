from __future__ import annotations

import math

import pandas as pd

from .assignment import ADDITIONAL_ACCOUNTS


def validate_population_results(
    df: pd.DataFrame,
    *,
    sample_fraction: float,
    staff_names: tuple[str, ...],
) -> pd.DataFrame:
    """
    Reconcile the buckets, sample, staff assignments,
    and TEST/PROD splits.
    """
    checks: list[dict[str, object]] = []

    def add_check(
        name: str,
        passed: bool,
        detail: str,
    ) -> None:
        checks.append(
            {
                "Check": name,
                "Status": (
                    "PASS"
                    if passed
                    else "FAIL"
                ),
                "Detail": detail,
            }
        )

        if not passed:
            raise ValueError(
                "Validation failed: "
                f"{name}. {detail}"
            )

    source_rows_are_valid = (
        df["BUCKET_ID"].ne("").all()
        and df["__SOURCE_ROW__"].is_unique
    )

    add_check(
        "Every source row has one bucket",
        source_rows_are_valid,
        (
            f"Source rows: {len(df):,}; "
            "unique source rows: "
            f"{df['__SOURCE_ROW__'].nunique():,}"
        ),
    )

    online = df[
        df["IS_GRAD_ONLINE"]
    ]

    add_check(
        "All Graduate Online rows selected",
        online["SELECTED_FOR_TESTING"].all(),
        (
            "Selected "
            f"{online['SELECTED_FOR_TESTING'].sum():,} "
            f"of {len(online):,}"
        ),
    )

    standard = df[
        ~df["IS_GRAD_ONLINE"]
    ]

    expected_standard = sum(
        math.ceil(
            len(group) * sample_fraction
        )
        for _, group in standard.groupby(
            "BUCKET_ID"
        )
    )

    actual_standard = int(
        standard[
            "SELECTED_FOR_TESTING"
        ].sum()
    )

    add_check(
        "Standard sample count reconciles",
        expected_standard == actual_standard,
        (
            f"Expected {expected_standard:,}; "
            f"selected {actual_standard:,}"
        ),
    )

    selected = df[
        df["SELECTED_FOR_TESTING"]
    ]

    assigned = selected[
        "ASSIGNED_TO"
    ].ne("")

    add_check(
        "Every selected row assigned",
        assigned.all(),
        (
            f"Assigned {assigned.sum():,} "
            f"of {len(selected):,}"
        ),
    )

    staff_counts = (
        selected["ASSIGNED_TO"]
        .value_counts()
        .reindex(
            staff_names,
            fill_value=0,
        )
    )

    add_check(
        (
            "Staff assignments differ "
            "by no more than one"
        ),
        (
            staff_counts.max()
            - staff_counts.min()
            <= 1
        ),
        "; ".join(
            f"{name}: {count}"
            for name, count
            in staff_counts.items()
        ),
    )

    valid_environment_mask = (
        selected["TESTING_ENVIRONMENT"]
        .isin(
            [
                "TEST",
                "PROD",
            ]
        )
    )

    add_check(
        "Every selected row has an environment",
        valid_environment_mask.all(),
        (
            f"Environment assigned to "
            f"{valid_environment_mask.sum():,} "
            f"of {len(selected):,}"
        ),
    )

    additional_accounts = selected[
        selected["ASSIGNED_TO"]
        == ADDITIONAL_ACCOUNTS
    ]

    additional_accounts_are_test = (
        additional_accounts[
            "TESTING_ENVIRONMENT"
        ]
        .eq("TEST")
        .all()
    )

    add_check(
        "Additional Accounts are all TEST",
        additional_accounts_are_test,
        (
            f"TEST assignments: "
            f"{additional_accounts['TESTING_ENVIRONMENT'].eq('TEST').sum():,}; "
            f"total: {len(additional_accounts):,}"
        ),
    )

    regular_staff = [
        name
        for name in staff_names
        if name != ADDITIONAL_ACCOUNTS
    ]

    environment_details: list[str] = []
    environments_are_balanced = True

    for staff_name in regular_staff:
        staff_sample = selected[
            selected["ASSIGNED_TO"]
            == staff_name
        ]

        test_count = int(
            staff_sample[
                "TESTING_ENVIRONMENT"
            ]
            .eq("TEST")
            .sum()
        )

        prod_count = int(
            staff_sample[
                "TESTING_ENVIRONMENT"
            ]
            .eq("PROD")
            .sum()
        )

        if abs(
            test_count - prod_count
        ) > 1:
            environments_are_balanced = False

        environment_details.append(
            f"{staff_name}: "
            f"TEST {test_count}, "
            f"PROD {prod_count}"
        )

    add_check(
        (
            "TEST and PROD differ by no more "
            "than one per regular staff member"
        ),
        environments_are_balanced,
        "; ".join(environment_details),
    )

    return pd.DataFrame(checks)