import re

import pandas as pd


def clean_column_names(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    df.columns = (
        df.columns
        .str.strip('"')
        .str.replace(r'^[^\w]*|[^\w]*$', '', regex=True)
        .str.replace(r'[^\w]+', '_', regex=True)
    )

    return df


def strip_string_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    df = df.copy()

    for col in columns:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()

    return df