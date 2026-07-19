import json
from pathlib import Path

import pandas as pd


INPUT_FILE = Path("data/TSADETC.xlsx")
OUTPUT_FILE = Path("data/banner/detail_codes.json")


# Read Detail Code as text to preserve leading zeros.
df = pd.read_excel(
    INPUT_FILE,
    dtype={"Detail Code": str},
)

# Clean spaces and any literal apostrophes from Excel column headers.
df.columns = (
    df.columns
    .str.strip()
    .str.strip("'")
    .str.lower()
    .str.replace(r"[^a-z0-9]+", "_", regex=True)
    .str.strip("_")
)

# Remove completely blank rows.
df = df.dropna(how="all")

# Convert common Excel indicators into JSON booleans.
boolean_columns = [
    "direct_deposit",
    "refundable",
    "receipt",
    "active",
    "term_based",
    "aid_year_based",
    "gl_enterable",
    "title_iv",
    "institutional_charges",
    "exclude_invoice_print",
    "payment_history",
    "non_allowable_charge",
]

boolean_values = {
    "Y": True,
    "N": False,
    "Yes": True,
    "No": False,
    "TRUE": True,
    "FALSE": False,
    1: True,
    0: False,
}

for column in boolean_columns:
    if column in df.columns:
        df[column] = df[column].replace(boolean_values)

# Make sure each detail code occurs only once.
duplicates = df.loc[
    df["detail_code"].duplicated(keep=False),
    "detail_code",
].tolist()

if duplicates:
    raise ValueError(f"Duplicate detail codes found: {duplicates}")

# Use Detail Code as the key for each JSON record.
records = df.set_index("detail_code").to_dict(orient="index")

# Convert pandas missing values and dates into JSON-compatible values.
json_text = pd.Series({"data": records}).to_json(
    date_format="iso",
    indent=2,
)

records = json.loads(json_text)["data"]

OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

with OUTPUT_FILE.open("w", encoding="utf-8") as file:
    json.dump(records, file, indent=2, ensure_ascii=False)

print(f"Created {OUTPUT_FILE}")