
import re


def normalize_sid(val) -> str | None:
    """
    Normalize student IDs into Banner-style S######## format.

    Accepts:
        12345678
        "12345678"
        "S12345678"
        "12345678.0"

    Returns:
        "S12345678" or None
    """
    if val is None:
        return None

    s = str(val).strip()

    if not s:
        return None

    if s.endswith(".0"):
        s = s[:-2].strip()

    if re.fullmatch(r"\d{8}", s):
        return f"S{s}"

    if re.fullmatch(r"S\d{8}", s):
        return s

    return None