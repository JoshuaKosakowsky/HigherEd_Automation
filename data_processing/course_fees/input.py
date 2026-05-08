from pathlib import Path

import pandas as pd


def read_banner_course_fee_listing(input_file: Path) -> pd.DataFrame:
    if not input_file.exists():
        raise FileNotFoundError(f"Missing Banner Course Fee Listing input: {input_file}")

    return pd.read_csv(input_file, delimiter=",", quotechar='"')


def read_course_specific_fees(input_file: Path) -> pd.DataFrame:
    if not input_file.exists():
        raise FileNotFoundError(f"Missing Course Specific Fees input: {input_file}")

    return pd.read_excel(input_file)