"""Application logging configuration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path


@dataclass(frozen=True)
class GuiLogging:
    logger: logging.Logger
    path: Path


def configure_gui_logging(project_root: Path) -> GuiLogging:
    log_directory = project_root / "logs" / "gui"
    log_directory.mkdir(parents=True, exist_ok=True)
    log_path = log_directory / f"gui_{date.today():%Y%m%d}.log"

    logger = logging.getLogger("highered_automation.gui")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    resolved_path = log_path.resolve()
    existing_path = next(
        (
            Path(handler.baseFilename).resolve()
            for handler in logger.handlers
            if isinstance(handler, logging.FileHandler)
        ),
        None,
    )
    if existing_path != resolved_path:
        for handler in tuple(logger.handlers):
            handler.close()
            logger.removeHandler(handler)

        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logger.addHandler(handler)

    return GuiLogging(logger=logger, path=log_path)
