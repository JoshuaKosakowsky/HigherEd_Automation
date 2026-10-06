from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
import json
from pathlib import Path
import re
from typing import Protocol
from time import perf_counter

from shared.cancellation import CancellationToken
from shared.progress import ProgressReporter

import pandas as pd

from .terms import validate_term


CWID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,30}$")
QUERY_DIRECTORY = Path(__file__).resolve().parents[2] / "query" / "AR" / "refunds"
TEMPLATE_TOKENS = {
    "__REFUND_SCOPE_SQL__",
    "__BATCH_COUNT__",
    "__BATCH_INDEX__",
    "__RUN_DATE__",
    "__TARGET_TERM_OVERRIDE__",
    "__CWID_FILTER__",
    "__PIDM_FILTER__",
    "__IDENTITY_PIDM_FILTER__",
    "__TRANSACTION_FILTER__",
}
MAX_SUBDIVISION_DEPTH = 64
PARTITION_COLUMNS = {
    "extract_partition_row_count", "extract_pidm_min", "extract_pidm_max",
    "extract_tran_min", "extract_tran_max",
}


class RefundExtractError(RuntimeError):
    """A safe-to-display extraction error; no account identifiers are included."""


class TruncatedRefundExtractError(RefundExtractError):
    def __init__(self, label: str, location: str, expected: int, received: int) -> None:
        self.expected = expected
        self.received = received
        super().__init__(
            f"Insights truncated {label} {location}: expected {expected:,} rows "
            f"but received {received:,}. No incomplete result was accepted. "
            "For manual downloads, export the complete result; for SQL runs, "
            "review the extraction log or contact the automation administrator."
        )


class SQLClient(Protocol):
    def run_sql(self, sql: str) -> pd.DataFrame: ...


@dataclass(frozen=True)
class ExtractSettings:
    target_term: str
    batch_count: int
    extract_directory: Path
    cwid: str | None = None
    resume: bool = False
    run_date: date = field(default_factory=date.today)

    def __post_init__(self) -> None:
        validate_term(self.target_term)
        if self.batch_count <= 0:
            raise ValueError("Batch count must be a positive integer.")
        if self.cwid is not None and not CWID_PATTERN.fullmatch(self.cwid.strip()):
            raise ValueError("CWID may contain only letters, digits, underscores, and hyphens.")


def _range_filter(column: str, bounds: tuple[int | None, int | None]) -> str:
    low, high = bounds
    if any(value is not None and type(value) is not int for value in bounds):
        raise ValueError("Extraction ranges must use integer boundaries.")
    if low is not None and high is not None and low > high:
        raise ValueError("Extraction range boundaries are reversed.")
    parts = []
    if low is not None:
        parts.append(f"{column} >= {low}")
    if high is not None:
        parts.append(f"{column} <= {high}")
    return " AND ".join(parts) or "TRUE"


def _scope_sql(settings: ExtractSettings, pidm_range: tuple[int | None, int | None]) -> str:
    # Settings validate literals before native SQL is sent to Insights.
    return (
        (QUERY_DIRECTORY / "refund_scope.sql").read_text(encoding="utf-8")
        .replace("__RUN_DATE__", f"DATE '{settings.run_date.isoformat()}'")
        .replace("__TARGET_TERM_OVERRIDE__", f"'{settings.target_term}'")
        .replace("__CWID_FILTER__", f"'{settings.cwid.strip()}'" if settings.cwid else "NULL")
        .replace("__PIDM_FILTER__", _range_filter("t.tbraccd_pidm", pidm_range))
        .replace("__IDENTITY_PIDM_FILTER__", _range_filter("i.spriden_pidm", pidm_range))
    )


def render_manual_extract_sql(template: str) -> str:
    """Generate standalone website SQL from the same scope used by API batches."""
    scope = (
        (QUERY_DIRECTORY / "refund_scope.sql").read_text(encoding="utf-8")
        .replace("__RUN_DATE__", "CURRENT_DATE")
        .replace("__TARGET_TERM_OVERRIDE__", "NULL")
        .replace("__CWID_FILTER__", "NULL")
        .replace("__BATCH_COUNT__", "1")
        .replace("__BATCH_INDEX__", "0")
        .replace("__PIDM_FILTER__", "TRUE")
        .replace("__IDENTITY_PIDM_FILTER__", "TRUE")
    )
    header = (
        "/* MANUAL WEBSITE EXPORT: download the complete result as XLSX or CSV.\n"
        "Use identical run_date, target_term_override and cwid_filter in both exports.\n"
        "Defaults: today's term, entire candidate population. Never commit a CWID.\n"
        "Generated from the extract template and refund_scope.sql; regenerate when either changes. */\n"
    )
    # The template's API-only introduction is misleading in a runnable export.
    body = re.sub(r"\A\s*/\*.*?\*/\s*", "", template, count=1, flags=re.DOTALL)
    return header + body.replace("__REFUND_SCOPE_SQL__", scope).replace("__TRANSACTION_FILTER__", "TRUE")


def render_extract_sql(
    template: str, settings: ExtractSettings, batch_index: int, *,
    pidm_range: tuple[int | None, int | None] = (None, None),
    transaction_range: tuple[int | None, int | None] = (None, None),
) -> str:
    """Render one validated extraction batch from a repository SQL template."""
    if not 0 <= batch_index < settings.batch_count:
        raise ValueError("Batch index is outside the configured batch count.")
    rendered = (
        template.replace("__REFUND_SCOPE_SQL__", _scope_sql(settings, pidm_range))
        .replace("__BATCH_COUNT__", str(settings.batch_count))
        .replace("__BATCH_INDEX__", str(batch_index))
        .replace("__PIDM_FILTER__", _range_filter("t.tbraccd_pidm", pidm_range))
        .replace("__IDENTITY_PIDM_FILTER__", _range_filter("i.spriden_pidm", pidm_range))
        .replace("__TRANSACTION_FILTER__", _range_filter("t.tbraccd_tran_number", transaction_range))
    )
    unresolved = sorted(token for token in TEMPLATE_TOKENS if token in rendered)
    if unresolved:
        raise ValueError(f"Unresolved SQL template tokens: {', '.join(unresolved)}")
    return rendered


def _read_cached(path: Path) -> pd.DataFrame:
    return pd.read_csv(
        path,
        dtype={
            "term_code": "string",
            "aidy_code": "string",
            "detail_code": "string",
            "priority": "string",
            "category_code": "string",
            "title_iv_ind": "string",
            "cwid": "string",
            "plus_auth_aidy_code": "string",
            "plus_to_student": "string",
        },
    )


def _write_atomic(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temporary, index=False)
    temporary.replace(path)


def _normalized_result(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result.columns = [
        re.sub(r"[^a-z0-9]+", "_", str(column).strip().lower()).strip("_")
        for column in result.columns
    ]
    return result


def _row_count(frame: pd.DataFrame, column: str) -> int:
    if column not in frame:
        raise ValueError(f"Insights result did not return its {column} guard.")
    if frame.empty:
        return 0
    values = pd.to_numeric(frame[column], errors="coerce")
    value = values.iloc[0]
    if pd.isna(value) or value < 0 or value % 1 or not values.eq(value).all():
        raise ValueError(f"Insights result returned an invalid {column} guard.")
    return int(value)


def _validate_complete_result(
    frame: pd.DataFrame,
    label: str,
    batch_index: int | None,
) -> pd.DataFrame:
    result = _normalized_result(frame)
    location = (
        f"batch {batch_index + 1}"
        if batch_index is not None
        else "download"
    )
    if "extract_row_count" not in result.columns:
        raise ValueError(f"{label} {location} did not return its row-count guard.")
    if not result.empty:
        expected = _row_count(result, "extract_row_count")
        if expected != len(result):
            if expected < len(result):
                raise RefundExtractError(f"Insights returned more {label} rows than its count guard.")
            raise TruncatedRefundExtractError(label, location, expected, len(result))
    return result.drop(columns=["extract_row_count"])


def _render_partition_sql(sql: str, label: str) -> str:
    """Add range guards to an already filtered extraction query."""
    transaction_bounds = (
        "MIN(source.tran_number) OVER () AS extract_tran_min,\n"
        "    MAX(source.tran_number) OVER () AS extract_tran_max,\n"
        if label == "transactions" else ""
    )
    order = "source.pidm, source.tran_number" if label == "transactions" else "source.pidm"
    return (
        "WITH refund_extract_source AS MATERIALIZED (\n"
        + sql.rstrip().removesuffix(";")
        + "\n)\nSELECT\n"
        "    COUNT(*) OVER () AS extract_partition_row_count,\n"
        "    MIN(source.pidm) OVER () AS extract_pidm_min,\n"
        "    MAX(source.pidm) OVER () AS extract_pidm_max,\n"
        f"    {transaction_bounds}source.*\n"
        "FROM refund_extract_source source\n"
        f"ORDER BY {order};"
    )


def _complete_partition(
    client: SQLClient, template: str, label: str, batch_index: int,
    *, settings: ExtractSettings, depth: int = 0,
    pidm_range: tuple[int | None, int | None] = (None, None),
    transaction_range: tuple[int | None, int | None] = (None, None),
    location: str | None = None, cancellation: CancellationToken | None = None,
    progress: Callable[[str], None] | None = None,
    progress_reporter: ProgressReporter | None = None,
) -> pd.DataFrame:
    """Bisect disjoint integer ranges until each result passes the count guard."""
    location = location or str(batch_index + 1)
    if cancellation:
        cancellation.check()
    sql = render_extract_sql(
        template, settings, batch_index, pidm_range=pidm_range,
        transaction_range=transaction_range,
    )
    started = perf_counter()
    if progress_reporter:
        progress_reporter.report(
            f"Extracting refund {label} — batch/partition {location}",
            completed=batch_index * 2 + (label == "context"), total=settings.batch_count * 2,
        )
    raw = _normalized_result(client.run_sql(_render_partition_sql(sql, label)))
    if progress:
        progress(f"{label.capitalize()} batch {location} query returned {len(raw):,} rows in {perf_counter() - started:.1f}s.")
    if cancellation:
        cancellation.check()
    required = PARTITION_COLUMNS if label == "transactions" else PARTITION_COLUMNS - {
        "extract_tran_min", "extract_tran_max",
    }
    if not required.issubset(raw.columns):
        raise ValueError("Insights result lacks automatic-subdivision count or range guards.")
    expected = _row_count(raw, "extract_partition_row_count")
    source_count = _row_count(raw, "extract_row_count")
    if expected != source_count:
        raise RefundExtractError(
            f"Insights returned conflicting {label} row-count guards. "
            "No incomplete batch was saved."
        )
    frame = raw.drop(columns=list(PARTITION_COLUMNS & set(raw.columns)))
    frame["extract_row_count"] = raw["extract_partition_row_count"]
    try:
        complete = _validate_complete_result(frame, label, batch_index)
    except TruncatedRefundExtractError:
        if progress:
            progress(
                f"{label.capitalize()} batch {location} expected {expected:,} rows "
                f"but received {len(raw):,}; subdividing."
            )
        if depth >= MAX_SUBDIVISION_DEPTH:
            raise RefundExtractError(
                f"Automatic subdivision reached its safety limit for {label} batch {location}. "
                "No incomplete batch was saved. Contact the automation administrator."
            ) from None
        for column, low_name, high_name in (
            ("pidm", "extract_pidm_min", "extract_pidm_max"),
            ("tran_number", "extract_tran_min", "extract_tran_max"),
        ):
            if low_name not in raw:
                continue
            low, high = raw[low_name].iloc[0], raw[high_name].iloc[0]
            if pd.isna(low) or pd.isna(high) or low % 1 or high % 1:
                raise RefundExtractError(
                    f"Insights returned invalid subdivision ranges for {label} batch {location}. "
                    "No incomplete batch was saved."
                ) from None
            if low < high:
                midpoint = (int(low) + int(high)) // 2
                break
        else:
            raise RefundExtractError(
                f"Insights still truncates the smallest {label} partition in batch {location}. "
                "A single account or transaction cannot be subdivided further. "
                "No incomplete batch was saved. Contact the automation administrator."
            ) from None
        bounds = pidm_range if column == "pidm" else transaction_range
        parts = []
        for child, child_bounds in ((1, (bounds[0], midpoint)), (2, (midpoint + 1, bounds[1]))):
            parts.append(_complete_partition(
                client, template, label, batch_index, settings=settings,
                pidm_range=child_bounds if column == "pidm" else pidm_range,
                transaction_range=child_bounds if column == "tran_number" else transaction_range,
                depth=depth + 1, location=f"{location}.{child}", progress=progress,
                cancellation=cancellation,
                progress_reporter=progress_reporter,
            ))
        combined = pd.concat(parts, ignore_index=True)
        if len(combined) != expected:
            raise RefundExtractError(
                f"Recombined {label} batch {location} has {len(combined):,} rows; "
                f"expected {expected:,}. No incomplete batch was saved. "
                "Start a fresh extraction."
            ) from None
        return combined
    if progress:
        progress(f"{label.capitalize()} batch {location} complete: {len(complete):,} rows.")
    return complete


def _manifest_values(settings: ExtractSettings) -> dict[str, object]:
    return {
        "format_version": 4,
        "target_term": settings.target_term,
        "batch_count": settings.batch_count,
        "cwid": settings.cwid,
        "run_date": settings.run_date.isoformat(),
    }


def _prepare_manifest(settings: ExtractSettings) -> None:
    settings.extract_directory.mkdir(parents=True, exist_ok=True)
    path = settings.extract_directory / "extract_manifest.json"
    expected = _manifest_values(settings)
    if settings.resume and path.exists():
        actual = json.loads(path.read_text(encoding="utf-8"))
        if actual != expected:
            raise ValueError(
                "The existing extract manifest does not match this run. "
                "Use a different --extract-dir or remove --resume."
            )
        return
    path.write_text(json.dumps(expected, indent=2) + "\n", encoding="utf-8")


def extract_refund_data(
    client: SQLClient,
    settings: ExtractSettings,
    *,
    transaction_template_path: Path,
    context_template_path: Path,
    progress: Callable[[str], None] | None = None,
    cancellation: CancellationToken | None = None,
    progress_reporter: ProgressReporter | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run or resume every flat Insights extraction batch."""
    _prepare_manifest(settings)
    transaction_template = transaction_template_path.read_text(encoding="utf-8")
    context_template = context_template_path.read_text(encoding="utf-8")
    transaction_frames: list[pd.DataFrame] = []
    context_frames: list[pd.DataFrame] = []

    for batch_index in range(settings.batch_count):
        for label, template, frames in (
            ("transactions", transaction_template, transaction_frames),
            ("context", context_template, context_frames),
        ):
            if cancellation:
                cancellation.check()
            path = settings.extract_directory / f"{label}_{batch_index:03d}.csv"
            if settings.resume and path.exists():
                if progress_reporter:
                    progress_reporter.report(f"Reading cached refund {label} batch {batch_index + 1}")
                frame = _read_cached(path)
                source = "cache"
            else:
                if progress:
                    progress(f"Extracting {label} batch {batch_index + 1}/{settings.batch_count}...")
                frame = _complete_partition(
                    client, template, label, batch_index, settings=settings,
                    progress=progress, cancellation=cancellation,
                    progress_reporter=progress_reporter,
                )
                if cancellation:
                    cancellation.check()
                _write_atomic(frame, path)
                source = "Insights"
            frames.append(frame)
            if progress_reporter:
                progress_reporter.report(
                    "Extracting refund data — complete batches",
                    completed=batch_index * 2 + 1 + (label == "context"),
                    total=settings.batch_count * 2,
                )
            if progress:
                progress(
                    f"Loaded {len(frame):,} {label} rows for batch "
                    f"{batch_index + 1}/{settings.batch_count} from {source}."
                )

    transactions = pd.concat(transaction_frames, ignore_index=True) if transaction_frames else pd.DataFrame()
    context = pd.concat(context_frames, ignore_index=True) if context_frames else pd.DataFrame()
    return transactions, context


def read_refund_extracts(settings: ExtractSettings) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load a complete cached extraction without contacting Insights."""
    manifest_path = settings.extract_directory / "extract_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Refund extract manifest was not found: {manifest_path}")
    actual = json.loads(manifest_path.read_text(encoding="utf-8"))
    if actual != _manifest_values(settings):
        raise ValueError("The extract manifest does not match the requested offline run.")
    transaction_frames = []
    context_frames = []
    for batch_index in range(settings.batch_count):
        for label, frames in (("transactions", transaction_frames), ("context", context_frames)):
            path = settings.extract_directory / f"{label}_{batch_index:03d}.csv"
            if not path.exists():
                raise FileNotFoundError(f"Cached refund extract is incomplete: {path}")
            frames.append(_read_cached(path))
    return pd.concat(transaction_frames, ignore_index=True), pd.concat(context_frames, ignore_index=True)
