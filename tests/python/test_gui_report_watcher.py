"""Verify the GUI calls the existing installer without registering real tasks."""

import subprocess
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.gui.models import WorkflowContext
from app.gui.services.report_watcher import PROJECT_ROOT, SETUP_SCRIPT, run_setup_report_watcher
from app.gui.services.access import AccessConfiguration, filter_workflows_for_view
from app.gui.workflow_registry import get_workflow, get_workflows


class ReportWatcherAdapterTests(unittest.TestCase):
    def setUp(self):
        self.context = WorkflowContext("setup_report_watcher", {})

    def test_workflow_is_assignable_but_not_automatically_granted(self):
        workflow = get_workflow("setup_report_watcher")
        self.assertEqual(workflow.parameters, ())
        configuration = AccessConfiguration({}, {"cashier": frozenset()})
        self.assertEqual(filter_workflows_for_view(get_workflows(), configuration, "cashier"), ())
        assigned = AccessConfiguration({}, {"cashier": frozenset({"setup_report_watcher"})})
        self.assertEqual(filter_workflows_for_view(get_workflows(), assigned, "cashier"), (workflow,))

    def test_mac_review_cannot_install_watcher(self):
        with patch("app.gui.services.report_watcher.sys.platform", "darwin"):
            with patch("app.gui.services.report_watcher.subprocess.run") as run:
                with self.assertRaisesRegex(ValueError, "Windows-only"):
                    run_setup_report_watcher(self.context)
                run.assert_not_called()

    def test_missing_setup_profile_blocks_installation(self):
        with patch("app.gui.services.report_watcher.sys.platform", "win32"):
            with patch("app.gui.services.report_watcher.read_automation_user_settings", return_value=None):
                with self.assertRaisesRegex(ValueError, "name and cashier initials"):
                    run_setup_report_watcher(self.context)

    def invoke(self, *, returncode=0, error=None):
        with (
            patch("app.gui.services.report_watcher.sys.platform", "win32"),
            patch("app.gui.services.report_watcher.read_automation_user_settings", return_value=Mock()),
            patch("app.gui.services.report_watcher.shutil.which", return_value="C:/Windows/powershell.exe"),
            patch("app.gui.services.report_watcher.subprocess.CREATE_NO_WINDOW", 0x08000000, create=True),
            patch("app.gui.services.report_watcher.subprocess.run",
                  return_value=subprocess.CompletedProcess([], returncode, "", ""),
                  side_effect=error) as run,
        ):
            result = run_setup_report_watcher(self.context)
            return result, run

    def test_installs_current_user_through_existing_script_without_shell_or_elevation(self):
        result, run = self.invoke()
        self.assertTrue(result.success)
        self.assertEqual(run.call_args.args[0], [
            "C:/Windows/powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive",
            "-File", str(SETUP_SCRIPT),
        ])
        self.assertEqual(run.call_args.kwargs["cwd"], PROJECT_ROOT)
        self.assertNotIn("shell", run.call_args.kwargs)
        self.assertEqual(run.call_args.kwargs["creationflags"], 0x08000000)
        self.assertEqual(run.call_args.kwargs["timeout"], 120)
        self.assertEqual(SETUP_SCRIPT, PROJECT_ROOT / "setup" / "setup_report_filing_watcher.ps1")

    def test_failed_installer_does_not_report_success(self):
        result, _ = self.invoke(returncode=1)
        self.assertFalse(result.success)
        self.assertIn("GUI log folder", result.message)

    def test_timeout_reports_possible_partial_installation(self):
        result, _ = self.invoke(error=subprocess.TimeoutExpired("powershell", 120))
        self.assertFalse(result.success)
        self.assertIn("partially completed", result.message)
