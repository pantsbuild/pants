# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
"""Disallow 'await' in a loop."""
from __future__ import annotations

import ast
from contextlib import contextmanager
from pathlib import PurePath
from typing import Iterator, Sequence


def check_for_await_in_loop(tree: ast.AST, filename: str) -> Iterator[tuple[int, int, str, None]]:
    path = PurePath(filename)
    if (
        not filename.startswith("src/python")
        or path.stem.startswith("test_")
        or path.stem.endswith("_test")
    ):
        return

    violations: list[tuple[int, int, str, None]] = []

    class Visitor(ast.NodeVisitor):
        def __init__(self):
            # this isn't entirely correct: function/class definitions within a loop might have
            # `await`s in them, but aren't _necessarily_ a problem (see example below).
            #
            # tasks = []
            # for i in range(10):
            #     async def foo(i=i):
            #         await bar(i)
            #     tasks.append(foo())
            # asyncio.gather(tasks)
            self._in_loop = False

        @contextmanager
        def in_loop(self) -> Iterator[None]:
            old = self._in_loop
            self._in_loop = True
            try:
                yield
            finally:
                self._in_loop = old

        def traverse(self, node: ast.AST | Sequence[ast.AST]):
            if isinstance(node, ast.AST):
                self.visit(node)
            else:
                for x in node:
                    self.visit(x)

        def visit_for(self, node: ast.For | ast.AsyncFor):
            """Example::

            [async] for MULTIPLE in await ONCE:
                await MULTIPLE
            else:
                await ONCE
            """
            self.visit(node.iter)
            self.traverse(node.orelse)

            with self.in_loop():
                self.visit(node.target)
                self.traverse(node.body)

        visit_For = visit_AsyncFor = visit_for

        def visit_While(self, node: ast.While):
            """Example:

            while await MULTIPLE:
                await MULTIPLE
            """
            with self.in_loop():
                self.generic_visit(node)

        def visit_comp(self, node: ast.DictComp | ast.ListComp | ast.SetComp | ast.GeneratorExp):
            """Example::

            [
                await MULTIPLE
                [async] for MULTIPLE in await ONCE
                if MULTIPLE
                for MULTIPLE in await MULTIPLE
            ]
            """
            first_comp = node.generators[0]
            self.visit(first_comp.iter)

            with self.in_loop():
                self.visit(first_comp.target)
                for expr in first_comp.ifs:
                    self.visit(expr)

                for other_comp in node.generators[1:]:
                    self.visit(other_comp)

                if isinstance(node, ast.DictComp):
                    self.visit(node.key)
                    self.visit(node.value)
                else:
                    self.visit(node.elt)

        visit_ListComp = visit_GeneratorExp = visit_SetComp = visit_DictComp = visit_comp

        def _await_that_could_be_multiget(self, node: ast.Await) -> bool:
            """Check for `await Get(...)` or `await MultiGet(...)` literally."""
            value = node.value

            # This checks for `await Get()` and `await MultiGet()` literally, because there's not
            # currently MultiGet support for normal async functions (i.e. `[await some_helper(x) for x in
            # ...]` cannot become `await MultiGet([some_helper(x) for x in ...])` ). Once that's
            # supported, this could flip to default to True, except for `await Effect`.

            return (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id in ("Get", "MultiGet")
            )

        def visit_Await(self, node: ast.Await):
            if self._in_loop and self._await_that_could_be_multiget(node):
                violations.append(
                    (
                        node.lineno,
                        node.col_offset,
                        "PNT30 `await` in a loop may be a performance hazard: prefer concurrent requests via MultiGet, or add `# noqa: PNT30: <explanation>` if this is required",
                        None,
                    )
                )

    Visitor().visit(tree)
    yield from violations


setattr(check_for_await_in_loop, "name", __name__)
setattr(check_for_await_in_loop, "version", "0.0.0")
