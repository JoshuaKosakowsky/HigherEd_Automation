"""Toolkit-independent parsing of registry-defined workflow inputs."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Mapping

from app.gui.models import ParameterDefinition, ParameterKind


def parse_parameters(
    definitions: tuple[ParameterDefinition, ...], values: Mapping[str, str]
) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    for parameter in definitions:
        if parameter.kind == ParameterKind.NAME_LIST:
            raw_names = values[parameter.key]
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
            raw_paths = values[parameter.key]
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

        raw_value = values[parameter.key].strip()
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
            if not math.isfinite(value):
                raise ValueError(f"{parameter.label} must be a finite number.")
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
