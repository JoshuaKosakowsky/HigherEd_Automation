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

from data_processing.shared.source_exports import money
from shared.mines_paths import get_shared_csmf_balances_directory
from .sources import LOANS, opening_values, read_trial_balance, validate_fiscal_year


def file_digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


@dataclass(frozen=True)
class ProjectBalance:
    amount: Decimal | None = None
    updated_at: str | None = None
    source_name: str | None = None
    source_digest: str | None = None


@dataclass(frozen=True)
class OpeningBalances:
    fiscal_year: int
    projects: tuple[tuple[str, ProjectBalance], ...]
    # The latest upload to the FY file can differ from individual project dates.
    updated_at: str
    source_name: str
    source_digest: str

    @property
    def values(self) -> tuple[tuple[str, Decimal | None], ...]:
        return tuple((project, balance.amount) for project, balance in self.projects)


@dataclass(frozen=True)
class BalanceSelection:
    balances: OpeningBalances
    expected_digest: str | None
    trial_path: Path | None = None
    uploaded_projects: tuple[str, ...] = ()


def _validate_upload(updated_at: str, source_name: str, source_digest: str) -> None:
    if datetime.fromisoformat(updated_at).tzinfo is None or not isinstance(source_name, str):
        raise ValueError("Invalid saved provenance")
    if not re.fullmatch(r"[0-9a-f]{64}", source_digest):
        raise ValueError("Invalid source digest")


def _load_project(payload: dict) -> ProjectBalance:
    amount = None if payload["amount"] is None else money(payload["amount"])
    updated_at, name, digest = payload["updated_at"], payload["source_name"], payload["source_sha256"]
    if updated_at is None and name is None and digest is None:
        if amount is not None:
            raise ValueError("Saved amount has no provenance")
    else:
        _validate_upload(updated_at, name, digest)
    return ProjectBalance(amount, updated_at, name, digest)


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
            version = payload["schema_version"]
            if version not in {1, 2} or payload["fiscal_year"] != self.fiscal_year:
                raise ValueError("Invalid saved FY or schema")
            values = payload["balances"]
            if not isinstance(values, dict) or set(values) != set(LOANS):
                raise ValueError("Invalid saved projects")
            _validate_upload(payload["updated_at"], payload["source_name"], payload["source_sha256"])
            if version == 1:
                # Earlier releases gave every project the same upload metadata.
                # Upgrade in memory; cache-only runs must not rewrite that file.
                values = {project: {"amount": amount, "updated_at": payload["updated_at"],
                                   "source_name": payload["source_name"], "source_sha256": payload["source_sha256"]}
                          for project, amount in values.items()}
            balances = OpeningBalances(self.fiscal_year,
                tuple((project, _load_project(values[project])) for project in LOANS),
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
            "schema_version": 2, "fiscal_year": balances.fiscal_year,
            "updated_at": balances.updated_at, "source_name": balances.source_name,
            "source_sha256": balances.source_digest,
            "balances": {project: {
                "amount": str(balance.amount) if balance.amount is not None else None,
                "updated_at": balance.updated_at, "source_name": balance.source_name,
                "source_sha256": balance.source_digest,
            } for project, balance in balances.projects},
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
    projects = dict(cached.projects) if cached is not None else {project: ProjectBalance() for project in LOANS}
    for project, amount in values:
        projects[project] = ProjectBalance(amount, stamp, trial_path.name, digest)
    balances = OpeningBalances(store.fiscal_year, tuple(projects.items()), stamp, trial_path.name, digest)
    return BalanceSelection(balances, expected, trial_path.resolve(),
                            tuple(project for project, _ in values))


def balance_summary(selection: BalanceSelection) -> str:
    balances = selection.balances
    action = "New upload — updates only listed projects when the run succeeds" if selection.trial_path else "Saved opening balances"
    stamp = datetime.fromisoformat(balances.updated_at).strftime("%Y-%m-%d %H:%M %z")
    lines = []
    for project, balance in balances.projects:
        amount = "Blank" if balance.amount is None else f"${balance.amount:,.2f}"
        date = datetime.fromisoformat(balance.updated_at).strftime("%Y-%m-%d %H:%M %z") if balance.updated_at else "Not supplied"
        state = "from upload" if project in selection.uploaded_projects else "saved" if balance.updated_at else "no saved balance"
        lines.append(f"{project} · {LOANS[project]}: {amount} — {date} ({state})")
    return "\n".join([
        f"FY{balances.fiscal_year} — {action}",
        f"Latest Trial Balance upload: {stamp}",
        f"Source: {balances.source_name}", "",
        *lines,
    ])
