"""Administrator page for maintaining GUI users and view assignments."""

from __future__ import annotations

import tkinter as tk
from dataclasses import replace
from tkinter import messagebox, simpledialog, ttk
from typing import Callable

from app.gui.services.access import (
    AccessConfiguration,
    AccessConfigurationError,
    UserAccessProfile,
    create_owner_protection,
    save_access_configuration,
)


class AccessManagementPage(ttk.Frame):
    def __init__(
        self,
        parent,
        *,
        configuration: AccessConfiguration,
        config_path,
        current_login: str,
        go_home: Callable[[], None],
        policy_saved: Callable[[AccessConfiguration], None],
    ) -> None:
        super().__init__(parent, style="App.TFrame", padding=(36, 28))
        self.configuration = configuration
        self.config_path = config_path
        self.current_login = current_login
        self.go_home = go_home
        self.policy_saved = policy_saved
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        ttk.Label(self, text="Manage staff access", style="PageTitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            self,
            text=(
                "Assign each Windows login to a view. Job titles are descriptive "
                "and never grant access. Revoked users remain in the history but cannot sign in."
            ),
            style="Body.TLabel",
            wraplength=780,
            justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(4, 18))

        toolbar = ttk.Frame(self, style="App.TFrame")
        toolbar.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        ttk.Button(toolbar, text="Add user", style="Primary.TButton", command=self._add).pack(side="left")
        ttk.Button(toolbar, text="Edit selected", command=self._edit).pack(side="left", padx=(8, 0))
        ttk.Button(toolbar, text="Revoke / restore", command=self._toggle_active).pack(side="left", padx=(8, 0))
        ttk.Button(toolbar, text="View permissions", command=self._edit_view).pack(side="left", padx=(8, 0))
        ttk.Button(toolbar, text="Owner password", command=self._set_owner_password).pack(side="left", padx=(8, 0))

        columns = ("login", "name", "title", "view", "status", "owner")
        self.table = ttk.Treeview(self, columns=columns, show="headings", selectmode="browse")
        headings = {
            "login": "Windows login", "name": "Name", "title": "Job title",
            "view": "View", "status": "Status", "owner": "Owner",
        }
        widths = {"login": 120, "name": 130, "title": 170, "view": 110, "status": 80, "owner": 60}
        for column in columns:
            self.table.heading(column, text=headings[column])
            self.table.column(column, width=widths[column], minwidth=55)
        self.table.grid(row=3, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.table.yview)
        scrollbar.grid(row=3, column=1, sticky="ns")
        self.table.configure(yscrollcommand=scrollbar.set)
        self.table.bind("<Double-1>", lambda _event: self._edit())

        footer = ttk.Frame(self, style="App.TFrame")
        footer.grid(row=4, column=0, sticky="ew", pady=(16, 0))
        ttk.Button(footer, text="Back", command=go_home).pack(side="left")
        self.status = ttk.Label(footer, text="", style="Muted.TLabel")
        self.status.pack(side="right")
        self._refresh()

    def _refresh(self) -> None:
        selected = self.table.selection()
        selected_key = selected[0] if selected else None
        self.table.delete(*self.table.get_children())
        owner_key = self.configuration.owner_login.casefold() if self.configuration.owner_login else None
        for key, profile in sorted(self.configuration.users.items()):
            self.table.insert(
                "", "end", iid=key,
                values=(
                    profile.login, profile.display_name, profile.job_title,
                    profile.view.title(), "Active" if profile.active else "Revoked",
                    "Yes" if key == owner_key else "",
                ),
            )
        if selected_key in self.configuration.users:
            self.table.selection_set(selected_key)
        self.status.configure(
            text=(
                f"Last updated by {self.configuration.updated_by}"
                if self.configuration.updated_by else "Owner password not established yet"
            )
        )

    def _selected(self) -> tuple[str, UserAccessProfile] | None:
        selected = self.table.selection()
        if not selected:
            messagebox.showinfo("Select a user", "Select a staff profile first.", parent=self)
            return None
        key = selected[0]
        return key, self.configuration.users[key]

    def _profile_dialog(self, title: str, profile: UserAccessProfile | None = None) -> UserAccessProfile | None:
        login = profile.login if profile else simpledialog.askstring(
            title, "Windows login (M number or account name):", parent=self
        )
        if login is None:
            return None
        display_name = simpledialog.askstring(
            title, "Display name:", initialvalue=profile.display_name if profile else "", parent=self
        )
        if display_name is None:
            return None
        job_title = simpledialog.askstring(
            title, "Job title:", initialvalue=profile.job_title if profile else "", parent=self
        )
        if job_title is None:
            return None
        available = ", ".join(sorted(self.configuration.workflows_by_view))
        view = simpledialog.askstring(
            title, f"View ({available}):", initialvalue=profile.view if profile else "", parent=self
        )
        if view is None:
            return None
        login, display_name, job_title, view = (
            login.strip(), display_name.strip(), job_title.strip(), view.strip().casefold()
        )
        if not all((login, display_name, job_title)) or view not in self.configuration.workflows_by_view:
            messagebox.showerror("Invalid profile", "Complete every field and choose a listed view.", parent=self)
            return None
        return UserAccessProfile(login, display_name, job_title, view, profile.active if profile else True)

    def _save(self, updated: AccessConfiguration, *, owner_password: str | None = None) -> bool:
        try:
            saved = save_access_configuration(
                self.config_path, updated, actor_login=self.current_login,
                owner_password=owner_password,
            )
        except AccessConfigurationError as error:
            messagebox.showerror("Access was not changed", str(error), parent=self)
            return False
        self.configuration = saved
        self.policy_saved(saved)
        self._refresh()
        return True

    def _add(self) -> None:
        profile = self._profile_dialog("Add staff access")
        if profile is None:
            return
        key = profile.login.casefold()
        if key in self.configuration.users:
            messagebox.showerror("Login already exists", "Edit the existing profile instead.", parent=self)
            return
        users = dict(self.configuration.users)
        users[key] = profile
        self._save(replace(self.configuration, users=users))

    def _edit(self) -> None:
        selected = self._selected()
        if selected is None:
            return
        key, current = selected
        profile = self._profile_dialog("Edit staff access", current)
        if profile is None:
            return
        password = self._owner_password_if_needed(key)
        if password is False:
            return
        users = dict(self.configuration.users)
        users[key] = profile
        self._save(replace(self.configuration, users=users), owner_password=password or None)

    def _toggle_active(self) -> None:
        selected = self._selected()
        if selected is None:
            return
        key, current = selected
        action = "restore" if not current.active else "revoke"
        if not messagebox.askyesno(
            f"{action.title()} access", f"{action.title()} GUI access for {current.display_name}?", parent=self
        ):
            return
        password = self._owner_password_if_needed(key)
        if password is False:
            return
        users = dict(self.configuration.users)
        users[key] = replace(current, active=not current.active)
        self._save(replace(self.configuration, users=users), owner_password=password or None)

    def _owner_password_if_needed(self, key: str) -> str | bool | None:
        owner_key = self.configuration.owner_login.casefold() if self.configuration.owner_login else None
        if key != owner_key:
            return None
        if self.configuration.owner_protection is None:
            messagebox.showerror(
                "Set owner password first",
                "Use Owner password before changing the protected owner profile.",
                parent=self,
            )
            return False
        value = simpledialog.askstring("Protected owner", "Owner password:", show="*", parent=self)
        return value if value is not None else False

    def _set_owner_password(self) -> None:
        owner_key = self.configuration.owner_login.casefold() if self.configuration.owner_login else None
        if self.current_login.casefold() != owner_key:
            messagebox.showerror("Owner only", "Only the protected owner can change this password.", parent=self)
            return
        current_password = None
        if self.configuration.owner_protection is not None:
            current_password = simpledialog.askstring(
                "Change owner password", "Current owner password:", show="*", parent=self
            )
            if current_password is None:
                return
        first = simpledialog.askstring("Owner password", "New password (12+ characters):", show="*", parent=self)
        if first is None:
            return
        second = simpledialog.askstring("Owner password", "Confirm new password:", show="*", parent=self)
        if second is None:
            return
        if first != second:
            messagebox.showerror("Passwords do not match", "The owner password was not changed.", parent=self)
            return
        try:
            protection = create_owner_protection(first)
        except AccessConfigurationError as error:
            messagebox.showerror("Invalid password", str(error), parent=self)
            return
        if self._save(
            replace(self.configuration, owner_protection=protection),
            owner_password=current_password,
        ):
            messagebox.showinfo("Owner protected", "The owner password verifier was saved.", parent=self)

    def _edit_view(self) -> None:
        view = simpledialog.askstring(
            "View permissions",
            "View to edit (analyst or cashier):",
            parent=self,
        )
        if view is None:
            return
        view = view.strip().casefold()
        if view == "administrator":
            messagebox.showinfo("Administrator view", "Administrators always see every registered workflow.", parent=self)
            return
        if view not in self.configuration.workflows_by_view:
            messagebox.showerror("Unknown view", "Choose an existing non-administrator view.", parent=self)
            return
        from app.gui.workflow_registry import get_workflows

        window = tk.Toplevel(self)
        window.title(f"{view.title()} permissions")
        window.transient(self.winfo_toplevel())
        window.grab_set()
        body = ttk.Frame(window, style="App.TFrame", padding=24)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=f"{view.title()} workflows", style="PageTitle.TLabel").pack(anchor="w")
        selected = self.configuration.workflows_by_view[view]
        variables: dict[str, tk.BooleanVar] = {}
        for workflow in get_workflows():
            variable = tk.BooleanVar(value=workflow.workflow_id in selected)
            variables[workflow.workflow_id] = variable
            ttk.Checkbutton(body, text=workflow.name, variable=variable).pack(anchor="w", pady=(8, 0))

        def save_view() -> None:
            views = dict(self.configuration.workflows_by_view)
            views[view] = frozenset(key for key, value in variables.items() if value.get())
            if self._save(replace(self.configuration, workflows_by_view=views)):
                window.destroy()

        buttons = ttk.Frame(body, style="App.TFrame")
        buttons.pack(fill="x", pady=(20, 0))
        ttk.Button(buttons, text="Save", style="Primary.TButton", command=save_view).pack(side="left")
        ttk.Button(buttons, text="Cancel", command=window.destroy).pack(side="left", padx=(8, 0))
