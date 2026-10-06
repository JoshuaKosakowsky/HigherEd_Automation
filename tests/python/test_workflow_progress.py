"""Shared progress contracts and live subprocess telemetry using synthetic work."""

import concurrent.futures
import logging
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Event
import unittest

from app.gui.models import WorkflowContext, WorkflowDefinition, WorkflowResult
from app.gui.services.execution import WorkflowExecutor
from app.gui.services.process import _report_marker, run_process
from shared.progress import ProgressReporter, ProgressUpdate


class WorkflowProgressTests(unittest.TestCase):
    def test_unknown_empty_and_measured_work(self):
        self.assertIsNone(ProgressUpdate("Connecting").percent)
        self.assertEqual(ProgressUpdate("No rows", 0, 0).percent, 100)
        self.assertEqual(ProgressUpdate("Processing rows", 3, 8).percent, 37)
        for stage, completed, total in (("", None, None), ("Work", 1, None),
                                         ("Work", None, 1), ("Work", -1, 4),
                                         ("Work", 5, 4), ("Work", True, 4),
                                         ("Work", 1, 4.5)):
            with self.subTest(stage=stage, completed=completed, total=total):
                with self.assertRaises(ValueError):
                    ProgressUpdate(stage, completed, total)

    def test_reporter_coalesces_updates_and_contexts_do_not_share_progress(self):
        reporter = ProgressReporter()
        for index in range(10000):
            reporter.report("Processing", completed=index, total=10000)
        self.assertEqual(reporter.snapshot, ProgressUpdate("Processing", 9999, 10000))
        first = WorkflowContext("one", {})
        second = WorkflowContext("two", {})
        first.progress.report("First workflow")
        self.assertIsNone(second.progress.snapshot)

    def test_executor_reports_live_work_and_resets_for_next_run(self):
        entered, release = Event(), Event()

        def runner(context):
            context.progress.report("Calculating", completed=4, total=10)
            entered.set()
            release.wait(timeout=2)
            return WorkflowResult(True, "Done")

        executor = WorkflowExecutor(logging.getLogger("progress-tests"), Path("synthetic.log"))
        definition = WorkflowDefinition("example", "Example", "Synthetic", "Testing", runner)
        results = executor.run_async(definition, WorkflowContext("example", {}))
        try:
            self.assertTrue(entered.wait(timeout=2))
            self.assertEqual(executor.progress_snapshot, ProgressUpdate("Calculating", 4, 10))
        finally:
            release.set()
        self.assertTrue(results.get(timeout=2).success)
        entered.clear()
        release.clear()

        def next_runner(context):
            entered.set()
            release.wait(timeout=2)
            return WorkflowResult(True, "Done again")

        next_definition = WorkflowDefinition("other", "Other", "Synthetic", "Testing", next_runner)
        results = executor.run_async(next_definition, WorkflowContext("other", {}))
        try:
            self.assertTrue(entered.wait(timeout=2))
            self.assertEqual(executor.progress_snapshot, ProgressUpdate("Starting workflow"))
        finally:
            release.set()
        self.assertTrue(results.get(timeout=2).success)

    def test_only_valid_explicit_markers_update_progress(self):
        reporter = ProgressReporter()
        for line in ("ordinary log text", "HIGHERED_PROGRESS=not-json", "HIGHERED_PROGRESS=[]",
                     'HIGHERED_PROGRESS={"stage":"Work","completed":4,"total":2}'):
            _report_marker(line, reporter)
        self.assertIsNone(reporter.snapshot)
        _report_marker('HIGHERED_PROGRESS={"stage":"Transferring files","completed":2,"total":7}', reporter)
        self.assertEqual(reporter.snapshot, ProgressUpdate("Transferring files", 2, 7))

    def test_process_reports_before_exit_and_preserves_both_output_streams(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            release_file = root / "release"
            observed = Event()
            reporter = ProgressReporter(lambda update: observed.set())
            script = (
                "import pathlib, sys, time\n"
                "print('HIGHERED_PROGRESS={\"stage\":\"Live child work\",\"completed\":1,\"total\":3}', flush=True)\n"
                "print('synthetic diagnostic', file=sys.stderr, flush=True)\n"
                "while not pathlib.Path(sys.argv[1]).exists(): time.sleep(0.01)\n"
                "print('HIGHERED_OUTPUT_PATH=synthetic.csv', flush=True)\n"
            )
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                result = pool.submit(run_process, [sys.executable, "-u", "-c", script, str(release_file)],
                                     cwd=root, timeout=5, creationflags=0, progress_reporter=reporter)
                try:
                    self.assertTrue(observed.wait(timeout=2))
                    self.assertFalse(result.done())
                    self.assertEqual(reporter.snapshot, ProgressUpdate("Live child work", 1, 3))
                finally:
                    release_file.touch()
                completed = result.result(timeout=3)
            self.assertEqual(completed.returncode, 0)
            self.assertIn("HIGHERED_OUTPUT_PATH=synthetic.csv", completed.stdout)
            self.assertIn("synthetic diagnostic", completed.stderr)

    def test_process_timeout_still_stops_the_launcher(self):
        with TemporaryDirectory() as directory:
            with self.assertRaises(subprocess.TimeoutExpired):
                run_process([sys.executable, "-c", "import time; time.sleep(5)"],
                            cwd=Path(directory), timeout=1, creationflags=0,
                            progress_reporter=ProgressReporter())

    def test_process_drains_large_output_and_keeps_failure_exit_code(self):
        with TemporaryDirectory() as directory:
            script = "import sys; print('x' * 100000); print('y' * 100000, file=sys.stderr); sys.exit(7)"
            completed = run_process([sys.executable, "-c", script], cwd=Path(directory),
                                    timeout=5, creationflags=0, progress_reporter=ProgressReporter())
        self.assertEqual(completed.returncode, 7)
        self.assertEqual(len(completed.stdout.strip()), 100000)
        self.assertEqual(len(completed.stderr.strip()), 100000)


if __name__ == "__main__":
    unittest.main()
