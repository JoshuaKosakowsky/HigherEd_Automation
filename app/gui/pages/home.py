"""Searchable, access-filtered workflow landing page."""

from collections import defaultdict
from typing import Callable, Iterable

from PySide6.QtWidgets import QLineEdit, QScrollArea, QWidget, QVBoxLayout, QHBoxLayout

from app.gui.models import WorkflowDefinition
from app.gui.theme import button, card, label


class HomePage(QScrollArea):
    def __init__(
        self, parent, workflows: Iterable[WorkflowDefinition],
        open_workflow: Callable[[WorkflowDefinition], None], *,
        user_first_name: str, profile_description: str | None = None,
        manage_access: Callable[[], None] | None = None,
        access_error: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        body = QWidget()
        body.setObjectName("page")
        self.setWidget(body)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(36, 30, 36, 30)
        layout.setSpacing(18)
        layout.addWidget(label("YOUR WORKSPACE", "eyebrow"))
        layout.addWidget(label(f"Welcome {user_first_name}", "title"))
        layout.addWidget(label("Choose a workflow. Review the details. Get back to your day.", "muted"))
        if profile_description:
            layout.addWidget(label(profile_description, "muted"))
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search your workflows…")
        self.search.setAccessibleName("Search workflows")
        self.search.setClearButtonEnabled(True)
        layout.addWidget(self.search)
        self.cards = []
        self.categories = []
        groups = defaultdict(list)
        for definition in workflows:
            groups[definition.category].append(definition)
        for category, definitions in groups.items():
            heading = label(category, "section")
            layout.addWidget(heading)
            group_cards = []
            for definition in definitions:
                frame, content = card()
                row = QHBoxLayout()
                row.addWidget(label(definition.name, "section"), 1)
                launch = button("Review workflow  →", lambda checked=False, item=definition: open_workflow(item), "primary")
                row.addWidget(launch)
                content.addLayout(row)
                content.addWidget(label(definition.description, "muted"))
                layout.addWidget(frame)
                self.cards.append((frame, f"{definition.name} {definition.description} {category}".casefold()))
                group_cards.append(frame)
            self.categories.append((heading, group_cards))
        self.empty = label(
            access_error or (
                "No workflows are assigned to your account yet. Contact your automation administrator."
                if not self.cards else "No workflows match your search."
            ), "status",
        )
        self.empty.setVisible(not self.cards)
        layout.addWidget(self.empty)
        layout.addStretch()
        self.search.textChanged.connect(self._filter)

    def _filter(self, query: str) -> None:
        query = query.strip().casefold()
        count = 0
        for frame, text in self.cards:
            visible = query in text
            frame.setVisible(visible)
            count += visible
        for heading, frames in self.categories:
            heading.setVisible(any(not frame.isHidden() for frame in frames))
        self.empty.setVisible(count == 0)
