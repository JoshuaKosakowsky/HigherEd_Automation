"""Extract and safely refresh Banner classification metadata from Insights."""
from __future__ import annotations

import json
from numbers import Integral
from pathlib import Path
import re
from tempfile import NamedTemporaryFile

from shared.cancellation import CancellationToken
from shared.insights.banner_activity import SQLExecutor
from shared.insights.client import InsightsAPIError
from shared.progress import ProgressReporter

QUERY_PATH = Path(__file__).resolve().parents[2] / "query" / "AR" / "reference" / "detail_codes_extract.sql"
FIELDS = {"detail_code", "type", "category", "detail_code_description", "extract_remaining_count"}


def extract_detail_codes(
    executor: SQLExecutor, *, cancellation: CancellationToken | None = None,
    progress: ProgressReporter | None = None,
) -> dict[str, dict[str, object]]:
    """Accept only complete, unique, usable classifications; include all codes."""
    template = QUERY_PATH.read_text(encoding="utf-8")
    records: dict[str, dict[str, object]] = {}
    cursor = None
    remaining = None
    page_size = 1000
    while True:
        if cancellation:
            cancellation.check()
        if progress:
            progress.report("Extracting and checking Banner detail-code classifications")
        predicate = "TRUE" if cursor is None else f"UPPER(TRIM(d.tbbdetc_detail_code)) > '{cursor}'"
        result = executor.run_sql(template.replace("__CURSOR_FILTER__", predicate)
                                  .replace("__PAGE_SIZE__", str(page_size)))
        if cancellation:
            cancellation.check()
        if FIELDS - set(result.columns):
            raise InsightsAPIError("Insights omitted required detail-code fields or completeness guards.")
        if result.empty:
            raise InsightsAPIError("Insights returned an empty or incomplete detail-code reference. The saved reference was preserved.")
        counts = result["extract_remaining_count"]
        if any(not ((isinstance(value, Integral) and not isinstance(value, bool))
                   or (isinstance(value, str) and re.fullmatch(r"[0-9]+", value))) for value in counts):
            raise InsightsAPIError("Insights returned an invalid detail-code row count.")
        totals = {int(value) for value in counts}
        if len(totals) != 1:
            raise InsightsAPIError("Insights returned inconsistent detail-code row counts.")
        total = totals.pop()
        if total < len(result) or (remaining is not None and remaining != total):
            raise InsightsAPIError("Detail-code counts changed or were inconsistent. Retry the refresh.")
        remaining = total
        expected = min(total, page_size)
        if len(result) > expected:
            raise InsightsAPIError("Insights returned more detail codes than requested.")
        if len(result) < expected:
            page_size = len(result)
            continue
        for row in result.to_dict("records"):
            code = row["detail_code"]
            kind, category, description = row["type"], row["category"], row["detail_code_description"]
            if not isinstance(code, str) or re.fullmatch(r"[A-Z0-9]{4}", code) is None:
                raise InsightsAPIError("Banner returned an invalid detail code. The saved reference was preserved.")
            if cursor is not None and code <= cursor:
                raise InsightsAPIError("Banner returned duplicate or unordered detail codes.")
            if not isinstance(kind, str) or kind not in {"C", "P"} or not isinstance(category, str) or not category.strip() or not isinstance(description, str):
                raise InsightsAPIError("Banner returned an invalid charge/payment classification or category. The saved reference was preserved.")
            records[code] = {"type": kind, "category": category.strip().upper(),
                             "detail_code_description": description.strip()}
            cursor = code
        remaining -= len(result)
        if remaining == 0:
            return records


def refresh_detail_codes(
    executor: SQLExecutor, path: Path, *,
    cancellation: CancellationToken | None = None,
    progress: ProgressReporter | None = None,
) -> int:
    """Replace a reference atomically after validation; never publish partial data.

    Extra Excel-derived metadata for retained codes is preserved. Local refreshes
    are serialized and the source is rechecked before replacement. OneDrive does
    not provide a distributed lock; conflicting synced edits still need review.
    """
    if not path.parent.is_dir():
        raise ValueError("The shared reference folder is unavailable. Check OneDrive synchronization.")
    lock_path = path.with_name(f".{path.name}.lock")
    try:
        lock = lock_path.open("x", encoding="utf-8")
    except FileExistsError:
        raise ValueError("A detail-code refresh is already running. If an earlier run stopped unexpectedly, ask an administrator to review the reference lock.") from None
    temporary = None
    try:
        with lock:
            original = path.read_bytes() if path.exists() else None
            if original is not None:
                try:
                    existing = json.loads(original)
                except (ValueError, UnicodeError):
                    raise ValueError("The existing detail-code reference is invalid JSON. Review it before refreshing; it was preserved.") from None
                if not isinstance(existing, dict) or any(not isinstance(value, dict) for value in existing.values()):
                    raise ValueError("The existing detail-code reference has an invalid structure. Review it before refreshing; it was preserved.")
            else:
                existing = {}
            records = extract_detail_codes(executor, cancellation=cancellation, progress=progress)
            records = {code: {**existing.get(code, {}), **metadata} for code, metadata in records.items()}
            if progress:
                progress.report(f"Saving {len(records):,} checked detail-code classifications")
            with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                    prefix=".detail_codes-", suffix=".json", delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(records, stream, ensure_ascii=False, indent=2, allow_nan=False)
                stream.write("\n")
            if cancellation:
                cancellation.check()
            current = path.read_bytes() if path.exists() else None
            if current != original:
                raise ValueError("The shared detail-code reference changed during refresh. Retry; the newer file was preserved.")
            temporary.replace(path)
            return len(records)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        lock_path.unlink(missing_ok=True)
