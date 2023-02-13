# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
"""Prefer softwrap over dedent in non-test code."""

from __future__ import annotations

import ast
from pathlib import PurePath
from typing import Iterator


def check_for_dedent_imports(tree: ast.AST, filename: str) -> Iterator[tuple[int, int, str, None]]:
    path = PurePath(filename)
    if (
        not filename.startswith("src/python")
        or path.stem.startswith("test_")
        or path.stem.endswith("_test")
    ):
        return

    violations: list[tuple[int, int, str, None]] = []

    class Visitor(ast.NodeVisitor):
        def visit_ImportFrom(self, node: ast.ImportFrom):
            for alias in node.names:
                if alias.name == "dedent":
                    violations.append(
                        (
                            node.lineno,
                            node.col_offset,
                            "PNT20 Don't import `textwrap.dedent`, import `pants.util.strutil.softwrap` instead",
                            None,
                        )
                    )

        def visit_Call(self, node: ast.Call):
            is_dedent_call = (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.attr == "dedent"
                and node.func.value.id == "textwrap"
            )
            if is_dedent_call:
                violations.append(
                    (
                        node.lineno,
                        node.col_offset,
                        "PNT20 Don't call `textwrap.dedent`, call `softwrap` from `pants.util.strutil` instead",
                        None,
                    )
                )
            else:
                for arg in node.args:
                    self.visit(arg)

    Visitor().visit(tree)
    yield from violations


setattr(check_for_dedent_imports, "name", __name__)
setattr(check_for_dedent_imports, "version", "0.0.0")
