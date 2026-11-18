"""Fiscal-year opening balances with read-only previews and atomic replacement."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from collections.abc import Iterator

from data_processing.shared.source_exports import SourceData, money
from shared.mines_paths import get_shared_csmf_balances_directory
from .sources import LOANS, opening_values, read_trial_balance, validate_fiscal_year


def file_digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


@dataclass(frozen=True)
class OpeningBalances:
    fiscal_year: int
    values: tuple[tuple[str, Decimal], ...]
    updated_at: str
    source_name: str
    source_digest: str


@dataclass(frozen=True)
class BalanceSelection:
    balances: OpeningBalances
    expected_digest: str | None
    trial_path: Path | None = None
    trial_source: SourceData | None = None


class BalanceStore:
    """One file per FY; local locks detect concurrent app updates on a workstation.

    The existing shared folder is OneDrive synchronized. Local locks cannot
    serialize simultaneous offline edits on different computers.
    """

    def __init__(self, fiscal_year: int, directory: Path | None = None) -> None:
        self.fiscal_year = validate_fiscal_year(fiscal_year)
        self.directory = directory if directory is not None else get_shared_csmf_balances_directory()
        self.path = self.directory / f"FY{self.fiscal_year}.json"

    def load(self) -> tuple[OpeningBalances | None, str | None]:
        try:
            raw = self.path.read_bytes()
        except FileNotFoundError:
            return None, None
        try:
            payload = json.loads(raw)
            if payload["schema_version"] != 1 or payload["fiscal_year"] != self.fiscal_year:
                raise ValueError("Invalid saved FY or schema")
            values = payload["balances"]
            if not isinstance(values, dict) or set(values) != set(LOANS):
                raise ValueError("Invalid saved projects")
            stamp = datetime.fromisoformat(payload["updated_at"])
            if stamp.tzinfo is None or not isinstance(payload["source_name"], str):
                raise ValueError("Invalid saved provenance")
            if not re.fullmatch(r"[0-9a-f]{64}", payload["source_sha256"]):
                raise ValueError("Invalid source digest")
            balances = OpeningBalances(self.fiscal_year,
                tuple((project, money(values[project])) for project in LOANS),
                payload["updated_at"], payload["source_name"], payload["source_sha256"])
        except (ValueError, TypeError, KeyError, OverflowError):
            raise ValueError(f"Saved FY{self.fiscal_year} opening balances are invalid. Restore the saved backup before running.") from None
        return balances, hashlib.sha256(raw).hexdigest()

    @contextmanager
    def locked(self, expected_digest: str | None) -> Iterator[None]:
        self.directory.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_suffix(".lock")
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            raise ValueError("Opening balances are being updated. Retry after the other run finishes.") from None
        try:
            os.close(descriptor)
            _, current_digest = self.load()
            if current_digest != expected_digest:
                raise ValueError("Saved opening balances changed after preview. Review the balances again before running.")
            yield
        finally:
            lock_path.unlink(missing_ok=True)

    def save_locked(self, balances: OpeningBalances) -> None:
        """Caller holds locked(); os.replace preserves the previous file on failure."""
        if balances.fiscal_year != self.fiscal_year or set(dict(balances.values)) != set(LOANS):
            raise ValueError("Opening balances do not match the selected FY/projects.")
        payload = {
            "schema_version": 1, "fiscal_year": balances.fiscal_year,
            "updated_at": balances.updated_at, "source_name": balances.source_name,
            "source_sha256": balances.source_digest,
            "balances": {project: str(amount) for project, amount in balances.values},
        }
        if self.path.exists():
            shutil.copy2(self.path, self.path.with_suffix(".backup.json"))
        descriptor, temporary = tempfile.mkstemp(prefix=".csmf-", suffix=".tmp", dir=self.directory)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            Path(temporary).unlink(missing_ok=True)


def prepare_opening_balances(
    fiscal_year: int, trial_path: Path | None = None, *,
    directory: Path | None = None, now: datetime | None = None,
) -> BalanceSelection:
    """Preview candidates without saving them; cache-only previews preserve time."""
    store = BalanceStore(fiscal_year, directory)
    cached, expected = store.load()
    if trial_path is None:
        if cached is None:
            raise ValueError(f"Upload Trial Balance to create opening balances for FY{store.fiscal_year}.")
        return BalanceSelection(cached, expected)
    trial_path = Path(trial_path)
    digest = file_digest(trial_path)
    source = read_trial_balance(trial_path)
    values = opening_values(source)
    if file_digest(trial_path) != digest:
        raise ValueError("Trial Balance changed while being read. Upload it again.")
    stamp = (now or datetime.now().astimezone()).astimezone().isoformat(timespec="seconds")
    return BalanceSelection(OpeningBalances(store.fiscal_year, values, stamp, trial_path.name, digest),
                            expected, trial_path.resolve(), source)


def balance_summary(selection: BalanceSelection) -> str:
    balances = selection.balances
    action = "New upload — replaces this FY when the run succeeds" if selection.trial_path else "Saved opening balances"
    stamp = datetime.fromisoformat(balances.updated_at).strftime("%Y-%m-%d %H:%M %z")
    return "\n".join([
        f"FY{balances.fiscal_year} — {action}",
        f"Last uploaded/updated: {stamp}",
        f"Source: {balances.source_name}", "",
        *(f"{project} · {LOANS[project]}: ${amount:,.2f}" for project, amount in balances.values),
    ])
