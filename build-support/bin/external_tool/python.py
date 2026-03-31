# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import ast
import json
import logging
import os
import textwrap
from collections.abc import Generator
from pathlib import Path
from typing import Any, TypeVar

logger = logging.getLogger(__name__)
T = TypeVar("T")


def _format_value(value: Any, indent: int = 4) -> str:
    # Do some extra work to format lists with a trailing comma to minimize
    # conflict with ruff/black, otherwise just json.dumps
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        if not value:
            return "[]"
        spaces = " " * indent
        formatted_items = [f'{spaces}"{item}",' for item in value]
        return "[\n" + "\n".join(formatted_items) + "\n]"
    return json.dumps(value, indent=indent)


def get_class_variables(file_path: Path, class_name: str, *, variables: type[T]) -> T:
    """Reads a Python file and retrieves the values of specified class variables."""

    logger.info("parsing %s variables in %s", class_name, file_path)
    with open(file_path, encoding="utf-8") as file:
        source_code = file.read()

    tree = ast.parse(source_code)
    values = {}

    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for stmt in node.body:
                if isinstance(stmt, ast.Assign):
                    for target in stmt.targets:
                        if isinstance(target, ast.Name) and target.id in variables.__annotations__:
                            values[target.id] = ast.literal_eval(stmt.value)

    return variables(**values)


def replace_class_variables(file_path: Path, class_name: str, replacements: dict[str, Any]) -> None:
    """Reads a Python file, searches for a class by name, and replaces specified class variables
    with new values."""
    with open(file_path, encoding="utf-8") as file:
        lines = file.readlines()

    tree = ast.parse("".join(lines))

    class_var_ranges = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for stmt in node.body:
                if isinstance(stmt, ast.Assign):
                    for target in stmt.targets:
                        if isinstance(target, ast.Name) and target.id in replacements:
                            start_line = stmt.lineno - 1
                            end_line = (
                                stmt.end_lineno if stmt.end_lineno is not None else start_line
                            )
                            class_var_ranges[target.id] = (start_line, end_line)

    logger.debug("class_var_ranges: %s", class_var_ranges)

    prev_end = 0
    with open(file_path, "w", encoding="utf-8") as file:
        for var, (start, end) in class_var_ranges.items():
            file.writelines(lines[prev_end:start])
            line = textwrap.indent(
                f"{var} = {_format_value(replacements[var])}\n",
                "    ",
            )
            file.writelines([line])
            prev_end = end
        file.writelines(lines[prev_end:])


def find_modules_with_subclasses(
    directory: Path,
    *,
    base_classes: set[str],
    exclude: set[str],
) -> Generator[tuple[Path, str]]:
    """Recursively finds Python modules that contain classes subclassing a given base class."""

    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith(".py"):
                file_path = Path(root) / file
                source_code = file_path.read_text()

                tree = ast.parse(source_code)
                for node in tree.body:
                    if isinstance(node, ast.ClassDef) and node.name not in exclude:
                        for base in node.bases:
                            if isinstance(base, ast.Name) and base.id in base_classes:
                                yield file_path, node.name
