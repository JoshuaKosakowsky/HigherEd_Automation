from pathlib import Path

import numpy as np
import pandas as pd

from data_processing.course_fees.config import (
    BANNER_DROP_COLUMNS,
    BANNER_RENAME_COLUMNS,
    CAMPUS_REPLACEMENTS,
    CSF_STRING_COLUMNS,
    CourseFeeRunConfig,
)
from data_processing.shared.files import ensure_dir
from data_processing.shared.text import clean_column_names, strip_string_columns


def conc_only(value) -> str:
    return "CONC" if value == "CONC" else ""


def modify_for_matching(value) -> str:
    if value == "ALL":
        return "ALL"

    section_str = str(value)

    if len(section_str) > 1 and section_str[:2] in ["37", "38", "39"]:
        return section_str[:2] + "X"

    return section_str[0] + "XX"


def text_num(course_number):
    try:
        return int(course_number)
    except (ValueError, TypeError):
        return course_number


def expand_rows(row):
    section = "ALL" if pd.isna(row["SECTION"]) else str(row["SECTION"]).strip()

    if section:
        sections = section.replace(" ", ",").split(",")
    else:
        sections = ["ALL"]

    new_rows = []

    for sec in sections:
        if sec:
            new_row = row.copy()
            new_row["SECTION"] = sec
            new_rows.append(new_row)

    return new_rows


def expand_campuses(row):
    campus = str(row["CAMPUS"]).strip() if pd.notna(row["CAMPUS"]) else "ALL"
    campuses = [c.strip() for c in campus.split("/")]

    new_rows = []

    for camp in campuses:
        if camp:
            new_row = row.copy()
            new_row["CAMPUS"] = camp
            new_rows.append(new_row)

    return new_rows


def clean_banner_course_fee_listing(
    df: pd.DataFrame,
    *,
    config: CourseFeeRunConfig,
) -> pd.DataFrame:
    df = clean_column_names(df)

    df = df.rename(columns=BANNER_RENAME_COLUMNS, errors="ignore")
    df = df.drop(columns=BANNER_DROP_COLUMNS, errors="ignore")

    conc_df = df[df["ATTR"] == "CONC"]

    unique_amount_df = (
        df.dropna(subset=["AMOUNT"])
        .drop_duplicates(subset=["CRN", "AMOUNT"])
        .copy()
    )
    unique_amount_df["ATTR"] = unique_amount_df["ATTR"].apply(conc_only)

    na_amount_df = (
        df[df["AMOUNT"].isna()]
        .drop_duplicates(subset=["CRN", "ATTR"])
        .copy()
    )
    na_amount_df["ATTR"] = na_amount_df["ATTR"].apply(conc_only)

    df = pd.concat([conc_df, unique_amount_df, na_amount_df], ignore_index=True)

    df["ATTR2"] = df["ATTR"].apply(lambda x: "MISSING" if pd.isna(x) or x == "" else x)
    df["AMOUNT2"] = df["AMOUNT"].fillna("MISSING")
    df["ATTR"] = df["ATTR"].apply(conc_only)

    df = df.sort_values(by=["CRN", "ATTR"], ascending=[True, False])

    if config.write_debug_outputs:
        ensure_dir(config.output_dir)
        df.to_excel(config.output_dir / "b4Drops.xlsx", index=False)

    df = df.drop_duplicates(subset=["CRN", "AMOUNT2"], keep="first")
    df = df.drop(columns=["ATTR2", "AMOUNT2"], errors="ignore")

    if config.third_party_dir:
        ensure_dir(config.third_party_dir)
        df.to_excel(config.third_party_dir / "CFL.xlsx", index=False)

    df["SECTION"] = df["SECTION"].astype(str).str.zfill(3)

    df = df[~df["CAMPUS"].str.contains("FCX|FCW|FCZ|FZZ", na=False)]

    df = df[
        ~(
            df["SECTION"].str.contains(
                r"27[A-Z]|28[A-Z]|37[A-Z]|38[A-Z]|39[A-Z]|78[A-Z]",
                na=False,
            )
            & ~(
                df["CAMPUS"].isin(["FWO", "FWC", "FLO", "FLC", "FBO", "FBC"])
                & (df["ATTR"] == "CONC")
            )
        )
    ]

    df["MODIFIED_SECTION"] = df["SECTION"].apply(modify_for_matching)
    df["ATTR"] = df["ATTR"].apply(conc_only)

    df = df.sort_values(by=["SUBJECT", "COURSE NUMBER"], ascending=[True, True])

    return df


def clean_course_specific_fees(
    df: pd.DataFrame,
    *,
    config: CourseFeeRunConfig,
) -> pd.DataFrame:
    df = df.copy()

    df.columns = df.columns.str.upper().str.strip()

    df = strip_string_columns(df, CSF_STRING_COLUMNS)

    df["CAMPUS"] = df["CAMPUS"].replace(["All", "ALL", "", "nan", "NAN", np.nan], "ALL")
    df["COURSE NUMBER"] = df["COURSE NUMBER"].replace(
        ["All", "ALL", "", " ", "nan", "NAN", np.nan],
        "ALL",
    )
    df["SECTION"] = df["SECTION"].replace(["All", "ALL", "", "nan", "NAN", np.nan], "ALL")

    df["COURSE NUMBER"] = df["COURSE NUMBER"].apply(text_num)
    df["SECTION"] = df["SECTION"].str.replace(r"-$", "", regex=True)
    df["EXPLANATION"] = df["EXPLANATION"].str.slice(0, 30)

    expanded_rows = df.apply(expand_rows, axis=1)
    df = pd.DataFrame([item for sublist in expanded_rows for item in sublist])

    expanded_campuses = df.apply(expand_campuses, axis=1)
    df = pd.DataFrame([item for sublist in expanded_campuses for item in sublist])

    df["CAMPUS"] = df["CAMPUS"].replace(CAMPUS_REPLACEMENTS)

    df = df.sort_values(by=["SUBJECT", "COURSE NUMBER"], ascending=[True, True])

    return df