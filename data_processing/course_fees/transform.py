import numpy as np
import pandas as pd

from data_processing.course_fees.config import CourseFeeRunConfig


def fee_type(freq) -> str:
    if freq in ["Per Course", "Per Term"]:
        return "FLAT"

    return "CRED"


def detail_code(det, *, config: CourseFeeRunConfig) -> str:
    if det == "Digital Content Fee":
        return config.digital_content_fee

    return config.not_dcf


def add_expected_fee_fields(
    df: pd.DataFrame,
    *,
    config: CourseFeeRunConfig,
) -> pd.DataFrame:
    df = df.copy()

    df["FEE TYPE"] = df["FREQUENCY"].apply(fee_type)
    df["DETAIL CODE"] = df["EXPLANATION"].apply(
        lambda value: detail_code(value, config=config)
    )

    return df


def finalize_course_fee_output(
    df: pd.DataFrame,
    *,
    config: CourseFeeRunConfig,
) -> pd.DataFrame:
    df = df.copy()

    df.loc[
        df["EXPLANATION"].str.contains("Malpractice Insurance", na=False),
        "UNCHANGED",
    ] = "MP"

    df = df.sort_values(
        by=["SUBJECT", "COURSE NUMBER_CFL", "CRN"],
        ascending=[True, True, True],
    )

    expected_amount_col = f"FY{config.fiscal_year} FEE AMOUNT"

    column_order = [
        "SEMESTER",
        "CRN",
        "SUBJECT",
        "COURSE NUMBER_CFL",
        "COURSE NUMBER_CSF",
        "SECTION_CFL",
        "MODIFIED_SECTION",
        "SECTION_CSF",
        "CAMPUS_CFL",
        "CAMPUS_CSF",
        "ATTR",
        "DET CODE",
        "DETAIL CODE",
        "AMOUNT",
        expected_amount_col,
        "FEE TYPE (OLD)",
        "FEE TYPE",
        "COURSE NAME",
        "FREQUENCY",
        "EXPLANATION",
        "UNCHANGED",
    ]

    df = df[column_order]

    rename_final = {
        "DET CODE": "CURRENT DETAIL CODE",
        "DETAIL CODE": "EXPECTED DETAIL CODE",
        "AMOUNT": "CURRENT AMOUNT",
        expected_amount_col: f"EXPECTED FY{config.fiscal_year} FEE AMOUNT",
        "FEE TYPE (OLD)": "CURRENT FEE TYPE",
        "FEE TYPE": "EXPECTED FEE TYPE",
    }

    return df.rename(columns=rename_final)