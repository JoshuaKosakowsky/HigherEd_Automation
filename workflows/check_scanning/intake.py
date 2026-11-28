"""Durable, per-user PaperCut scan inventory and filing verification."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass
import hashlib
from itertools import count
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from time import monotonic

from shared.user_settings import get_user_settings_path
from .detection import NEEDS_REVIEW, Box, Finding, Mark
from .documents import inspect_pdf, local_ocr, page_count, redact_pdf


def queue_path() -> Path:
    settings = get_user_settings_path()
    if settings is None:
        raise ValueError("Local app data is unavailable for this login.")
    # Keep pilot approvals out of the filing history used when shared filing opens.
    return settings.parent / "check-scanning" / "pilot-queue.sqlite3"


def check_scan_output_directory() -> Path:
    return Path.home() / "Documents" / "Tests"


@dataclass(frozen=True)
class FiledScan:
    source_name: str
    source_digest: str
    output: Path
    output_digest: str


def _file_digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def fingerprint(path: Path) -> tuple[int, int, int]:
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def _verify_filed_copy(path: Path, checksum: str) -> None:
    if path.parent != check_scan_output_directory() or path.is_symlink():
        raise ValueError("The redacted copy is outside the filing destination.")
    try:
        version = fingerprint(path)
        unchanged = _file_digest(path) == checksum and fingerprint(path) == version
    except OSError as error:
        raise ValueError("The redacted copy is unavailable.") from error
    if not unchanged or path.is_symlink():
        raise ValueError("The redacted copy changed after approval.")


def inbox_versions(inbox: Path) -> dict[str, tuple[int, int, int]]:
    versions = {}
    for path in inbox.iterdir():
        if path.is_symlink() or path.suffix.lower() in {".tmp", ".partial", ".crdownload", ".part"}:
            continue
        try:
            if path.is_file():
                versions[path.name] = fingerprint(path)
        except OSError:
            continue
    return versions


def decode_finding(record) -> Finding:
    info = json.loads(record["finding"])
    return Finding(info["status"], [Mark(m["page"], m["kind"], Box(**m["box"])) for m in info["marks"]],
                   info["issuer"], info["number"])


def missing_redactions(marks: list[Mark]) -> tuple[str, ...]:
    marked = {mark.kind for mark in marks}
    return tuple(kind for kind in ("MICR", "Signature") if kind not in marked)


def is_pending_review(record) -> bool:
    return record["status"] not in ("Not a PDF", "Unrelated", "Dismissed", "Filed")


def review_output_path(record, issuer: str, number: str) -> Path:
    target = check_scan_output_directory() / output_name(issuer, number)
    if record["status"] == "Filed" and target.exists():
        for copy in count(2):
            candidate = target.with_stem(f"{target.stem} ({copy})")
            if not candidate.exists():
                return candidate
    return target


def _publish_copy(stage: Path, target: Path) -> None:
    # Windows rename refuses existing destinations. POSIX link gives the same guarantee.
    if os.name == "nt":
        os.rename(stage, target)
    else:
        os.link(stage, target)


class ScanQueue:
    def __init__(self, inbox: Path, database: Path):
        self.inbox = inbox
        self.database = database
        database.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS scans (
                    name TEXT PRIMARY KEY, size INTEGER, mtime INTEGER, ctime INTEGER,
                    digest TEXT NOT NULL, status TEXT NOT NULL, finding TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS scans_digest ON scans(digest);
                CREATE TABLE IF NOT EXISTS publications (
                    digest TEXT PRIMARY KEY, target TEXT NOT NULL, checksum TEXT NOT NULL,
                    completed INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS repeat_publications (
                    digest TEXT NOT NULL, target TEXT NOT NULL, checksum TEXT NOT NULL,
                    PRIMARY KEY (digest, target));
                CREATE TABLE IF NOT EXISTS filing_corrections (digest TEXT PRIMARY KEY);
            """)
            db.execute("UPDATE scans SET status=? WHERE status=?", (NEEDS_REVIEW, "Needs a look"))
            db.execute(
                "UPDATE scans SET finding=json_set(finding,'$.status',?) WHERE json_extract(finding,'$.status')=?",
                (NEEDS_REVIEW, "Needs a look"),
            )

    @contextmanager
    def connect(self):
        with closing(sqlite3.connect(self.database, timeout=10)) as db, db:
            db.row_factory = sqlite3.Row
            yield db

    def records(self, include_other: bool = False):
        with self.connect() as db:
            rows = db.execute("SELECT * FROM scans WHERE status != 'Not a PDF' ORDER BY mtime, name").fetchall()
        return rows if include_other else [row for row in rows if is_pending_review(row)]

    def known_versions(self) -> dict[str, tuple[int, int, int]]:
        with self.connect() as db:
            return {r["name"]: tuple(r)[1:] for r in db.execute("SELECT name,size,mtime,ctime FROM scans")}

    def source(self, record) -> bytes:
        path = self.inbox / record["name"]
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != record["digest"]:
            raise ValueError("This source changed. Reopen it after the queue refreshes.")
        if b"%PDF-" not in data[:1024] or b"%%EOF" not in data[-4096:]:
            raise ValueError("The source PDF is incomplete. Wait for the scan to finish syncing.")
        return data

    def mark_unrelated(self, record) -> bool:
        with self.connect() as db:
            result = db.execute(
                "UPDATE scans SET status='Unrelated' "
                "WHERE name=? AND digest=? AND status NOT IN ('Not a PDF', 'Unrelated', 'Filed')",
                (record["name"], record["digest"]),
            )
            return result.rowcount == 1

    def filed_copies(self, digest: str) -> dict[Path, str]:
        with self.connect() as db:
            return self._filed_copies(db, digest)

    @staticmethod
    def _filed_copies(db: sqlite3.Connection, digest: str) -> dict[Path, str]:
        rows = db.execute(
            "SELECT target, checksum FROM publications WHERE digest=? AND completed=1 "
            "UNION ALL SELECT target, checksum FROM repeat_publications WHERE digest=?",
            (digest, digest),
        )
        return {Path(row["target"]): row["checksum"] for row in rows}

    def correct_filing(
        self, record, confirmed_copies: dict[Path, str], recycle: Callable[[Path], bool],
    ) -> dict[Path, str]:
        """Withdraw a mistaken filing and return copies that need manual cleanup."""
        digest = record["digest"]
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT status FROM scans WHERE name=? AND digest=?", (record["name"], digest))
            row = current.fetchone()
            if row is None or row["status"] != "Filed":
                raise ValueError("The scan status changed. Reopen it to review the current filing.")
            if self._filed_copies(db, digest) != confirmed_copies:
                raise ValueError("The filed copies changed. Review the updated list before correcting the filing.")
            self.source(record)

            db.execute("INSERT OR IGNORE INTO filing_corrections VALUES(?)", (digest,))
            db.execute("UPDATE scans SET status='Unrelated' WHERE digest=?", (digest,))
            db.execute("DELETE FROM publications WHERE digest=?", (digest,))
            db.execute("DELETE FROM repeat_publications WHERE digest=?", (digest,))
            remaining = {}
            for path, checksum in confirmed_copies.items():
                other_owner = db.execute(
                    "SELECT 1 FROM publications WHERE target=? COLLATE NOCASE "
                    "UNION ALL SELECT 1 FROM repeat_publications WHERE target=? COLLATE NOCASE LIMIT 1",
                    (str(path), str(path)),
                ).fetchone()
                if other_owner:
                    remaining[path] = "This path is also recorded for another scan."
                    continue
                try:
                    _verify_filed_copy(path, checksum)
                    if not recycle(path):
                        remaining[path] = "Could not move this copy to the Recycle Bin."
                except ValueError as error:
                    remaining[path] = str(error)
                except OSError:
                    remaining[path] = "Could not move this copy to the Recycle Bin."
            return remaining

    def file(self, record, marks, issuer: str, number: str) -> FiledScan:
        if decode_finding(record).status == "Multiple check pages":
            raise ValueError("Separate or verify this multi-check packet manually before filing.")
        target = review_output_path(record, issuer, number)
        repeat_review = record["status"] == "Filed"
        if missing_redactions(marks):
            raise ValueError("Mark the MICR band and the issuer signature before filing.")
        source = self.source(record)
        name = record["name"]
        digest = record["digest"]
        if not repeat_review:
            with self.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                old = db.execute("SELECT * FROM publications WHERE digest=?", (digest,)).fetchone()
                if old and Path(old["target"]).is_file():
                    old_target = Path(old["target"])
                    if _file_digest(old_target) != old["checksum"]:
                        raise ValueError("The previously filed copy has changed. Review the destination manually.")
                    db.execute("UPDATE publications SET completed=1 WHERE digest=?", (digest,))
                    db.execute("UPDATE scans SET status='Filed' WHERE digest=?", (digest,))
                    return FiledScan(name, digest, old_target, old["checksum"])
        if target.exists():
            raise FileExistsError("That filename already exists. Review the issuer and check number.")
        target.parent.mkdir(parents=True, exist_ok=True)
        # Write only redacted data into the destination directory.
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".check-scan-", suffix=".tmp", delete=False) as tmp:
            stage = Path(tmp.name)
        try:
            redact_pdf(source, marks, stage)
            checksum = _file_digest(stage)
            filing = FiledScan(name, digest, target, checksum)
            if page_count(stage.read_bytes()) != page_count(source):
                raise ValueError("The output page count could not be verified.")
            self.source(record)
            with self.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                current = db.execute("SELECT status FROM scans WHERE name=? AND digest=?",
                                     (record["name"], digest)).fetchone()
                if current is None or current["status"] != record["status"]:
                    raise ValueError("The queue entry changed. Refresh before filing.")
                if repeat_review:
                    # Keep the initial receipt for deduplication and track repeat copies for corrections.
                    db.execute("INSERT OR REPLACE INTO repeat_publications VALUES(?,?,?)",
                               (digest, str(target), checksum))
                    _publish_copy(stage, target)
                    return filing
                pending = db.execute("SELECT target FROM publications WHERE digest=?", (digest,)).fetchone()
                if pending and Path(pending["target"]).exists():
                    raise ValueError("A copy was already filed. Reopen the queue to reconcile it.")
                db.execute("INSERT OR REPLACE INTO publications(digest,target,checksum) VALUES(?,?,?)",
                           (digest, str(target), checksum))
            with self.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                intent = db.execute("SELECT target, checksum FROM publications WHERE digest=?", (digest,)).fetchone()
                if tuple(intent) != (str(target), checksum):
                    raise ValueError("Another review changed this filing. Reopen the queue.")
                _publish_copy(stage, target)
                db.execute("UPDATE publications SET completed=1 WHERE digest=?", (digest,))
                db.execute("DELETE FROM filing_corrections WHERE digest=?", (digest,))
                db.execute("UPDATE scans SET status='Filed' WHERE digest=?", (digest,))
            return filing
        finally:
            stage.unlink(missing_ok=True)

    def original_for_recycling(self, filing: FiledScan) -> Path:
        """Verify the filed bytes and the original immediately before recycling."""
        _verify_filed_copy(filing.output, filing.output_digest)
        with self.connect() as db:
            if db.execute("SELECT 1 FROM filing_corrections WHERE digest=?", (filing.source_digest,)).fetchone():
                raise ValueError("The filing was withdrawn and the original scan was kept.")
        path = self.inbox / filing.source_name
        if path.parent != self.inbox or path.is_symlink() or not path.is_file():
            raise ValueError("The original scan is unavailable.")
        version = fingerprint(path)
        if _file_digest(path) != filing.source_digest or fingerprint(path) != version or path.is_symlink():
            raise ValueError("The original scan changed after approval.")
        return path


def output_name(issuer: str, number: str) -> str:
    issuer, number = issuer.strip(), number.strip()
    if not issuer or not number:
        raise ValueError("Enter the company name and check number.")
    if not re.fullmatch(r"[0-9A-Za-z-]+", number):
        raise ValueError("Use letters, digits or hyphens in the check number.")
    if re.search(r'[<>:"/\\|?*\x00-\x1f]', issuer):
        raise ValueError('Remove any forbidden Windows filename characters from the company name (< > : " / \\ | ? *).')
    if re.match(r"^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])\.", issuer, re.I):
        raise ValueError("Edit the company name so it can be used in a Windows filename.")
    if len(issuer) + len(number) > 210:
        raise ValueError("Shorten the company name or check number so the filename fits.")
    return f"{issuer} - {number}.pdf"


class ScanIntake:
    def __init__(self, queue: ScanQueue, recognize=None):
        self.queue = queue
        self.recognize = recognize
        self.observed = {}

    def poll(self, stop=lambda: False) -> None:
        """Reconcile the entire directory; duplicate events or a restart need no special handling."""
        now = monotonic()
        files = inbox_versions(self.queue.inbox)
        known = self.queue.known_versions()
        with self.queue.connect() as db:
            for name in known.keys() - files.keys():
                db.execute("DELETE FROM scans WHERE name=?", (name,))
        self.observed = {name: value for name, value in self.observed.items() if name in files}
        for name, version in files.items():
            if stop():
                return
            if known.get(name) == version:
                continue
            last, since = self.observed.get(name, (None, now))
            if last != version:
                self.observed[name] = (version, now)
                continue
            if now - since < 2 or not version[0]:
                continue
            path = self.queue.inbox / name
            try:
                with path.open("rb") as src:
                    head = src.read(1024)
                    if b"%PDF-" not in head and path.suffix.lower() != ".pdf":
                        with self.queue.connect() as db:
                            db.execute("INSERT OR REPLACE INTO scans VALUES(?,?,?,?,?,?,?)",
                                       (name, *version, "", "Not a PDF", "{}"))
                        continue
                    data = head + src.read()
                if fingerprint(path) != version:
                    continue
            except OSError:
                continue
            digest = hashlib.sha256(data).hexdigest()
            with self.queue.connect() as db:
                duplicate = db.execute("SELECT finding,status FROM scans WHERE digest=? LIMIT 1", (digest,)).fetchone()
            if duplicate:
                info, status = duplicate
            else:
                if self.recognize is None:
                    self.recognize = local_ocr()
                try:
                    if b"%%EOF" not in data[-4096:]:
                        raise ValueError("Incomplete PDF")
                    finding = inspect_pdf(data, self.recognize)
                except (OSError, ValueError, RuntimeError):
                    finding = Finding("Could not read")
                info, status = json.dumps(asdict(finding)), finding.status
            # A long OCR pass must not replace a newer scan or a cashier's decision.
            try:
                if fingerprint(path) != version:
                    continue
            except OSError:
                continue
            with self.queue.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                corrected = db.execute("SELECT 1 FROM filing_corrections WHERE digest=?", (digest,)).fetchone()
                filed = db.execute("SELECT completed FROM publications WHERE digest=?", (digest,)).fetchone()
                if corrected:
                    status = "Unrelated"
                elif filed and filed["completed"]:
                    status = "Filed"
                db.execute("""INSERT INTO scans VALUES(?,?,?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET
                    size=excluded.size,mtime=excluded.mtime,ctime=excluded.ctime,digest=excluded.digest,
                    status=CASE WHEN scans.digest=excluded.digest THEN scans.status ELSE excluded.status END,
                    finding=excluded.finding""", (name, *version, digest, status, info))
