"""Quiet per-user intake used by the review window and the optional sign-in task."""

import sys
import time

from PySide6.QtCore import QLockFile

from shared.mines_paths import get_papercut_scan_directory
from .intake import ScanIntake, ScanQueue, queue_path


def main() -> int:
    queue = ScanQueue(get_papercut_scan_directory(), queue_path())
    lock = QLockFile(str(queue.database.with_suffix(".watch.lock")))
    lock.setStaleLockTime(0)
    while not lock.tryLock(0):
        if lock.error() != QLockFile.LockError.LockFailedError:
            return 1
        time.sleep(5)
    intake = ScanIntake(queue)
    while True:
        try:
            intake.poll()
        except (FileNotFoundError, PermissionError):
            # A synced folder may be absent briefly at sign-in.
            pass
        time.sleep(3)


if __name__ == "__main__":
    sys.exit(main())
