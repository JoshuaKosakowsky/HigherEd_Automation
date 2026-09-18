"""Desktop entry point for Mines Bursar Automation (Qt Widgets)."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QMainWindow, QMessageBox,
    QStackedWidget, QVBoxLayout, QWidget,
)

from app.gui import APP_NAME, APP_VERSION
from app.gui.models import WorkflowDefinition
from app.gui.pages.access_management import AccessManagementPage
from app.gui.pages.home import HomePage
from app.gui.pages.workflow_detail import WorkflowDetailPage
from app.gui.services.access import (
    AccessConfiguration, AccessConfigurationError, create_shared_access_configuration,
    filter_workflows_for_view, get_current_login, load_access_configuration,
    upgrade_legacy_configuration,
)
from app.gui.services.execution import WorkflowExecutor
from app.gui.services.logging_service import configure_gui_logging
from app.gui.services.system import open_path
from app.gui.theme import apply_theme, button, label
from app.gui.workflow_registry import get_workflows
from shared.mines_paths import MinesPathError, get_shared_gui_access_path
from shared.user_settings import DEFAULT_FIRST_NAME, read_automation_user_settings

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOCAL_REVIEW_ACCESS_CONFIG_PATH = PROJECT_ROOT / "config" / "gui_access.json"


class AutomationApplication(QMainWindow):
    def __init__(
        self, *, user_login_override: str | None = None,
        access_config_path: Path | None = None,
    ) -> None:
        super().__init__()
        logging = configure_gui_logging(PROJECT_ROOT)
        self.logger = logging.logger
        self.executor = WorkflowExecutor(logging.logger, logging.path)
        settings = read_automation_user_settings()
        self.user_first_name = settings.first_name if settings else DEFAULT_FIRST_NAME
        self.user_login = user_login_override or get_current_login() or ""
        self.access_config_path = access_config_path or get_shared_gui_access_path()
        self.access_configuration = None
        self.profile = None
        self.profile_description = None
        self.visible_workflows = ()
        self.access_error = None
        self.current_page = None
        self._busy = False
        self.setWindowTitle(APP_NAME)
        self.resize(1180, 820)
        self.setMinimumSize(900, 640)
        shell = QWidget()
        row = QHBoxLayout(shell)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(230)
        navigation = QVBoxLayout(self.sidebar)
        navigation.setContentsMargins(22, 30, 22, 22)
        navigation.setSpacing(12)
        navigation.addWidget(label("MINES", "brand"))
        navigation.addWidget(label("Bursar Automation", "sideTitle"))
        navigation.addWidget(label("COLORADO SCHOOL OF MINES", "institution"))
        navigation.addSpacing(32)
        self.home_button = button("Workflows", self.show_home, "nav")
        self.access_button = button("Staff access", self.show_access_management, "nav")
        for control in (self.home_button, self.access_button):
            control.setCheckable(True)
            navigation.addWidget(control)
        navigation.addStretch()
        self.identity = label("", wrap=True)
        navigation.addWidget(self.identity)
        if user_login_override:
            navigation.addWidget(label("LOCAL REVIEW", wrap=False))
        navigation.addWidget(button("Open logs", self._open_logs, "nav"))
        navigation.addWidget(button("About this app", self._about, "nav"))
        navigation.addWidget(label(f"Version {APP_VERSION}", wrap=False))
        row.addWidget(self.sidebar)
        self.content = QStackedWidget()
        row.addWidget(self.content, 1)
        self.setCentralWidget(shell)
        self._reload_access(bootstrap=True)
        self.show_home(reload=False)
        self.logger.info("Application started: version=%s", APP_VERSION)

    def _load_access_configuration(self, *, bootstrap: bool = False) -> AccessConfiguration:
        if self.access_config_path.exists():
            return load_access_configuration(self.access_config_path)
        if not bootstrap or sys.platform != "win32" or not LOCAL_REVIEW_ACCESS_CONFIG_PATH.exists():
            return load_access_configuration(self.access_config_path)
        legacy = load_access_configuration(LOCAL_REVIEW_ACCESS_CONFIG_PATH)
        # A previously designated owner must not change during migration.
        if not legacy.is_administrator(self.user_login):
            raise AccessConfigurationError("A configured administrator must initialize shared access.")
        upgraded = legacy if legacy.owner_login else upgrade_legacy_configuration(legacy, owner_login=self.user_login)
        return create_shared_access_configuration(
            self.access_config_path, upgraded, actor_login=self.user_login
        )

    def _reload_access(self, *, bootstrap: bool = False) -> bool:
        try:
            self._apply_access_configuration(self._load_access_configuration(bootstrap=bootstrap))
            return True
        except (AccessConfigurationError, MinesPathError, OSError):
            self.logger.exception("GUI access could not be loaded")
            self.access_configuration = None
            self.profile = None
            self.profile_description = None
            self.visible_workflows = ()
            self.access_error = "Access settings are unavailable. Check OneDrive synchronization or contact your administrator."
            self._update_navigation()
            return False

    def _apply_access_configuration(self, configuration: AccessConfiguration) -> None:
        profile = configuration.profile_for_login(self.user_login)
        workflows = filter_workflows_for_view(get_workflows(), configuration, profile.view if profile else None)
        self.access_configuration = configuration
        self.profile = profile
        self.visible_workflows = workflows
        self.profile_description = f"{profile.job_title}  •  {profile.view.title()} view" if profile else None
        self.access_error = None
        self._update_navigation()

    def _update_navigation(self) -> None:
        admin = bool(
            self.access_configuration
            and self.access_configuration.owner_login
            and self.access_configuration.is_administrator(self.user_login)
        )
        self.access_button.setVisible(admin)
        self.identity.setText(self.profile_description or "No view assigned")

    def _show(self, page: QWidget) -> None:
        previous = self.current_page
        self.current_page = page
        self.content.addWidget(page)
        self.content.setCurrentWidget(page)
        if previous is not None:
            self.content.removeWidget(previous)
            previous.deleteLater()

    def show_home(self, checked: bool = False, *, reload: bool = True) -> None:
        if self._busy or self.executor.is_running:
            return
        if reload:
            self._reload_access()
        self.home_button.setChecked(True)
        self.access_button.setChecked(False)
        self._show(HomePage(
            self.content, self.visible_workflows, self.show_workflow,
            user_first_name=self.user_first_name, profile_description=self.profile_description,
            access_error=self.access_error,
        ))

    def show_access_management(self) -> None:
        if self._busy or self.executor.is_running:
            return
        self._reload_access()
        if not self.access_configuration or not self.access_configuration.is_administrator(self.user_login):
            self.show_home(reload=False)
            return
        self.home_button.setChecked(False)
        self.access_button.setChecked(True)
        self._show(AccessManagementPage(
            self.content, configuration=self.access_configuration,
            config_path=self.access_config_path, current_login=self.user_login,
            go_home=self.show_home, policy_saved=self._apply_access_configuration,
        ))

    def _authorize_workflow(self, definition: WorkflowDefinition) -> bool:
        self._reload_access()
        if definition.workflow_id not in {item.workflow_id for item in self.visible_workflows}:
            QMessageBox.warning(self, "Workflow unavailable",
                                "Your current view does not have access to this workflow. Return to Workflows to refresh.")
            return False
        return True

    def show_workflow(self, definition: WorkflowDefinition) -> None:
        if self._busy or self.executor.is_running or not self._authorize_workflow(definition):
            return
        page = WorkflowDetailPage(
            self.content, definition, self.executor, self.show_home,
            authorize=lambda: self._authorize_workflow(definition),
        )
        page.busy_changed.connect(self._set_busy)
        self._show(page)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.home_button.setEnabled(not busy)
        self.access_button.setEnabled(not busy)

    def _open_logs(self) -> None:
        try:
            open_path(self.executor.log_directory)
        except OSError:
            QMessageBox.warning(self, "Logs unavailable", "The log folder could not be opened.")

    def _about(self) -> None:
        dialog = QMessageBox(self)
        dialog.setWindowTitle("About Mines Bursar Automation")
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText(f"{APP_NAME}\nVersion {APP_VERSION}")
        dialog.setInformativeText(
            "A local desktop workspace for Bursar Office workflows.\n\n"
            "Uses Qt and PySide6 Essentials under LGPLv3. "
            "Licensing and source information: app/gui/THIRD_PARTY_NOTICES.md"
        )
        qt_button = dialog.addButton("About Qt", QMessageBox.ButtonRole.HelpRole)
        qt_button.clicked.connect(lambda: QMessageBox.aboutQt(self))
        dialog.addButton(QMessageBox.StandardButton.Close)
        dialog.exec()

    def closeEvent(self, event) -> None:
        if self._busy or self.executor.is_running:
            QMessageBox.warning(self, "Workflow is running", "Keep this window open until the workflow finishes.")
            event.ignore()
            return
        self.logger.info("Application closed")
        event.accept()


def parse_args(arguments: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=f"Open {APP_NAME}.")
    parser.add_argument(
        "--review-as",
        metavar="WINDOWS_LOGIN",
        help=(
            "Preview a configured Windows login on macOS/Linux. This option is "
            "disabled on Windows staff installations."
        ),
    )
    parser.add_argument(
        "--access-config",
        type=Path,
        metavar="PATH",
        help="Use a local access-policy file for non-Windows GUI review.",
    )
    return parser.parse_args(arguments)


def build_review_login(
    login: str | None,
    *,
    platform: str = sys.platform,
) -> str | None:
    if login is None:
        return None
    if platform == "win32":
        raise ValueError("--review-as is not available on Windows.")
    cleaned_login = login.strip()
    if (
        not cleaned_login
        or len(cleaned_login) > 150
        or re.fullmatch(r"[A-Za-z0-9._@\\-]+", cleaned_login) is None
    ):
        raise ValueError("The review Windows login is invalid.")
    return cleaned_login


def resolve_access_config_path(
    review_login: str | None,
    override: Path | None,
    *,
    platform: str = sys.platform,
) -> Path:
    if platform == "win32":
        if override is not None:
            raise ValueError("--access-config is not available on Windows.")
        return get_shared_gui_access_path()
    if override is not None:
        if review_login is None:
            raise ValueError("--access-config requires --review-as.")
        return override.expanduser().resolve()
    if review_login is not None:
        return LOCAL_REVIEW_ACCESS_CONFIG_PATH
    return get_shared_gui_access_path()


def main(arguments: list[str] | None = None) -> int:
    args = parse_args(arguments)
    logging = configure_gui_logging(PROJECT_ROOT)
    application = QApplication.instance() or QApplication([sys.argv[0]])
    application.setApplicationName(APP_NAME)
    application.setApplicationVersion(APP_VERSION)
    apply_theme(application)
    try:
        review_login = build_review_login(args.review_as)
        path = resolve_access_config_path(review_login, args.access_config)
        window = AutomationApplication(user_login_override=review_login, access_config_path=path)
        window.show()
        return application.exec()
    except Exception:
        logging.logger.exception("Application startup failed")
        QMessageBox.critical(None, f"{APP_NAME} could not start",
                             f"Technical details were written to:\n{logging.path}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
