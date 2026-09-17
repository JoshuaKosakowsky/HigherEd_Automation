"""Main entry point for Mines Bursar Automation."""

from __future__ import annotations

import argparse
import re
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
try:
    from tkinterdnd2 import TkinterDnD
except ModuleNotFoundError:
    TkinterDnD = None

from app.gui import APP_NAME, APP_VERSION
from app.gui.models import WorkflowDefinition
from app.gui.pages.home import HomePage
from app.gui.pages.access_management import AccessManagementPage
from app.gui.pages.workflow_detail import WorkflowDetailPage
from app.gui.services.execution import WorkflowExecutor
from app.gui.services.access import (
    AccessConfiguration,
    AccessConfigurationError,
    create_shared_access_configuration,
    filter_workflows_for_view,
    get_current_login,
    load_access_configuration,
    upgrade_legacy_configuration,
)
from app.gui.services.logging_service import configure_gui_logging
from app.gui.theme import DARK_BLUE, apply_theme
from app.gui.workflow_registry import get_workflows
from shared.user_settings import (
    DEFAULT_FIRST_NAME,
    read_automation_user_settings,
)
from shared.mines_paths import get_shared_gui_access_path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOCAL_REVIEW_ACCESS_CONFIG_PATH = PROJECT_ROOT / "config" / "gui_access.json"


class AutomationApplication:
    def __init__(
        self,
        root: tk.Tk,
        *,
        user_login_override: str | None = None,
        access_config_path: Path | None = None,
    ) -> None:
        self.root = root
        logging = configure_gui_logging(PROJECT_ROOT)
        self.logger = logging.logger
        self.executor = WorkflowExecutor(logging.logger, logging.path)
        self.current_page: ttk.Frame | None = None
        user_settings = read_automation_user_settings()
        self.user_first_name = (
            user_settings.first_name
            if user_settings is not None
            else DEFAULT_FIRST_NAME
        )
        user_login = user_login_override or get_current_login()
        self.user_login = user_login or ""
        self.access_config_path = access_config_path or get_shared_gui_access_path()
        self.access_configuration: AccessConfiguration | None = None
        profile = None
        try:
            access_configuration = self._load_access_configuration()
            self.access_configuration = access_configuration
            profile = access_configuration.profile_for_login(user_login)
            self.visible_workflows = filter_workflows_for_view(
                get_workflows(),
                access_configuration,
                profile.view if profile is not None else None,
            )
        except AccessConfigurationError:
            self.logger.exception("GUI access configuration is invalid")
            self.visible_workflows = ()
        self.profile_description = (
            f"{profile.job_title}  •  {profile.view.title()} view"
            if profile is not None
            else None
        )
        self.profile = profile
        self.logger.info(
            "Workflow access resolved: view=%s visible_workflows=%s",
            profile.view if profile is not None else "unassigned",
            [workflow.workflow_id for workflow in self.visible_workflows],
        )

        root.title(APP_NAME)
        root.geometry("960x760")
        root.minsize(820, 650)
        root.configure(background=DARK_BLUE)
        root.protocol("WM_DELETE_WINDOW", self._close)
        apply_theme(ttk.Style(root))

        header = ttk.Frame(root, style="Header.TFrame", padding=(30, 18))
        header.pack(fill="x")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text=APP_NAME, style="HeaderTitle.TLabel").grid(
            row=0,
            column=0,
            sticky="w",
        )
        ttk.Label(
            header,
            text=f"Bursar Office  •  Version {APP_VERSION}",
            style="HeaderMeta.TLabel",
        ).grid(row=0, column=1, sticky="e")

        self.content = ttk.Frame(root, style="App.TFrame")
        self.content.pack(fill="both", expand=True)
        self.show_home()
        self.logger.info("Application started: version=%s", APP_VERSION)

    def _show(self, page: ttk.Frame) -> None:
        if self.current_page is not None:
            self.current_page.destroy()
        self.current_page = page
        page.pack(fill="both", expand=True)

    def show_home(self) -> None:
        self._show(
            HomePage(
                self.content,
                self.visible_workflows,
                self.show_workflow,
                user_first_name=self.user_first_name,
                profile_description=self.profile_description,
                manage_access=(
                    self.show_access_management
                    if self.access_configuration is not None
                    and self.access_configuration.is_administrator(self.user_login)
                    and self.access_configuration.owner_login is not None
                    else None
                ),
            )
        )

    def _load_access_configuration(self) -> AccessConfiguration:
        if self.access_config_path.exists():
            return load_access_configuration(self.access_config_path)
        if sys.platform != "win32" or not LOCAL_REVIEW_ACCESS_CONFIG_PATH.exists():
            return load_access_configuration(self.access_config_path)
        legacy = load_access_configuration(LOCAL_REVIEW_ACCESS_CONFIG_PATH)
        upgraded = upgrade_legacy_configuration(legacy, owner_login=self.user_login)
        self.logger.info(
            "Creating shared GUI access policy from the existing private configuration: %s",
            self.access_config_path,
        )
        return create_shared_access_configuration(
            self.access_config_path, upgraded, actor_login=self.user_login
        )

    def _apply_access_configuration(self, configuration: AccessConfiguration) -> None:
        self.access_configuration = configuration
        self.profile = configuration.profile_for_login(self.user_login)
        self.visible_workflows = filter_workflows_for_view(
            get_workflows(), configuration,
            self.profile.view if self.profile is not None else None,
        )
        self.profile_description = (
            f"{self.profile.job_title}  •  {self.profile.view.title()} view"
            if self.profile is not None else None
        )

    def show_access_management(self) -> None:
        if (
            self.access_configuration is None
            or not self.access_configuration.is_administrator(self.user_login)
        ):
            messagebox.showerror("Access denied", "Administrator access is required.", parent=self.root)
            return
        self._show(
            AccessManagementPage(
                self.content,
                configuration=self.access_configuration,
                config_path=self.access_config_path,
                current_login=self.user_login,
                go_home=self.show_home,
                policy_saved=self._apply_access_configuration,
            )
        )

    def show_workflow(self, definition: WorkflowDefinition) -> None:
        self.logger.info("Workflow selected: id=%s", definition.workflow_id)
        self._show(
            WorkflowDetailPage(
                self.content,
                definition,
                self.executor,
                self.show_home,
            )
        )

    def _close(self) -> None:
        if self.executor.is_running:
            messagebox.showwarning(
                "Process is still running",
                "Keep this window open until the process finishes.",
                parent=self.root,
            )
            return
        self.logger.info("Application closed")
        self.root.destroy()


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
    try:
        review_login = build_review_login(args.review_as)
        access_config_path = resolve_access_config_path(review_login, args.access_config)
        root = TkinterDnD.Tk() if TkinterDnD is not None else tk.Tk()
        AutomationApplication(
            root,
            user_login_override=review_login,
            access_config_path=access_config_path,
        )
        root.mainloop()
    except Exception:
        logging.logger.exception("Application startup failed")
        try:
            messagebox.showerror(
                f"{APP_NAME} could not start",
                f"Technical details were written to:\n{logging.path}",
            )
        except tk.TclError:
            pass
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
