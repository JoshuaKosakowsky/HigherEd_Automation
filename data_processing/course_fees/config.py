from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


FEE_MAPPING = {
    "10": {"digital_content_fee": "A394", "not_dcf": "A385"},  # Summer
    "20": {"digital_content_fee": "A392", "not_dcf": "A383"},  # Fall
    "30": {"digital_content_fee": "A393", "not_dcf": "A384"},  # Spring
}

BANNER_RENAME_COLUMNS = {
    "SSBSECT_TERM_CODE": "SEMESTER",
    "SSBSECT_CRN": "CRN",
    "SSBSECT_SUBJ_CODE": "SUBJECT",
    "SSBSECT_CRSE_NUMB": "COURSE NUMBER",
    "SSBSECT_SEQ_NUMB": "SECTION",
    "SSBSECT_CAMP_CODE": "CAMPUS",
    "SSRATTR_ATTR_CODE": "ATTR",
    "SSRFEES_DETL_CODE": "DET CODE",
    "SSRFEES_AMOUNT": "AMOUNT",
    "SSRFEES_FTYP_CODE": "FEE TYPE (OLD)",
}

BANNER_DROP_COLUMNS = [
    "SSBSECT_VPDI_CODE",
    "SSBSECT_CREDIT_HRS",
    "SSBSECT_BILL_HRS",
    "SSBSECT_ENRL",
    "SSBSECT_WAIT_COUNT",
    "SSBSECT_LAB_HR",
    "SSBSECT_LEC_HR",
    "SSBSECT_OTH_HR",
    "SSBSECT_PRNT_IND",
    "SSBSECT_PTRM_CODE",
    "SSBSECT_ACTIVITY_DATE",
    "SSBSECT_PTRM_START_DATE",
    "SSBSECT_PTRM_END_DATE",
    "SSBSECT_CENSUS_ENRL_DATE",
    "SSRATTR_ACTIVITY_DATE",
    "SSRFEES_FEE_IND",
    "SSRFEES_LEVL_CODE",
    "SSBOVRR_COLL_CODE",
    "SSBOVRR_DEPT_CODE",
    "SSBOVRR_DIVS_CODE",
    "SSBOVRR_TOPS_CODE",
    "SSRMEET_BLDG_CODE",
    "SSRMEET_START_DATE",
    "SSRMEET_END_DATE",
    "SSRMEET_BEGIN_TIME",
    "SSRMEET_END_TIME",
    "SSRMEET_HRS_WEEK",
    "SSRMEET_ROOM_CODE",
    "SSRMEET_CATAGORY",
    "SSRMEET_SUN_DAY",
    "SSRMEET_MON_DAY",
    "SSRMEET_TUE_DAY",
    "SSRMEET_WED_DAY",
    "SSRMEET_THU_DAY",
    "SSRMEET_FRI_DAY",
    "SSRMEET_SAT_DAY",
]

CSF_STRING_COLUMNS = [
    "CAMPUS",
    "SUBJECT",
    "COURSE NUMBER",
    "SECTION",
    "FREQUENCY",
    "EXPLANATION",
]

CAMPUS_REPLACEMENTS = {
    "BCC": "FBC",
    "LC": "FLC",
    "WC": "FWC",
    "OL": "FCY",
}

AMOUNT_TOLERANCE = 0.01


@dataclass(frozen=True)
class CourseFeeRunConfig:
    term_code: str
    fiscal_year: str
    semester: str
    digital_content_fee: str
    not_dcf: str
    output_dir: Path
    third_party_dir: Path | None = None
    write_debug_outputs: bool = False


def build_course_fee_config(
    *,
    term_code: str,
    output_dir: Path,
    third_party_dir: Path | None = None,
    write_debug_outputs: bool = False,
) -> CourseFeeRunConfig:
    semester = term_code[-2:]
    fiscal_year = term_code[2:4]

    if semester not in FEE_MAPPING:
        raise ValueError(f"Invalid semester code extracted from term_code: {term_code}")

    return CourseFeeRunConfig(
        term_code=term_code,
        fiscal_year=fiscal_year,
        semester=semester,
        digital_content_fee=FEE_MAPPING[semester]["digital_content_fee"],
        not_dcf=FEE_MAPPING[semester]["not_dcf"],
        output_dir=output_dir,
        third_party_dir=third_party_dir,
        write_debug_outputs=write_debug_outputs,
    )