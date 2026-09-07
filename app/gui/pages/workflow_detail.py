"""Generic detail page generated from workflow metadata."""

from __future__ import annotations

import queue
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable

from app.gui.models import (
    ParameterDefinition,
    ParameterKind,
    WorkflowContext,
    WorkflowDefinition,
    WorkflowMode,
    WorkflowResult,
)
from app.gui.services.execution import WorkflowExecutor
from app.gui.services.drag_drop import is_file_drop_available, register_file_drop
from app.gui.services.system import open_path
from app.gui.theme import DARK_BLUE, PALE_BLUE, PAGE, WHITE


class WorkflowDetailPage(ttk.Frame):
    def __init__(
        self,
        parent,
        definition: WorkflowDefinition,
        executor: WorkflowExecutor,
        go_home: Callable[[], None],
    ) -> None:
        super().__init__(parent, style="App.TFrame")
        self.definition = definition
        self.executor = executor
        self.go_home = go_home
        self.variables: dict[str, tk.StringVar] = {}
        self.name_lists: dict[str, tk.Text] = {}
        self.multi_file_inputs: dict[str, tk.Text] = {}
        self.result_queue: queue.Queue[WorkflowResult] | None = None
        self.output_path: Path | None = None

        self.canvas = tk.Canvas(
            self,
            background=PAGE,
            borderwidth=0,
            highlightthickness=0,
        )
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.configure(yscrollcommand=scrollbar.set)

        self.body = ttk.Frame(
            self.canvas,
            style="App.TFrame",
            padding=(36, 24),
        )
        self.body.columnconfigure(0, weight=1)
        self.body_window = self.canvas.create_window(
            (0, 0),
            window=self.body,
            anchor="nw",
        )
        self.body.bind("<Configure>", self._update_scroll_region)
        self.canvas.bind("<Configure>", self._resize_body)

        self._build_header()
        self._build_form()
        self._build_actions()

    def _update_scroll_region(self, _event=None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _resize_body(self, event) -> None:
        self.canvas.itemconfigure(self.body_window, width=event.width)

    def _build_header(self) -> None:
        self.back_button = ttk.Button(
            self.body,
            text="← Back to Automation",
            style="Secondary.TButton",
            command=self.go_home,
        )
        self.back_button.grid(row=0, column=0, sticky="w")
        ttk.Label(
            self.body,
            text=self.definition.name,
            style="PageTitle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(20, 5))
        ttk.Label(
            self.body,
            text=self.definition.description,
            style="Body.TLabel",
            wraplength=760,
            justify="left",
        ).grid(row=2, column=0, sticky="w", pady=(0, 20))

    def _build_form(self) -> None:
        form = ttk.Frame(self.body, style="App.TFrame")
        form.grid(row=3, column=0, sticky="ew")
        form.columnconfigure(0, weight=1)

        row = 0
        for parameter in self.definition.parameters:
            ttk.Label(form, text=parameter.label, style="Field.TLabel").grid(
                row=row,
                column=0,
                sticky="w",
            )
            row += 1

            if parameter.kind == ParameterKind.NAME_LIST:
                list_frame = ttk.Frame(form, style="App.TFrame")
                list_frame.grid(row=row, column=0, sticky="ew")
                list_frame.columnconfigure(0, weight=1)
                text = tk.Text(
                    list_frame,
                    height=6,
                    wrap="word",
                    font=("Segoe UI", 10),
                    relief="solid",
                    borderwidth=1,
                    background=WHITE,
                    foreground=DARK_BLUE,
                    insertbackground=DARK_BLUE,
                )
                default_names = parameter.default or ()
                text.insert("1.0", "\n".join(str(name) for name in default_names))
                text.grid(row=0, column=0, sticky="ew")
                scrollbar = ttk.Scrollbar(
                    list_frame,
                    orient="vertical",
                    command=text.yview,
                )
                scrollbar.grid(row=0, column=1, sticky="ns")
                text.configure(yscrollcommand=scrollbar.set)
                self.name_lists[parameter.key] = text
            elif parameter.kind == ParameterKind.MULTI_INPUT_FILE:
                file_frame = ttk.Frame(form, style="App.TFrame")
                file_frame.grid(row=row, column=0, sticky="ew")
                file_frame.columnconfigure(0, weight=1)
                text = tk.Text(
                    file_frame,
                    height=4,
                    wrap="char",
                    font=("Segoe UI", 10),
                    relief="solid",
                    borderwidth=1,
                    background=PALE_BLUE,
                    foreground=DARK_BLUE,
                    insertbackground=DARK_BLUE,
                )
                text.grid(row=0, column=0, sticky="ew")
                scrollbar = ttk.Scrollbar(
                    file_frame,
                    orient="vertical",
                    command=text.yview,
                )
                scrollbar.grid(row=0, column=1, sticky="ns")
                text.configure(yscrollcommand=scrollbar.set)
                ttk.Button(
                    file_frame,
                    text="Browse…",
                    command=lambda item=parameter: self._browse(item),
                ).grid(row=0, column=2, padx=(8, 0), sticky="n")
                self.multi_file_inputs[parameter.key] = text
                register_file_drop(
                    text,
                    lambda paths, item=parameter: self._accept_dropped_files(
                        item,
                        paths,
                    ),
                )
            else:
                value = tk.StringVar(value=str(parameter.default))
                self.variables[parameter.key] = value
                field_row = ttk.Frame(form, style="App.TFrame")
                field_row.grid(row=row, column=0, sticky="ew")
                field_row.columnconfigure(0, weight=1)
                entry = ttk.Entry(field_row, textvariable=value)
                entry.grid(
                    row=0,
                    column=0,
                    sticky="ew",
                )
                if parameter.kind == ParameterKind.INPUT_FILE:
                    register_file_drop(
                        entry,
                        lambda paths, item=parameter: self._accept_dropped_files(
                            item,
                            paths,
                        ),
                    )
                if parameter.kind in {
                    ParameterKind.INPUT_FILE,
                    ParameterKind.OUTPUT_FILE,
                }:
                    ttk.Button(
                        field_row,
                        text="Browse…",
                        command=lambda item=parameter: self._browse(item),
                    ).grid(row=0, column=1, padx=(8, 0))
            row += 1

            if parameter.help_text:
                help_text = parameter.help_text
                if (
                    parameter.kind
                    in {ParameterKind.INPUT_FILE, ParameterKind.MULTI_INPUT_FILE}
                    and not is_file_drop_available()
                ):
                    help_text += (
                        " File drop is unavailable in this Python environment; "
                        "path entry and Browse still work."
                    )
                ttk.Label(
                    form,
                    text=help_text,
                    style="Muted.TLabel",
                    wraplength=760,
                    justify="left",
                ).grid(row=row, column=0, sticky="w", pady=(4, 14))
                row += 1

        self.mode_value = tk.StringVar(
            value=(self.definition.default_mode or "").value
            if self.definition.default_mode
            else ""
        )
        if self.definition.supported_modes:
            ttk.Label(form, text="Mode", style="Field.TLabel").grid(
                row=row,
                column=0,
                sticky="w",
            )
            row += 1
            mode_row = ttk.Frame(form, style="App.TFrame")
            mode_row.grid(row=row, column=0, sticky="w")
            for column, mode in enumerate(self.definition.supported_modes):
                label = "Test" if mode == WorkflowMode.TEST else "Production"
                ttk.Radiobutton(
                    mode_row,
                    text=label,
                    value=mode.value,
                    variable=self.mode_value,
                    command=self._update_production_warning,
                ).grid(row=0, column=column, padx=(0, 18))
            row += 1
            self.production_warning = ttk.Label(
                form,
                text=f"PRODUCTION MODE\n{self.definition.production_warning}",
                style="Production.TLabel",
            )
            self.production_warning.grid(row=row, column=0, sticky="ew", pady=(8, 14))
            row += 1
            self._update_production_warning()

    def _build_actions(self) -> None:
        action_row = ttk.Frame(self.body, style="App.TFrame")
        action_row.grid(row=4, column=0, sticky="ew", pady=(10, 0))

        self.run_button = ttk.Button(
            action_row,
            text="Run Process",
            style="Primary.TButton",
            command=self._run,
        )
        self.run_button.grid(row=0, column=0, sticky="w")

        self.progress = ttk.Progressbar(action_row, mode="indeterminate", length=180)
        self.progress.grid(row=0, column=1, padx=(16, 0))
        self.progress.grid_remove()

        self.status_label = ttk.Label(
            self.body,
            text="Ready to run.",
            style="Muted.TLabel",
            wraplength=760,
            justify="left",
        )
        self.status_label.grid(row=5, column=0, sticky="w", pady=(18, 6))

        support_row = ttk.Frame(self.body, style="App.TFrame")
        support_row.grid(row=6, column=0, sticky="w")
        self.output_button = ttk.Button(
            support_row,
            text="Open Result",
            command=self._open_output,
        )
        self.output_button.grid(row=0, column=0, padx=(0, 8))
        self.output_button.grid_remove()
        self.log_button = ttk.Button(
            support_row,
            text="Open Log Folder",
            command=lambda: open_path(self.executor.log_directory),
        )
        self.log_button.grid(row=0, column=1)

    def _browse(self, parameter: ParameterDefinition) -> None:
        file_types = parameter.file_types or (("All files", "*.*"),)
        if parameter.kind == ParameterKind.MULTI_INPUT_FILE:
            selected_files = filedialog.askopenfilenames(
                title=parameter.label,
                initialdir=Path.cwd(),
                filetypes=file_types,
            )
            if selected_files:
                self._set_multi_file_paths(
                    parameter,
                    tuple(Path(path) for path in selected_files),
                )
            return

        current = Path(self.variables[parameter.key].get()).expanduser()
        initial_directory = current.parent if current.parent.exists() else Path.cwd()
        if parameter.kind == ParameterKind.INPUT_FILE:
            selected = filedialog.askopenfilename(
                title=parameter.label,
                initialdir=initial_directory,
                filetypes=file_types,
            )
        else:
            selected = filedialog.asksaveasfilename(
                title=parameter.label,
                initialdir=initial_directory,
                initialfile=current.name,
                filetypes=file_types,
                defaultextension=parameter.default_extension,
            )
        if selected:
            self.variables[parameter.key].set(selected)

    def _accept_dropped_files(
        self,
        parameter: ParameterDefinition,
        paths: tuple[Path, ...],
    ) -> None:
        files = tuple(path for path in paths if path.is_file())
        if not files:
            messagebox.showwarning(
                "No file selected",
                "Drop one or more files, not a folder.",
                parent=self,
            )
            return

        if parameter.kind == ParameterKind.INPUT_FILE:
            if len(files) != 1:
                messagebox.showwarning(
                    "Select one file",
                    f"{parameter.label} accepts one file at a time.",
                    parent=self,
                )
                return
            self.variables[parameter.key].set(str(files[0]))
            return

        self._set_multi_file_paths(parameter, files)

    def _set_multi_file_paths(
        self,
        parameter: ParameterDefinition,
        paths: tuple[Path, ...],
    ) -> None:
        text = self.multi_file_inputs[parameter.key]
        existing = [
            line.strip().strip('"')
            for line in text.get("1.0", "end").splitlines()
            if line.strip()
        ]
        existing_keys = {str(Path(line).expanduser().resolve()) for line in existing}
        for path in paths:
            key = str(path.expanduser().resolve())
            if key not in existing_keys:
                existing.append(str(path))
                existing_keys.add(key)
        text.delete("1.0", "end")
        text.insert("1.0", "\n".join(existing))

    def _update_production_warning(self) -> None:
        if not hasattr(self, "production_warning"):
            return
        if self.mode_value.get() == WorkflowMode.PRODUCTION.value:
            self.production_warning.grid()
        else:
            self.production_warning.grid_remove()

    def _parse_parameters(self) -> dict[str, Any]:
        parsed: dict[str, Any] = {}
        for parameter in self.definition.parameters:
            if parameter.kind == ParameterKind.NAME_LIST:
                raw_names = self.name_lists[parameter.key].get("1.0", "end")
                names = tuple(
                    name.strip()
                    for line in raw_names.splitlines()
                    for name in line.split(",")
                    if name.strip()
                )
                if parameter.required and not names:
                    raise ValueError(f"{parameter.label} is required.")
                if len(names) != len(set(names)):
                    raise ValueError(f"{parameter.label} must contain unique names.")
                parsed[parameter.key] = names
                continue

            if parameter.kind == ParameterKind.MULTI_INPUT_FILE:
                raw_paths = self.multi_file_inputs[parameter.key].get("1.0", "end")
                paths = tuple(
                    Path(line.strip().strip('"')).expanduser()
                    for line in raw_paths.splitlines()
                    if line.strip()
                )
                if parameter.required and not paths:
                    raise ValueError(f"{parameter.label} is required.")
                missing = next((path for path in paths if not path.is_file()), None)
                if missing is not None:
                    raise ValueError(f"Source file was not found: {missing}")
                resolved = [path.resolve() for path in paths]
                if len(resolved) != len(set(resolved)):
                    raise ValueError(f"{parameter.label} contains a duplicate path.")
                parsed[parameter.key] = paths
                continue

            raw_value = self.variables[parameter.key].get().strip()
            if parameter.required and not raw_value:
                raise ValueError(f"{parameter.label} is required.")

            if parameter.kind in {ParameterKind.INPUT_FILE, ParameterKind.OUTPUT_FILE}:
                path = Path(raw_value.strip('"')).expanduser()
                if parameter.kind == ParameterKind.INPUT_FILE and not path.is_file():
                    raise ValueError(f"{parameter.label} was not found.")
                parsed[parameter.key] = path
            elif parameter.kind == ParameterKind.PERCENT:
                try:
                    value = float(raw_value)
                except ValueError as error:
                    raise ValueError(f"{parameter.label} must be a number.") from error
                if parameter.minimum is not None and value < parameter.minimum:
                    raise ValueError(
                        f"{parameter.label} must be at least {parameter.minimum:g}."
                    )
                if parameter.maximum is not None and value > parameter.maximum:
                    raise ValueError(
                        f"{parameter.label} must be no more than {parameter.maximum:g}."
                    )
                parsed[parameter.key] = value
            else:
                parsed[parameter.key] = raw_value
        return parsed

    def _run(self) -> None:
        try:
            parameters = self._parse_parameters()
        except ValueError as error:
            messagebox.showwarning("Check the process details", str(error), parent=self)
            return

        mode = WorkflowMode(self.mode_value.get()) if self.mode_value.get() else None
        if mode == WorkflowMode.PRODUCTION:
            confirmed = messagebox.askyesno(
                "Confirm production run",
                (
                    f"{self.definition.production_warning}\n\n"
                    "Are you sure you want to continue?"
                ),
                icon="warning",
                parent=self,
            )
            if not confirmed:
                return

        context = WorkflowContext(
            workflow_id=self.definition.workflow_id,
            parameters=parameters,
            mode=mode,
        )
        try:
            self.result_queue = self.executor.run_async(self.definition, context)
        except RuntimeError as error:
            messagebox.showwarning("Process already running", str(error), parent=self)
            return

        self.run_button.configure(state="disabled")
        self.back_button.configure(state="disabled")
        self.output_button.grid_remove()
        self.progress.grid()
        self.progress.start(12)
        self.status_label.configure(
            text="Running… Keep this window open.",
            style="Status.Running.TLabel",
        )
        self.after(100, self._poll_result)

    def _poll_result(self) -> None:
        if self.result_queue is None:
            return
        try:
            result = self.result_queue.get_nowait()
        except queue.Empty:
            self.after(100, self._poll_result)
            return

        self.progress.stop()
        self.progress.grid_remove()
        self.run_button.configure(state="normal")
        self.back_button.configure(state="normal")
        self.status_label.configure(
            text=result.message,
            style=("Status.Success.TLabel" if result.success else "Status.Failure.TLabel"),
        )
        self.output_path = result.output_path
        if result.success and result.output_path:
            self.output_button.grid()
        elif not result.success:
            messagebox.showerror(
                "Process could not be completed",
                f"{result.message}\n\nTechnical details were written to the GUI log.",
                parent=self,
            )

    def _open_output(self) -> None:
        if self.output_path:
            open_path(self.output_path)
