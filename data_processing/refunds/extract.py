from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
import json
from pathlib import Path
import re
from typing import Protocol

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
}


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


def _scope_sql(settings: ExtractSettings) -> str:
    # Settings validate literals before native SQL is sent to Insights.
    return (
        (QUERY_DIRECTORY / "refund_scope.sql").read_text(encoding="utf-8")
        .replace("__RUN_DATE__", f"DATE '{settings.run_date.isoformat()}'")
        .replace("__TARGET_TERM_OVERRIDE__", f"'{settings.target_term}'")
        .replace("__CWID_FILTER__", f"'{settings.cwid.strip()}'" if settings.cwid else "NULL")
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
    )
    header = (
        "/* MANUAL WEBSITE EXPORT: download the complete result as XLSX or CSV.\n"
        "Use identical run_date, target_term_override and cwid_filter in both exports.\n"
        "Defaults: today's term, entire candidate population. Never commit a CWID.\n"
        "Generated from the extract template and refund_scope.sql; regenerate when either changes. */\n"
    )
    # The template's API-only introduction is misleading in a runnable export.
    body = re.sub(r"\A\s*/\*.*?\*/\s*", "", template, count=1, flags=re.DOTALL)
    return header + body.replace("__REFUND_SCOPE_SQL__", scope)


def render_extract_sql(template: str, settings: ExtractSettings, batch_index: int) -> str:
    """Render one validated extraction batch from a repository SQL template."""
    if not 0 <= batch_index < settings.batch_count:
        raise ValueError("Batch index is outside the configured batch count.")
    rendered = (
        template.replace("__REFUND_SCOPE_SQL__", _scope_sql(settings))
        .replace("__BATCH_COUNT__", str(settings.batch_count))
        .replace("__BATCH_INDEX__", str(batch_index))
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


def _validate_complete_result(
    frame: pd.DataFrame,
    label: str,
    batch_index: int | None,
) -> pd.DataFrame:
    result = frame.copy()
    result.columns = [
        re.sub(r"[^a-z0-9]+", "_", str(column).strip().lower()).strip("_")
        for column in result.columns
    ]
    location = (
        f"batch {batch_index + 1}"
        if batch_index is not None
        else "download"
    )
    if "extract_row_count" not in result.columns:
        raise ValueError(f"{label} {location} did not return its row-count guard.")
    if not result.empty:
        expected = int(result["extract_row_count"].iloc[0])
        if expected != len(result):
            raise RuntimeError(
                f"Insights truncated {label} {location}: "
                f"expected {expected:,} rows but received {len(result):,}. "
                "Increase --batch-count and start a fresh extraction without --resume."
            )
    return result.drop(columns=["extract_row_count"])


def _manifest_values(settings: ExtractSettings) -> dict[str, object]:
    return {
        "format_version": 3,
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
            path = settings.extract_directory / f"{label}_{batch_index:03d}.csv"
            if settings.resume and path.exists():
                frame = _read_cached(path)
                source = "cache"
            else:
                if progress:
                    progress(f"Extracting {label} batch {batch_index + 1}/{settings.batch_count}...")
                frame = client.run_sql(render_extract_sql(template, settings, batch_index))
                frame = _validate_complete_result(frame, label, batch_index)
                _write_atomic(frame, path)
                source = "Insights"
            frames.append(frame)
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
