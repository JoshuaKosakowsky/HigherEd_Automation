"""Central visual theme for the staff desktop application."""

from __future__ import annotations

from tkinter import ttk


# Official Mines Communications and Marketing digital palette.
DARK_BLUE = "#21314D"
BLASTER_BLUE = "#09396C"
LIGHT_BLUE = "#879EC3"
COLORADO_RED = "#CC4628"
PALE_BLUE = "#CFDCE9"
WHITE = "#FFFFFF"
LIGHT_GRAY = "#AEB3B8"
SILVER = "#81848A"
DARK_GRAY = "#75757D"
EARTH_BLUE = "#0272DE"
MUTED_BLUE = "#57A2BD"
ENERGY_YELLOW = "#F0F600"
GOLDEN_TECH = "#F1B91A"
ENVIRONMENT_GREEN = "#80C342"
RED_FLANNEL = "#B42024"

# Semantic choices keep the interface mostly within the primary/neutral palette.
PAGE = WHITE
CARD = PALE_BLUE
TEXT = DARK_BLUE
MUTED = DARK_GRAY
SUCCESS = ENVIRONMENT_GREEN
WARNING = GOLDEN_TECH
ERROR = RED_FLANNEL


def apply_theme(style: ttk.Style) -> None:
    """Apply restrained Mines-inspired styles in one place."""
    if "clam" in style.theme_names():
        style.theme_use("clam")

    style.configure("App.TFrame", background=PAGE)
    style.configure("Header.TFrame", background=DARK_BLUE)
    style.configure(
        "HeaderTitle.TLabel",
        background=DARK_BLUE,
        foreground=WHITE,
        font=("Segoe UI", 20, "bold"),
    )
    style.configure(
        "HeaderMeta.TLabel",
        background=DARK_BLUE,
        foreground=PALE_BLUE,
        font=("Segoe UI", 9),
    )
    style.configure(
        "PageTitle.TLabel",
        background=PAGE,
        foreground=TEXT,
        font=("Segoe UI", 18, "bold"),
    )
    style.configure(
        "Section.TLabel",
        background=PAGE,
        foreground=DARK_BLUE,
        font=("Segoe UI", 12, "bold"),
    )
    style.configure(
        "Body.TLabel",
        background=PAGE,
        foreground=TEXT,
        font=("Segoe UI", 10),
    )
    style.configure(
        "Muted.TLabel",
        background=PAGE,
        foreground=MUTED,
        font=("Segoe UI", 9),
    )
    style.configure("Card.TFrame", background=CARD, relief="solid", borderwidth=1)
    style.configure(
        "CardTitle.TLabel",
        background=CARD,
        foreground=TEXT,
        font=("Segoe UI", 12, "bold"),
    )
    style.configure(
        "CardBody.TLabel",
        background=CARD,
        foreground=MUTED,
        font=("Segoe UI", 9),
    )
    style.configure(
        "Field.TLabel",
        background=PAGE,
        foreground=TEXT,
        font=("Segoe UI", 10, "bold"),
    )
    style.configure(
        "Primary.TButton",
        background=BLASTER_BLUE,
        foreground=WHITE,
        font=("Segoe UI", 10, "bold"),
        padding=(18, 9),
    )
    style.map(
        "Primary.TButton",
        background=[("active", DARK_BLUE), ("disabled", LIGHT_GRAY)],
    )
    style.configure("Secondary.TButton", padding=(12, 7))
    style.configure(
        "Production.TLabel",
        background=PALE_BLUE,
        foreground=COLORADO_RED,
        font=("Segoe UI", 10, "bold"),
        padding=10,
    )
    style.configure(
        "Status.Running.TLabel",
        background=PAGE,
        foreground=BLASTER_BLUE,
        font=("Segoe UI", 10, "bold"),
    )
    style.configure(
        "Status.Success.TLabel",
        background=PAGE,
        foreground=SUCCESS,
        font=("Segoe UI", 10, "bold"),
    )
    style.configure(
        "Status.Failure.TLabel",
        background=PAGE,
        foreground=ERROR,
        font=("Segoe UI", 10, "bold"),
    )
