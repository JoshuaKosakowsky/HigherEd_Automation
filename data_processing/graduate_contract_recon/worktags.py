"""Student funding worktags from the Workday Find Journal Lines export."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .sources import SourceData, STUDENT_PATTERN, accounting_date, text


WORKTAG_HEADERS = ["CWID", "Term Code", "Term Description", "Worktag Type", "Worktag Number"]
TERM_NAMES = {"SU": "Summer", "FA": "Fall", "SP": "Spring", "WI": "Winter"}
# Sort undated exports by the season in the memo, without assigning dates to rows.
TERM_SORT_MONTH = {"WI": 1, "SP": 3, "SU": 6, "FA": 9}
TERM_PATTERN = re.compile(r"\b(SU|FA|SP|WI)(\d{2})\b", re.IGNORECASE)
WORKTAG_PATTERN = re.compile(
    r"\b(Grant|Project|Operating\s+Account)\s*:?\s*([0-9]{6})(?![0-9])", re.IGNORECASE)


@dataclass(frozen=True)
class StudentWorktags:
    rows: list[list[str]]
    by_cwid: dict[str, dict[str, str]]
    warning_count: int


def prepare_worktags(source: SourceData, *additional_sources: SourceData) -> StudentWorktags:
    """Keep every distinct student/term/tag assignment, never just the first."""
    entries = {}
    assignments: dict[str, dict[str, set[str]]] = {}
    warnings = 0
    source_rows = ((upload, values) for upload in (source, *additional_sources) for _, values in upload.rows)
    for upload, values in source_rows:
        if not any(text(value) for value in values):
            continue
        memo = text(upload.value(values, "worktag_memo"))
        raw_tags = text(upload.value(values, "worktags"))
        cwids = set(STUDENT_PATTERN.findall(memo))
        cwid = next(iter(cwids)) if len(cwids) == 1 else ""
        terms = sorted({prefix.upper() + year for prefix, year in TERM_PATTERN.findall(memo)})
        term_code = "; ".join(terms)
        term_description = "; ".join(f"{TERM_NAMES[term[:2]]} 20{term[2:]}" for term in terms)
        tags = sorted({("Operating Account" if kind.lower().startswith("operating") else kind.title(), code)
                       for kind, code in WORKTAG_PATTERN.findall(raw_tags)})
        if not cwid or len(terms) != 1 or not tags:
            warnings += 1
        order = (10000, 0, 0)
        if additional_sources:
            day = accounting_date(upload, values)
            if day:
                order = (day.year, day.month, day.day)
            elif len(terms) == 1:
                order = (2000 + int(terms[0][2:]), TERM_SORT_MONTH[terms[0][:2]], 0)
        for kind, code in tags or [("", "")]:
            entry = (cwid, term_code, term_description, kind, code)
            if entry not in entries or order < entries[entry]:
                entries[entry] = order
            if cwid and code:
                assignments.setdefault(cwid, {}).setdefault(kind, set()).add(code)
    if not entries:
        raise ValueError("Grad Contract Worktag export contains no data rows.")
    ordered = sorted(entries, key=entries.__getitem__) if additional_sources else entries
    return StudentWorktags([list(entry) for entry in ordered], {
        cwid: {kind: "; ".join(sorted(codes)) for kind, codes in tags.items()}
        for cwid, tags in assignments.items()
    }, warnings)
