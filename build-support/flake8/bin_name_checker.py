# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
"""Checks that we don't use "./pants" in strings."""

from __future__ import annotations

import ast
from pathlib import PurePath
from typing import Iterator


def check_for_hardcoded_pants_bin_name(
    tree: ast.AST, filename: str
) -> Iterator[tuple[int, int, str]]:
    path = PurePath(filename)
    if (
        not filename.startswith("src/python")
        or path.stem.startswith("test_")
        or path.stem.endswith("_test")
    ):
        return

    violations: tuple[int, int] = []

    class Visitor(ast.NodeVisitor):
        def __init__(self):
            self._docstrings: list[str] = []

        def visit_docstringable(self, node: ast.AST):
            self._docstrings.append(ast.get_docstring(node, clean=False))
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

        def visit_Str(self, node: ast.AST) -> None:
            # Don't report on docstrings
            if node.value == self._docstrings[-1]:
                return

            if "./pants" in node.value:
                violations.append((node.lineno, node.col_offset))

        def visit_Constant(self, node: ast.AST) -> None:
            if isinstance(node.value, str):
                self.visit_Str(node)

    Visitor().visit(tree)

    for lineno, colno in violations:
        yield (
            lineno,
            colno,
            "PANTSBIN Don't hardcode `./pants`, use `from pants.util.docutil.bin_name` instead",
            None,
        )


check_for_hardcoded_pants_bin_name.name = __name__
check_for_hardcoded_pants_bin_name.version = "0.0.0"
