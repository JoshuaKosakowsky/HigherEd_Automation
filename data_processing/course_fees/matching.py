import numpy as np
import pandas as pd

from data_processing.course_fees.config import AMOUNT_TOLERANCE, CourseFeeRunConfig


def custom_join(df_banner_cfl: pd.DataFrame, df_csf: pd.DataFrame) -> pd.DataFrame:
    parts = []

    for subj, cfl_sub in df_banner_cfl.groupby("SUBJECT", dropna=False):
        csf_sub = df_csf[df_csf["SUBJECT"] == subj]

        if csf_sub.empty:
            continue

        left = cfl_sub.rename(
            columns={
                "COURSE NUMBER": "COURSE NUMBER_CFL",
                "SECTION": "SECTION_CFL",
                "CAMPUS": "CAMPUS_CFL",
            }
        ).copy()

        right = (
            csf_sub.rename(
                columns={
                    "COURSE NUMBER": "COURSE NUMBER_CSF",
                    "SECTION": "SECTION_CSF",
                    "CAMPUS": "CAMPUS_CSF",
                }
            )
            .drop(columns=["SUBJECT"])
            .copy()
        )

        for col in ["COURSE NUMBER_CFL", "MODIFIED_SECTION", "SECTION_CFL", "CAMPUS_CFL"]:
            if col in left.columns:
                left[col] = left[col].astype(str).str.strip().str.upper()

        for col in ["COURSE NUMBER_CSF", "SECTION_CSF", "CAMPUS_CSF"]:
            if col in right.columns:
                right[col] = right[col].astype(str).str.strip().str.upper()

        cross = left.merge(right, how="cross")

        course_mask = (
            (cross["COURSE NUMBER_CFL"] == cross["COURSE NUMBER_CSF"])
            | (cross["COURSE NUMBER_CFL"] == "ALL")
            | (cross["COURSE NUMBER_CSF"] == "ALL")
        )

        section_mask = (
            (cross["MODIFIED_SECTION"] == cross["SECTION_CSF"])
            | (cross["MODIFIED_SECTION"] == "ALL")
            | (cross["SECTION_CSF"] == "ALL")
        )

        keep = cross[course_mask & section_mask].copy()

        if keep.empty:
            continue

        keep["SUBJECT"] = subj
        parts.append(keep)

    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def filter_out_high_med_attr(df: pd.DataFrame) -> pd.DataFrame:
    return df[
        ~(df["EXPLANATION"].str.contains("HIGH|MED|LOW", case=False, na=False))
    ].copy()


def keep_non_hs_all_match(row) -> bool:
    if row["MODIFIED_SECTION"] in ["37X", "38X", "39X"] and row["SECTION_CSF"] == "ALL":
        return False

    return True


def campus_filter(row) -> bool:
    if row["CAMPUS_CFL"] == "FBO":
        return row["CAMPUS_CSF"] in ["FBO", "FBC", "ALL"]

    if row["CAMPUS_CFL"] == "FWO":
        return row["CAMPUS_CSF"] in ["FWO", "FWC", "ALL"]

    if row["CAMPUS_CFL"] == "FLO":
        return row["CAMPUS_CSF"] in ["FLO", "FLC", "ALL"]

    if row["CAMPUS_CFL"] == "FCY":
        return row["CAMPUS_CSF"] in ["FON", "FCY", "ALL"]

    return (
        (row["CAMPUS_CFL"] == row["CAMPUS_CSF"])
        or (row["CAMPUS_CFL"] == "ALL")
        or (row["CAMPUS_CSF"] == "ALL")
    )


def hs_filter(df: pd.DataFrame) -> pd.DataFrame:
    return df[
        ~(
            (df["ATTR"] == "CONC")
            & (df["MODIFIED_SECTION"].str.match(r"^(2XX|3XX|7XX)$", na=False))
        )
    ].copy()


def apply_course_fee_match_filters(df: pd.DataFrame) -> pd.DataFrame:
    df = filter_out_high_med_attr(df)
    df = df[df.apply(campus_filter, axis=1)]
    df = df[df.apply(keep_non_hs_all_match, axis=1)]
    df = hs_filter(df)

    return df.copy()


def _score_row(row, *, fiscal_year: str) -> float:
    score = 0

    modified_section = str(row.get("MODIFIED_SECTION", "")).upper()
    csf_section = str(row.get("SECTION_CSF", "")).upper()

    if (
        modified_section
        and csf_section
        and modified_section != "ALL"
        and csf_section != "ALL"
        and modified_section == csf_section
    ):
        score += 80
    elif csf_section == "ALL" or modified_section == "ALL":
        score += 20

    cfl_campus = str(row.get("CAMPUS_CFL", "")).upper()
    csf_campus = str(row.get("CAMPUS_CSF", "")).upper()

    if (
        cfl_campus
        and csf_campus
        and cfl_campus != "ALL"
        and csf_campus != "ALL"
        and cfl_campus == csf_campus
    ):
        score += 50
    elif cfl_campus == "ALL" or csf_campus == "ALL":
        score += 15

    if str(row.get("DET CODE", "")).strip().upper() == str(row.get("DETAIL CODE", "")).strip().upper():
        score += 100

    if str(row.get("FEE TYPE (OLD)", "")).strip().upper() == str(row.get("FEE TYPE", "")).strip().upper():
        score += 40

    try:
        actual_amount = float(row.get("AMOUNT", np.nan))
    except Exception:
        actual_amount = np.nan

    expected_amount_col = f"FY{fiscal_year} FEE AMOUNT"

    try:
        expected_amount = float(row.get(expected_amount_col, np.nan))
    except Exception:
        expected_amount = np.nan

    if pd.notna(actual_amount) and pd.notna(expected_amount):
        score += max(0, 60 - min(abs(actual_amount - expected_amount), 60))

    return score


def compute_unchanged_one_to_one(
    df: pd.DataFrame,
    *,
    config: CourseFeeRunConfig,
) -> pd.DataFrame:
    df = df.copy()

    df["_score"] = df.apply(
        lambda row: _score_row(row, fiscal_year=config.fiscal_year),
        axis=1,
    )

    expected_amount_col = f"FY{config.fiscal_year} FEE AMOUNT"

    cfl_id_cols = [
        "COURSE NUMBER_CFL",
        "SECTION_CFL",
        "CAMPUS_CFL",
        "DET CODE",
        "FEE TYPE (OLD)",
        "AMOUNT",
        "MODIFIED_SECTION",
    ]

    csf_id_cols = [
        "COURSE NUMBER_CSF",
        "SECTION_CSF",
        "CAMPUS_CSF",
        "DETAIL CODE",
        "FEE TYPE",
        expected_amount_col,
    ]

    for col in cfl_id_cols:
        if col not in df.columns:
            df[col] = ""

    for col in csf_id_cols:
        if col not in df.columns:
            df[col] = ""

    df["__CFL_ID__"] = df[cfl_id_cols].astype(str).agg("|".join, axis=1)
    df["__CSF_ID__"] = df[csf_id_cols].astype(str).agg("|".join, axis=1)

    df["UNCHANGED"] = False
    df["__CHOSEN__"] = False

    for _, group in df.groupby("CRN", group_keys=False):
        mp_mask = group["EXPLANATION"].str.contains("Malpractice Insurance", na=False)

        if mp_mask.any():
            mp_idx = group.index[mp_mask]
            df.loc[mp_idx, "UNCHANGED"] = "MP"
            df.loc[mp_idx, "__CHOSEN__"] = True
            group = group.loc[~mp_mask]

        group = group.sort_values("_score", ascending=False)

        used_cfl = set()
        used_csf = set()
        chosen_idx = []

        for idx, row in group.iterrows():
            cfl_id = row["__CFL_ID__"]
            csf_id = row["__CSF_ID__"]

            if cfl_id in used_cfl or csf_id in used_csf:
                continue

            used_cfl.add(cfl_id)
            used_csf.add(csf_id)
            chosen_idx.append(idx)

        df.loc[chosen_idx, "__CHOSEN__"] = True

        for idx in chosen_idx:
            row = df.loc[idx]

            same_code = (
                str(row["DET CODE"]).strip().upper()
                == str(row["DETAIL CODE"]).strip().upper()
            )
            same_type = (
                str(row["FEE TYPE (OLD)"]).strip().upper()
                == str(row["FEE TYPE"]).strip().upper()
            )

            try:
                actual_amount = float(row["AMOUNT"])
                expected_amount = float(row[expected_amount_col])
            except Exception:
                actual_amount = np.nan
                expected_amount = np.nan

            if (
                same_code
                and same_type
                and pd.notna(actual_amount)
                and pd.notna(expected_amount)
                and abs(actual_amount - expected_amount) <= AMOUNT_TOLERANCE
            ):
                df.at[idx, "UNCHANGED"] = True

    return df.drop(columns=["_score", "__CFL_ID__", "__CSF_ID__"])


def build_matched_course_fees(
    df_banner_cfl: pd.DataFrame,
    df_csf: pd.DataFrame,
    *,
    config: CourseFeeRunConfig,
) -> pd.DataFrame:
    df = custom_join(df_banner_cfl, df_csf)
    df = apply_course_fee_match_filters(df)
    df = compute_unchanged_one_to_one(df, config=config)
    df = df[df["__CHOSEN__"]].drop(columns="__CHOSEN__")

    return df