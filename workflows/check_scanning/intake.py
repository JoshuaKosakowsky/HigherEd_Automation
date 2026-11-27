"""Durable, per-user PaperCut scan inventory. Originals are read-only."""

from __future__ import annotations

from contextlib import closing, contextmanager
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from time import monotonic

from shared.user_settings import get_user_settings_path
from .detection import Box, Finding, Mark
from .documents import inspect_pdf, local_ocr, page_count, redact_pdf


def queue_path() -> Path:
    settings = get_user_settings_path()
    if settings is None:
        raise ValueError("Local app data is unavailable for this login.")
    # Keep pilot approvals out of the filing history used when shared filing opens.
    return settings.parent / "check-scanning" / "pilot-queue.sqlite3"


def check_scan_output_directory() -> Path:
    return Path.home() / "Documents" / "Tests"


def fingerprint(path: Path) -> tuple[int, int, int]:
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def decode_finding(record) -> Finding:
    info = json.loads(record["finding"])
    return Finding(info["status"], [Mark(m["page"], m["kind"], Box(**m["box"])) for m in info["marks"]],
                   info["issuer"], info["number"])


def missing_redactions(marks: list[Mark]) -> tuple[str, ...]:
    marked = {mark.kind for mark in marks}
    return tuple(kind for kind in ("MICR", "Signature") if kind not in marked)


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
            """)

    @contextmanager
    def connect(self):
        with closing(sqlite3.connect(self.database, timeout=10)) as db, db:
            db.row_factory = sqlite3.Row
            yield db

    def records(self, include_other: bool = False):
        clause = "" if include_other else "WHERE status NOT IN ('Unrelated', 'Dismissed', 'Filed')"
        with self.connect() as db:
            return db.execute(f"SELECT * FROM scans {clause} ORDER BY mtime, name").fetchall()

    def source(self, record) -> bytes:
        path = self.inbox / record["name"]
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != record["digest"]:
            raise ValueError("This source changed. Reopen it after the queue refreshes.")
        if b"%PDF-" not in data[:1024] or b"%%EOF" not in data[-4096:]:
            raise ValueError("The source PDF is incomplete. Wait for the scan to finish syncing.")
        return data

    def dismiss(self, record):
        with self.connect() as db:
            db.execute("UPDATE scans SET status='Dismissed' WHERE name=? AND digest=? AND status!='Filed'",
                       (record["name"], record["digest"]))

    def file(self, record, marks, issuer: str, number: str) -> Path:
        if decode_finding(record).status == "Multiple check pages":
            raise ValueError("Separate or verify this multi-check packet manually before filing.")
        target = check_scan_output_directory() / output_name(issuer, number)
        if missing_redactions(marks):
            raise ValueError("Mark the MICR band and the issuer signature before filing.")
        source = self.source(record)
        digest = record["digest"]
        with self.connect() as db:
            old = db.execute("SELECT * FROM publications WHERE digest=?", (digest,)).fetchone()
            if old and Path(old["target"]).is_file():
                if hashlib.sha256(Path(old["target"]).read_bytes()).hexdigest() != old["checksum"]:
                    raise ValueError("The previously filed copy has changed. Review the destination manually.")
                db.execute("UPDATE publications SET completed=1 WHERE digest=?", (digest,))
                db.execute("UPDATE scans SET status='Filed' WHERE digest=?", (digest,))
                return Path(old["target"])
        if target.exists():
            raise FileExistsError("That filename already exists. Review the issuer and check number.")
        target.parent.mkdir(parents=True, exist_ok=True)
        # Write only redacted data into the destination directory.
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".check-scan-", suffix=".tmp", delete=False) as tmp:
            stage = Path(tmp.name)
        try:
            redact_pdf(source, marks, stage)
            with stage.open("rb") as stream:
                checksum = hashlib.file_digest(stream, "sha256").hexdigest()
            if page_count(stage.read_bytes()) != page_count(source):
                raise ValueError("The output page count could not be verified.")
            self.source(record)
            with self.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                current = db.execute("SELECT status FROM scans WHERE name=? AND digest=?",
                                     (record["name"], digest)).fetchone()
                if current is None or current["status"] == "Filed":
                    raise ValueError("The queue entry changed. Refresh before filing.")
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
                # Windows rename refuses existing destinations. POSIX link provides the same guarantee.
                if os.name == "nt":
                    os.rename(stage, target)
                else:
                    os.link(stage, target)
                db.execute("UPDATE publications SET completed=1 WHERE digest=?", (digest,))
                db.execute("UPDATE scans SET status='Filed' WHERE digest=?", (digest,))
            return target
        finally:
            stage.unlink(missing_ok=True)


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
        self.non_pdfs = {}

    def poll(self, stop=lambda: False) -> None:
        """Reconcile the entire directory; duplicate events or a restart need no special handling."""
        now = monotonic()
        files = {}
        for path in self.queue.inbox.iterdir():
            if path.is_symlink() or path.suffix.lower() in {".tmp", ".partial", ".crdownload", ".part"}:
                continue
            try:
                if path.is_file():
                    files[path.name] = fingerprint(path)
            except OSError:
                continue
        with self.queue.connect() as db:
            known = {r["name"]: tuple(r)[1:] for r in db.execute("SELECT name,size,mtime,ctime FROM scans")}
            for name in known.keys() - files.keys():
                db.execute("DELETE FROM scans WHERE name=?", (name,))
        self.observed = {name: value for name, value in self.observed.items() if name in files}
        self.non_pdfs = {name: value for name, value in self.non_pdfs.items() if name in files}
        for name, version in files.items():
            if stop():
                return
            if known.get(name) == version or self.non_pdfs.get(name) == version:
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
                        self.non_pdfs[name] = version
                        continue
                    data = head + src.read()
                if fingerprint(path) != version:
                    continue
            except OSError:
                continue
            digest = hashlib.sha256(data).hexdigest()
            with self.queue.connect() as db:
                duplicate = db.execute("SELECT finding,status FROM scans WHERE digest=? LIMIT 1", (digest,)).fetchone()
                filed = db.execute("SELECT completed FROM publications WHERE digest=?", (digest,)).fetchone()
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
            if filed and filed["completed"]:
                status = "Filed"
            # A long OCR pass must not replace a newer scan or a cashier's decision.
            try:
                if fingerprint(path) != version:
                    continue
            except OSError:
                continue
            with self.queue.connect() as db:
                db.execute("""INSERT INTO scans VALUES(?,?,?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET
                    size=excluded.size,mtime=excluded.mtime,ctime=excluded.ctime,digest=excluded.digest,
                    status=CASE WHEN scans.digest=excluded.digest THEN scans.status ELSE excluded.status END,
                    finding=excluded.finding""", (name, *version, digest, status, info))
