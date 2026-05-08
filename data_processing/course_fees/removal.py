import pandas as pd


def section_key_matches(key, valid_keys) -> bool:
    subject, course, section = key
    is_hs = section in ["37X", "38X", "39X", "27X", "28X", "78X"]

    if (subject, course, section) in valid_keys:
        return True

    if is_hs and (subject, course, "ALL") in valid_keys:
        return False

    return (subject, course, "ALL") in valid_keys


def build_fees_to_remove(
    df_banner_cfl: pd.DataFrame,
    df_csf: pd.DataFrame,
) -> pd.DataFrame:
    valid_subjects = set(df_csf["SUBJECT"].unique())

    df_subject_not_in_csf = df_banner_cfl[
        ~df_banner_cfl["SUBJECT"].isin(valid_subjects)
    ].copy()
    df_subject_not_in_csf["REMOVAL_REASON"] = "Subject not in CSF"

    df_banner_subject_match = df_banner_cfl[
        df_banner_cfl["SUBJECT"].isin(df_csf["SUBJECT"])
    ].copy()

    valid_subj_course = df_csf[["SUBJECT", "COURSE NUMBER"]].drop_duplicates()
    valid_subj_course_set = set(tuple(x) for x in valid_subj_course.values)

    df_banner_subject_match["SUBJ_COURSE_PAIR"] = list(
        zip(
            df_banner_subject_match["SUBJECT"],
            df_banner_subject_match["COURSE NUMBER"],
        )
    )

    mask_invalid_course = ~df_banner_subject_match["SUBJ_COURSE_PAIR"].isin(
        valid_subj_course_set
    )

    df_course_not_in_csf = df_banner_subject_match[mask_invalid_course].copy()
    df_course_not_in_csf["REMOVAL_REASON"] = "Course Number not in CSF"

    df_csf = df_csf.copy()
    df_banner_cfl = df_banner_cfl.copy()

    df_csf["SECTION"] = (
        df_csf["SECTION"]
        .fillna("ALL")
        .replace("", "ALL")
        .astype(str)
        .str.strip()
        .str.upper()
    )

    df_banner_cfl["SECTION"] = (
        df_banner_cfl["SECTION"]
        .fillna("ALL")
        .replace("", "ALL")
        .astype(str)
        .str.strip()
        .str.upper()
    )

    df_banner_cfl["MODIFIED_SECTION"] = df_banner_cfl["SECTION"].apply(
        lambda s: (
            s
            if s == "ALL"
            else (
                s[:2] + "X"
                if s[:2] in ["37", "38", "39", "27", "28", "78"]
                else s[0] + "XX"
            )
        )
    )

    valid_pairs = df_csf[["SUBJECT", "COURSE NUMBER"]].drop_duplicates()

    df_banner_course_match = df_banner_cfl[
        df_banner_cfl["SUBJECT"].isin(df_csf["SUBJECT"])
        & df_banner_cfl[["SUBJECT", "COURSE NUMBER"]]
        .apply(tuple, axis=1)
        .isin(valid_pairs.apply(tuple, axis=1))
    ].copy()

    valid_sections = df_csf[["SUBJECT", "COURSE NUMBER", "SECTION"]].drop_duplicates()
    valid_section_keys = set(tuple(x) for x in valid_sections.values)

    df_banner_course_match["SECTION_KEY"] = list(
        zip(
            df_banner_course_match["SUBJECT"],
            df_banner_course_match["COURSE NUMBER"],
            df_banner_course_match["MODIFIED_SECTION"],
        )
    )

    df_banner_course_match["SECTION_MATCH"] = df_banner_course_match[
        "SECTION_KEY"
    ].apply(lambda key: section_key_matches(key, valid_section_keys))

    df_section_not_in_csf = df_banner_course_match[
        ~df_banner_course_match["SECTION_MATCH"]
    ].copy()
    df_section_not_in_csf["REMOVAL_REASON"] = (
        "Section not found for Subject & Course Number in CSF"
    )

    fees_to_remove = pd.concat(
        [
            df_subject_not_in_csf,
            df_course_not_in_csf,
            df_section_not_in_csf,
        ],
        ignore_index=True,
    )

    fees_to_remove["AMOUNT"] = pd.to_numeric(fees_to_remove["AMOUNT"], errors="coerce")
    fees_to_remove = fees_to_remove[
        fees_to_remove["AMOUNT"].notna() & (fees_to_remove["AMOUNT"] != 0)
    ]

    fees_to_remove = fees_to_remove.drop(
        columns=["SUBJ_COURSE_PAIR", "SECTION_KEY", "SECTION_MATCH"],
        errors="ignore",
    )

    fees_to_remove = fees_to_remove.sort_values(
        by=["SUBJECT", "COURSE NUMBER", "SECTION", "CRN"],
        ascending=[True, True, True, True],
        key=lambda col: (
            col.astype(str).str.upper()
            if col.name in ["SUBJECT", "SECTION"]
            else col
        ),
    )

    return fees_to_remove