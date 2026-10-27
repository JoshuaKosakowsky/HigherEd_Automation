"""Student funding worktags from the Workday Find Journal Lines export."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .sources import SourceData, text


WORKTAG_HEADERS = ["CWID", "Term Code", "Term Description", "Worktag Type", "Worktag Number"]
TERM_NAMES = {"SU": "Summer", "FA": "Fall", "SP": "Spring", "WI": "Winter"}
STUDENT_PATTERN = re.compile(r"(?<!\d)10\d{6}(?!\d)")
TERM_PATTERN = re.compile(r"\b(SU|FA|SP|WI)(\d{2})\b", re.IGNORECASE)
WORKTAG_PATTERN = re.compile(
    r"\b(Grant|Project|Operating\s+Account)\s*:?\s*([0-9]{6})(?![0-9])", re.IGNORECASE)


@dataclass(frozen=True)
class StudentWorktags:
    rows: list[list[str]]
    by_cwid: dict[str, dict[str, str]]
    warning_count: int


def prepare_worktags(source: SourceData) -> StudentWorktags:
    """Keep every distinct student/term/tag assignment, never just the first."""
    rows = []
    assignments: dict[str, dict[str, set[str]]] = {}
    seen = set()
    warnings = 0
    for _, values in source.rows:
        if not any(text(value) for value in values):
            continue
        memo = text(source.value(values, "worktag_memo"))
        raw_tags = text(source.value(values, "worktags"))
        cwids = set(STUDENT_PATTERN.findall(memo))
        cwid = next(iter(cwids)) if len(cwids) == 1 else ""
        terms = sorted({prefix.upper() + year for prefix, year in TERM_PATTERN.findall(memo)})
        term_code = "; ".join(terms)
        term_description = "; ".join(f"{TERM_NAMES[term[:2]]} 20{term[2:]}" for term in terms)
        tags = sorted({("Operating Account" if kind.lower().startswith("operating") else kind.title(), code)
                       for kind, code in WORKTAG_PATTERN.findall(raw_tags)})
        if not cwid or len(terms) != 1 or not tags:
            warnings += 1
        for kind, code in tags or [("", "")]:
            entry = (cwid, term_code, term_description, kind, code)
            if entry not in seen:
                seen.add(entry)
                rows.append(list(entry))
            if cwid and code:
                assignments.setdefault(cwid, {}).setdefault(kind, set()).add(code)
    if not rows:
        raise ValueError("Grad Contract Worktag export contains no data rows.")
    return StudentWorktags(rows, {
        cwid: {kind: "; ".join(sorted(codes)) for kind, codes in tags.items()}
        for cwid, tags in assignments.items()
    }, warnings)
