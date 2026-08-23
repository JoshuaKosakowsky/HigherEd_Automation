from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import pandas as pd

from data_processing.population_testing.assignment import (
    ADDITIONAL_ACCOUNTS,
    assign_testing_environments,
    assign_testing_staff,
)
from data_processing.population_testing.buckets import assign_population_buckets
from data_processing.population_testing.config import DEFAULT_SAMPLE_FRACTION
from data_processing.population_testing.sampling import select_testing_sample
from workflows.population_testing.run_population_testing import parse_args


class PopulationCommandLineTests(unittest.TestCase):
    def test_sample_help_and_default_match_configuration(self) -> None:
        with patch("sys.argv", ["run_population_testing.py"]):
            arguments = parse_args()

        expected_percent = DEFAULT_SAMPLE_FRACTION * 100
        self.assertEqual(arguments.sample_percent, expected_percent)

        help_output = io.StringIO()
        with patch("sys.argv", ["run_population_testing.py", "--help"]):
            with redirect_stdout(help_output):
                with self.assertRaises(SystemExit) as exit_context:
                    parse_args()

        self.assertEqual(exit_context.exception.code, 0)
        normalized_help = " ".join(
            help_output.getvalue().split()
        )
        self.assertIn(
            f"The default is {expected_percent:g}.",
            normalized_help,
        )


class PopulationBucketTests(unittest.TestCase):
    def test_assigns_credit_residency_and_online_buckets(self) -> None:
        credits = [0, 2.5, 3, 5.5, 6, 19, 19.5]
        rows = [
            {
                "Primary Program": "BS-CS",
                "Student Residency": "R",
                "Primary Student Level Desc": "Undergraduate",
                "Registered Credits": credit,
                "__SOURCE_ROW__": row_number,
            }
            for row_number, credit in enumerate(credits, start=2)
        ]
        rows.extend(
            [
                {
                    "Primary Program": "BS-EE",
                    "Student Residency": "L",
                    "Primary Student Level Desc": "Undergraduate",
                    "Registered Credits": 6,
                    "__SOURCE_ROW__": 20,
                },
                {
                    "Primary Program": "X-ONLINE",
                    "Student Residency": "Z",
                    "Primary Student Level Desc": "Online Program",
                    "Registered Credits": None,
                    "__SOURCE_ROW__": 21,
                },
            ]
        )

        result = assign_population_buckets(pd.DataFrame(rows))

        self.assertEqual(
            result.iloc[:7]["CREDIT_BUCKET"].tolist(),
            ["0-2.5", "0-2.5", "3-5.5", "3-5.5", "6-19", "6-19", ">19"],
        )
        self.assertEqual(result.loc[0, "RESIDENCY_BUCKET"], "RL")
        self.assertEqual(result.loc[7, "RESIDENCY_BUCKET"], "RL")
        self.assertEqual(result.loc[7, "Student Residency"], "L")
        self.assertEqual(result.loc[8, "BUCKET_ID"], "B000")
        self.assertEqual(result.loc[8, "RESIDENCY_BUCKET"], "ALL")
        self.assertEqual(result.loc[8, "CREDIT_BUCKET"], "ALL")
        self.assertTrue(result.loc[8, "IS_GRAD_ONLINE"])

    def test_rejects_unsupported_standard_residency(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "Primary Program": "BS-CS",
                    "Student Residency": "Z",
                    "Primary Student Level Desc": "Undergraduate",
                    "Registered Credits": 12,
                    "__SOURCE_ROW__": 2,
                }
            ]
        )

        with self.assertRaisesRegex(ValueError, "Unsupported Student Residency"):
            assign_population_buckets(frame)


class PopulationSelectionTests(unittest.TestCase):
    def test_sampling_is_reproducible_and_selects_all_online_students(self) -> None:
        frame = pd.DataFrame(
            {
                "BUCKET_ID": ["B001"] * 5 + ["B002"] * 5 + ["B000"] * 2,
                "IS_GRAD_ONLINE": [False] * 10 + [True] * 2,
            }
        )

        first = select_testing_sample(frame, sample_fraction=0.25, random_seed=20260822)
        second = select_testing_sample(frame, sample_fraction=0.25, random_seed=20260822)

        pd.testing.assert_series_equal(
            first["SELECTED_FOR_TESTING"],
            second["SELECTED_FOR_TESTING"],
        )
        selected_by_bucket = (
            first.groupby("BUCKET_ID")["SELECTED_FOR_TESTING"].sum().to_dict()
        )
        self.assertEqual(selected_by_bucket, {"B000": 2, "B001": 2, "B002": 2})

    def test_staff_assignment_is_balanced_and_reproducible(self) -> None:
        frame = pd.DataFrame(
            {
                "BUCKET_ID": ["B001"] * 4 + ["B002"] * 5 + ["B003"],
                "SELECTED_FOR_TESTING": [True] * 9 + [False],
            }
        )
        staff = ("Analyst One", "Analyst Two", "Analyst Three")

        first = assign_testing_staff(frame, staff_names=staff, random_seed=12345)
        second = assign_testing_staff(frame, staff_names=staff, random_seed=12345)

        pd.testing.assert_series_equal(first["ASSIGNED_TO"], second["ASSIGNED_TO"])
        counts = first.loc[first["SELECTED_FOR_TESTING"], "ASSIGNED_TO"].value_counts()
        self.assertLessEqual(int(counts.max() - counts.min()), 1)
        self.assertEqual(first.loc[9, "ASSIGNED_TO"], "")

    def test_environment_assignment_is_balanced_and_additional_accounts_is_test_only(self) -> None:
        frame = pd.DataFrame(
            {
                "SELECTED_FOR_TESTING": [True] * 8 + [False],
                "ASSIGNED_TO": [
                    "Analyst One",
                    "Analyst One",
                    "Analyst One",
                    "Analyst One",
                    "Analyst One",
                    ADDITIONAL_ACCOUNTS,
                    ADDITIONAL_ACCOUNTS,
                    ADDITIONAL_ACCOUNTS,
                    "",
                ],
            }
        )

        result = assign_testing_environments(
            frame,
            staff_names=("Analyst One", ADDITIONAL_ACCOUNTS),
            random_seed=12345,
        )

        analyst_counts = result.loc[
            result["ASSIGNED_TO"] == "Analyst One", "TESTING_ENVIRONMENT"
        ].value_counts()
        self.assertEqual(analyst_counts.to_dict(), {"TEST": 3, "PROD": 2})
        additional_environments = result.loc[
            result["ASSIGNED_TO"] == ADDITIONAL_ACCOUNTS,
            "TESTING_ENVIRONMENT",
        ]
        self.assertEqual(set(additional_environments), {"TEST"})
        self.assertEqual(result.loc[8, "TESTING_ENVIRONMENT"], "")


if __name__ == "__main__":
    unittest.main()
