# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
"""Checks that we don't use "./pants" in strings."""

from __future__ import annotations

import ast
from pathlib import PurePath
from typing import Iterator, cast


def check_for_hardcoded_pants_bin_name(
    tree: ast.AST, filename: str
) -> Iterator[tuple[int, int, str, None]]:
    path = PurePath(filename)
    if (
        not filename.startswith("src/python")
        or path.stem.startswith("test_")
        or path.stem.endswith("_test")
    ):
        return

    violations: list[tuple[int, int]] = []

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self._docstrings: list[str | None] = []

        def visit_docstringable(self, node: ast.AST):
            self._docstrings.append(ast.get_docstring(node, clean=False))  # type: ignore[arg-type]
            self.generic_visit(node)
            self._docstrings.pop()

        def visit_FunctionDef(self, node: ast.AST):
            self.visit_docstringable(node)

        def visit_AsyncFunctionDef(self, node: ast.AST):
            self.visit_docstringable(node)

        def visit_ClassDef(self, node: ast.AST):
            self.visit_docstringable(node)

        def visit_Module(self, node: ast.AST):
            self.visit_docstringable(node)

        # Python 3.7
        def visit_Str(self, node: ast.Str) -> None:
            # Don't report on docstrings
            if node.s == self._docstrings[-1]:
                return

            if "./pants" in node.s:
                violations.append((node.lineno, node.col_offset))

        # Python 3.8+
        def visit_Constant(self, node: ast.Constant) -> None:
            if isinstance(node.value, str):
                self.visit_Str(cast(ast.Str, node))

    Visitor().visit(tree)

    for lineno, colno in violations:
        yield (
            lineno,
            colno,
            "PNT10 Don't hardcode `./pants`, use `from pants.util.docutil.bin_name` instead",
            None,
        )


setattr(check_for_hardcoded_pants_bin_name, "name", __name__)
setattr(check_for_hardcoded_pants_bin_name, "version", "0.0.0")
