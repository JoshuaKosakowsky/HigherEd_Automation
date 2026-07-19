from __future__ import annotations

import pandas as pd


def clean_cwid(
    value: object,
) -> str:
    """
    Convert a CWID into a clean string while removing
    Excel's occasional trailing .0.
    """
    if pd.isna(value):
        return ""

    cwid = str(value).strip()

    if cwid.endswith(".0"):
        return cwid[:-2]

    return cwid