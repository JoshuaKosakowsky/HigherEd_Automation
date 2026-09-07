"""Registry-driven home page."""

from __future__ import annotations

from collections import defaultdict
from tkinter import ttk
from typing import Callable, Iterable

from app.gui.models import WorkflowDefinition


class HomePage(ttk.Frame):
    def __init__(
        self,
        parent,
        workflows: Iterable[WorkflowDefinition],
        open_workflow: Callable[[WorkflowDefinition], None],
        *,
        user_first_name: str,
        profile_description: str | None = None,
    ) -> None:
        super().__init__(parent, style="App.TFrame", padding=(36, 28))
        self.columnconfigure(0, weight=1)

        ttk.Label(
            self,
            text=f"Welcome {user_first_name}",
            style="PageTitle.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            self,
            text=(
                "Choose an automation to review its inputs before anything runs."
            ),
            style="Body.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(4, 22))

        if profile_description:
            ttk.Label(
                self,
                text=profile_description,
                style="Muted.TLabel",
            ).grid(row=2, column=0, sticky="w", pady=(0, 18))

        by_category: dict[str, list[WorkflowDefinition]] = defaultdict(list)
        for workflow in workflows:
            by_category[workflow.category].append(workflow)

        if not by_category:
            ttk.Label(
                self,
                text=(
                    "No automations are assigned to this user profile. "
                    "Contact the automation administrator if access is needed."
                ),
                style="Muted.TLabel",
                wraplength=650,
                justify="left",
            ).grid(row=3, column=0, sticky="w", pady=(4, 0))
            return

        row = 3
        for category, definitions in by_category.items():
            ttk.Label(self, text=category, style="Section.TLabel").grid(
                row=row,
                column=0,
                sticky="w",
                pady=(0, 9),
            )
            row += 1

            card_area = ttk.Frame(self, style="App.TFrame")
            card_area.grid(row=row, column=0, sticky="ew", pady=(0, 22))
            card_area.columnconfigure(0, weight=1)
            card_area.columnconfigure(1, weight=1)

            for index, definition in enumerate(definitions):
                self._add_card(
                    card_area,
                    definition,
                    open_workflow,
                    row=index // 2,
                    column=index % 2,
                )
            row += 1

    @staticmethod
    def _add_card(
        parent,
        definition: WorkflowDefinition,
        open_workflow: Callable[[WorkflowDefinition], None],
        *,
        row: int,
        column: int,
    ) -> None:
        card = ttk.Frame(parent, style="Card.TFrame", padding=18)
        card.grid(
            row=row,
            column=column,
            sticky="nsew",
            padx=(0, 10) if column == 0 else (10, 0),
            pady=(0, 12),
        )
        card.columnconfigure(0, weight=1)

        ttk.Label(card, text=definition.name, style="CardTitle.TLabel").grid(
            row=0,
            column=0,
            sticky="w",
        )
        ttk.Label(
            card,
            text=definition.description,
            style="CardBody.TLabel",
            wraplength=330,
            justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(7, 15))
        ttk.Button(
            card,
            text="Review and run",
            style="Secondary.TButton",
            command=lambda item=definition: open_workflow(item),
        ).grid(row=2, column=0, sticky="w")
