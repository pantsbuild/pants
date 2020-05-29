# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import ast as ast3
import re
import sys
import warnings
from dataclasses import dataclass
from typing import Set

from typed_ast import ast27

from pants.util.ordered_set import FrozenOrderedSet
from pants.util.strutil import ensure_text


class ImportParseError(ValueError):
    pass


@dataclass(frozen=True)
class PythonImports:
    imported: FrozenOrderedSet[str]
    inferred: FrozenOrderedSet[str]


def parse_file(source_code: str, *, module_name: str):
    try:
        # NB: The Python 3 ast is generally backwards-compatible with earlier versions. The only
        # breaking change is `async` `await` becoming reserved keywords in Python 3.7 (deprecated
        # in 3.6). If the std-lib fails to parse, we could use typed-ast to try parsing with a
        # target version of Python 3.5, but we don't because Python 3.5 is almost EOL and has very
        # low usage.
        # We will also fail to parse Python 3.8 syntax if Pants is run with Python 3.6 or 3.7.
        # There is no known workaround for this, beyond users changing their `./pants` script to
        # always use >= 3.8.
        tree = ast3.parse(source_code)
        visitor_cls = _Py3AstVisitor if sys.version_info[:2] < (3, 8) else _Py38AstVisitor
        return tree, visitor_cls
    except Exception as e:
        try:
            return ast27.parse(source_code), _Py27AstVisitor
        except Exception:
            raise ImportParseError(f"Failed to parse source code for {module_name}:\n{e!r}")


def find_python_imports(source_code: str, *, module_name: str) -> PythonImports:
    tree, ast_visitor_cls = parse_file(source_code, module_name=module_name)
    ast_visitor = ast_visitor_cls(module_name)
    with warnings.catch_warnings():
        # We often encounter this deprecation warning when parsing files. It's noisy for us to
        # display.
        warnings.filterwarnings(
            "ignore", category=DeprecationWarning, message="invalid escape sequence"
        )
        ast_visitor.visit(tree)
    return PythonImports(
        imported=FrozenOrderedSet(sorted(ast_visitor.imported_symbols)),
        inferred=FrozenOrderedSet(sorted(ast_visitor.inferred_symbols)),
    )


_POSSIBLE_MODULE_REGEX = re.compile(r"^([a-z_][a-z_\d]*\.){2,}[a-zA-Z_]\w*$")


class _BaseAstVisitor:
    def __init__(self, module_name: str) -> None:
        self._module_parts = module_name.split(".")
        self.imported_symbols: Set[str] = set()
        self.inferred_symbols: Set[str] = set()

    def maybe_add_string_import(self, s: str) -> None:
        if _POSSIBLE_MODULE_REGEX.match(s):
            self.inferred_symbols.add(s)

    def visit_Import(self, node) -> None:
        for alias in node.names:
            self.imported_symbols.add(alias.name)

    def visit_ImportFrom(self, node) -> None:
        rel_module = node.module
        abs_module = ".".join(
            self._module_parts[0 : -node.level] + ([] if rel_module is None else [rel_module])
        )
        for alias in node.names:
            self.imported_symbols.add(f"{abs_module}.{alias.name}")


class _Py27AstVisitor(ast27.NodeVisitor, _BaseAstVisitor):
    def visit_Str(self, node) -> None:
        val = ensure_text(node.s)
        self.maybe_add_string_import(val)


class _Py3AstVisitor(ast3.NodeVisitor, _BaseAstVisitor):
    def visit_Str(self, node) -> None:
        self.maybe_add_string_import(node.s)


class _Py38AstVisitor(ast3.NodeVisitor, _BaseAstVisitor):
    # Python 3.8 deprecated the Str node in favor of Constant.
    def visit_Constant(self, node) -> None:
        if isinstance(node.value, str):
            self.maybe_add_string_import(node.value)
