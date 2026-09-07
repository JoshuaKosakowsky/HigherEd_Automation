from __future__ import annotations

import json
import logging
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.gui.models import (
    WorkflowContext,
    WorkflowDefinition,
    WorkflowMode,
    WorkflowResult,
)
from app.gui.main import build_review_login
from app.gui.services.execution import WorkflowExecutor, friendly_error_message
from app.gui.services.access import (
    filter_workflows_for_view,
    get_current_login,
    load_access_configuration,
)
from app.gui.services.drag_drop import parse_dropped_files, register_file_drop
from app.gui.services.population_testing import run_population_testing
from app.gui.services.textbook_brokers import run_textbook_brokers
from app.gui import theme
from app.gui.workflow_registry import get_workflow, get_workflows
from shared.banner.term import get_banner_term
from shared.user_settings import (
    get_automation_user_first_name,
    get_user_settings_path,
)


class WorkflowRegistryTests(unittest.TestCase):
    def test_registry_ids_are_unique_and_initial_workflows_are_registered(self) -> None:
        workflows = get_workflows()
        ids = [workflow.workflow_id for workflow in workflows]

        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(
            get_workflow("population_testing").name,
            "Student Testing Population",
        )
        self.assertEqual(get_workflow("textbook_brokers").name, "Textbook Brokers")

    def test_test_is_default_when_a_workflow_supports_both_modes(self) -> None:
        definition = WorkflowDefinition(
            workflow_id="mode_test",
            name="Mode Test",
            description="Test fixture",
            category="Testing",
            runner=lambda context: WorkflowResult(True, "done"),
            supported_modes=(WorkflowMode.PRODUCTION, WorkflowMode.TEST),
        )

        self.assertEqual(definition.default_mode, WorkflowMode.TEST)


class GuiBrandAndUserTests(unittest.TestCase):
    def test_theme_uses_official_mines_digital_colors(self) -> None:
        self.assertEqual(theme.DARK_BLUE, "#21314D")
        self.assertEqual(theme.BLASTER_BLUE, "#09396C")
        self.assertEqual(theme.LIGHT_BLUE, "#879EC3")
        self.assertEqual(theme.COLORADO_RED, "#CC4628")
        self.assertEqual(theme.PALE_BLUE, "#CFDCE9")
        self.assertEqual(theme.LIGHT_GRAY, "#AEB3B8")
        self.assertEqual(theme.DARK_GRAY, "#75757D")

    def test_user_settings_path_matches_powershell_setup_location(self) -> None:
        path = get_user_settings_path({"LOCALAPPDATA": "C:/Synthetic/AppData/Local"})

        self.assertEqual(
            path,
            Path("C:/Synthetic/AppData/Local") / "HigherEdAutomation"
            / "user-settings.json",
        )

    def test_first_name_reads_powershell_json_with_utf8_bom(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings_path = Path(directory) / "user-settings.json"
            payload = {
                "SchemaVersion": 1,
                "DisplayName": "Jordan Example",
                "Initials": "JE",
            }
            settings_path.write_text(
                "\ufeff" + json.dumps(payload),
                encoding="utf-8",
            )

            self.assertEqual(
                get_automation_user_first_name(settings_path),
                "Jordan",
            )

    def test_first_name_defaults_when_settings_are_missing_or_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings_path = Path(directory) / "missing.json"
            self.assertEqual(get_automation_user_first_name(settings_path), "User")

            settings_path.write_text("not valid json", encoding="utf-8")
            self.assertEqual(get_automation_user_first_name(settings_path), "User")


class WorkflowAccessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.config_path = Path(self.temporary_directory.name) / "gui_access.json"
        self.config_path.write_text(
            json.dumps(
                {
                    "schemaVersion": 2,
                    "users": {
                        "M00000001": {
                            "displayName": "Admin Example",
                            "jobTitle": "Cashier",
                            "view": "administrator",
                        },
                        "ANALYST1": {
                            "displayName": "Analyst Example",
                            "jobTitle": "AR Analyst",
                            "view": "analyst",
                        },
                        "CASHIER1": {
                            "displayName": "Cashier Example",
                            "jobTitle": "Cashier",
                            "view": "cashier",
                        },
                    },
                    "views": {
                        "administrator": {"workflows": ["*"]},
                        "analyst": {"workflows": []},
                        "cashier": {"workflows": []},
                    },
                }
            ),
            encoding="utf-8",
        )

    def visible_ids(self, login: str) -> set[str]:
        configuration = load_access_configuration(self.config_path)
        profile = configuration.profile_for_login(login)
        return {
            workflow.workflow_id
            for workflow in filter_workflows_for_view(
                get_workflows(),
                configuration,
                profile.view if profile is not None else None,
            )
        }

    def test_administrator_sees_every_registered_workflow(self) -> None:
        self.assertEqual(
            self.visible_ids("m00000001"),
            {workflow.workflow_id for workflow in get_workflows()},
        )

    def test_staff_have_no_workflows_until_explicitly_assigned(self) -> None:
        self.assertEqual(self.visible_ids("ANALYST1"), set())
        self.assertEqual(self.visible_ids("CASHIER1"), set())

    def test_unassigned_user_sees_no_workflows(self) -> None:
        self.assertEqual(self.visible_ids("UNASSIGNED1"), set())

    def test_job_title_does_not_determine_view(self) -> None:
        configuration = load_access_configuration(self.config_path)
        profile = configuration.profile_for_login("M00000001")

        self.assertIsNotNone(profile)
        self.assertEqual(profile.job_title, "Cashier")
        self.assertEqual(profile.view, "administrator")

    def test_windows_login_prefers_username_environment_value(self) -> None:
        self.assertEqual(
            get_current_login({"USERNAME": "M00000001", "USER": "fallback"}),
            "M00000001",
        )


class FileDropTests(unittest.TestCase):
    def test_drop_parser_preserves_multiple_paths_with_spaces(self) -> None:
        widget = SimpleNamespace(tk=Mock())
        widget.tk.splitlist.return_value = (
            "C:/Input Files/finaid_one.csv",
            "C:/Input Files/ia_two.csv",
        )

        paths = parse_dropped_files(widget, "tcl encoded file list")

        self.assertEqual(
            paths,
            (
                Path("C:/Input Files/finaid_one.csv"),
                Path("C:/Input Files/ia_two.csv"),
            ),
        )
        widget.tk.splitlist.assert_called_once_with("tcl encoded file list")

    def test_missing_optional_dependency_preserves_path_and_browse_mode(self) -> None:
        widget = Mock()

        with patch("app.gui.services.drag_drop.DND_FILES", None):
            registered = register_file_drop(widget, Mock())

        self.assertFalse(registered)
        widget.drop_target_register.assert_not_called()


class MacReviewIdentityTests(unittest.TestCase):
    def test_non_windows_review_identity_uses_configured_login(self) -> None:
        login = build_review_login("M00000001", platform="darwin")

        self.assertEqual(login, "M00000001")

    def test_windows_staff_launch_cannot_override_identity(self) -> None:
        with self.assertRaisesRegex(ValueError, "not available on Windows"):
            build_review_login("M00000001", platform="win32")


class BannerTermTests(unittest.TestCase):
    def test_gui_current_term_uses_shared_institution_configuration(self) -> None:
        term = get_banner_term(date(2026, 9, 6))

        self.assertEqual(term.code, "202680")
        self.assertEqual(term.name, "Fall 2026")

class PopulationTestingAdapterTests(unittest.TestCase):
    def test_adapter_builds_existing_pipeline_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.xlsx"
            source.touch()
            output = root / "output.xlsx"
            context = WorkflowContext(
                workflow_id="population_testing",
                parameters={
                    "input_file": source,
                    "output_file": output,
                    "sample_percent": 30,
                    "staff_names": ("Analyst One", "Analyst Two"),
                },
            )

            with patch(
                "app.gui.services.population_testing.run_population_testing_pipeline",
                return_value=output,
            ) as pipeline:
                result = run_population_testing(context)

            config = pipeline.call_args.args[0]
            self.assertEqual(config.input_file, source)
            self.assertEqual(config.output_file, output)
            self.assertEqual(config.sample_fraction, 0.3)
            self.assertEqual(config.staff_names, ("Analyst One", "Analyst Two"))
            self.assertEqual(result.output_path, output)

    def test_adapter_refuses_to_overwrite_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.xlsx"
            source.touch()
            context = WorkflowContext(
                workflow_id="population_testing",
                parameters={
                    "input_file": source,
                    "output_file": source,
                    "sample_percent": 25,
                    "staff_names": ("Analyst",),
                },
            )

            with self.assertRaisesRegex(ValueError, "different from the source"):
                run_population_testing(context)


class TextbookBrokersAdapterTests(unittest.TestCase):
    def test_adapter_runs_proven_local_transformation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "finaid_review.csv"
            source.write_text(
                "ignored,ignored,900000001,BKFA,ignored,125.50\n",
                encoding="utf-8",
            )
            output = root / "TSPLOAD.csv"
            context = WorkflowContext(
                workflow_id="textbook_brokers",
                parameters={
                    "term_code": "202680",
                    "source_files": (source,),
                    "output_file": output,
                },
            )

            result = run_textbook_brokers(context)

            self.assertTrue(result.success)
            self.assertEqual(result.output_path, output)
            self.assertIn("1 file(s)", result.message)
            self.assertTrue(output.is_file())


class WorkflowExecutorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.log_path = Path(self.temporary_directory.name) / "gui.log"
        self.logger = logging.getLogger(f"gui-test-{id(self)}")
        self.logger.addHandler(logging.NullHandler())

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_worker_returns_success_result(self) -> None:
        definition = WorkflowDefinition(
            workflow_id="success",
            name="Success",
            description="Test fixture",
            category="Testing",
            runner=lambda context: WorkflowResult(True, "Completed"),
        )
        executor = WorkflowExecutor(self.logger, self.log_path)

        result = executor.run_async(
            definition,
            WorkflowContext("success", {}),
        ).get(timeout=2)

        self.assertTrue(result.success)
        self.assertEqual(result.log_path, self.log_path)
        self.assertFalse(executor.is_running)

    def test_worker_hides_unexpected_exception_details(self) -> None:
        def fail(context: WorkflowContext) -> WorkflowResult:
            raise RuntimeError("internal-only detail")

        definition = WorkflowDefinition(
            workflow_id="failure",
            name="Failure",
            description="Test fixture",
            category="Testing",
            runner=fail,
        )
        executor = WorkflowExecutor(self.logger, self.log_path)

        result = executor.run_async(
            definition,
            WorkflowContext("failure", {}),
        ).get(timeout=2)

        self.assertFalse(result.success)
        self.assertNotIn("internal-only detail", result.message)
        self.assertIn("could not be completed", result.message)

    def test_permission_error_has_actionable_staff_message(self) -> None:
        message = friendly_error_message(PermissionError("technical path"))

        self.assertIn("Close it in Excel", message)
        self.assertNotIn("technical path", message)


class GuiPowerShellContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        project_root = Path(__file__).resolve().parents[2]
        cls.launcher = (project_root / "launcher" / "run_gui.ps1").read_text(
            encoding="utf-8"
        )
        cls.shortcut = (
            project_root / "powershell" / "gui" / "install_desktop_shortcut.ps1"
        ).read_text(encoding="utf-8")

    def test_launcher_uses_repository_windowed_python(self) -> None:
        self.assertIn('.venv\\Scripts\\pythonw.exe', self.launcher)
        self.assertIn('-m", "app.gui.main', self.launcher)
        self.assertIn("-WorkingDirectory $projectRoot", self.launcher)

    def test_shortcut_uses_hidden_powershell_and_gui_launcher(self) -> None:
        self.assertIn("Mines Bursar Automation.lnk", self.shortcut)
        self.assertIn("-WindowStyle Hidden", self.shortcut)
        self.assertIn("launcher\\run_gui.ps1", self.shortcut)

    def test_setup_verifies_native_file_drop_dependency(self) -> None:
        project_root = Path(__file__).resolve().parents[2]
        setup = (project_root / "setup.ps1").read_text(encoding="utf-8")
        requirements = (project_root / "requirements.txt").read_text(encoding="utf-8")

        self.assertIn("import tkinterdnd2", setup)
        self.assertIn("tkinterdnd2==0.6.1", requirements)


if __name__ == "__main__":
    unittest.main()
