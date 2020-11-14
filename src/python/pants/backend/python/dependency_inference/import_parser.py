# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import ast as ast3
import re
import sys
from dataclasses import dataclass
from pathlib import PurePath
from typing import Optional, Set, Tuple

from typed_ast import ast27

from pants.util.memo import memoized_property
from pants.util.ordered_set import FrozenOrderedSet
from pants.util.strutil import ensure_text


class ImportParseError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedPythonImports:
    """All the discovered imports from a Python source file.

    Explicit imports are imports from `import x` and `from module import x` statements. Inferred
    imports come from strings that look like module names, such as
    `importlib.import_module("example.subdir.Foo")`.
    """

    explicit_imports: FrozenOrderedSet[str]
    inferred_imports: FrozenOrderedSet[str]

    @memoized_property
    def all_imports(self) -> FrozenOrderedSet[str]:
        return FrozenOrderedSet(sorted([*self.explicit_imports, *self.inferred_imports]))


def parse_file(*, filename: str, content: str) -> Optional[Tuple]:
    try:
        # NB: The Python 3 ast is generally backwards-compatible with earlier versions. The only
        # breaking change is `async` `await` becoming reserved keywords in Python 3.7 (deprecated
        # in 3.6). If the std-lib fails to parse, we could use typed-ast to try parsing with a
        # target version of Python 3.5, but we don't because Python 3.5 is almost EOL and has very
        # low usage.
        # We will also fail to parse Python 3.8 syntax if Pants is run with Python 3.6 or 3.7.
        # There is no known workaround for this, beyond users changing their `./pants` script to
        # always use >= 3.8.
        tree = ast3.parse(content, filename=filename)
        visitor_cls = _Py3AstVisitor if sys.version_info[:2] < (3, 8) else _Py38AstVisitor
        return tree, visitor_cls
    except SyntaxError:
        try:
            py27_tree = ast27.parse(content, filename=filename)
            return py27_tree, _Py27AstVisitor
        except SyntaxError:
            return None


def find_python_imports(*, filename: str, content: str) -> ParsedPythonImports:
    package_parts = PurePath(filename).parts[0:-1]
    parse_result = parse_file(filename=filename, content=content)
    # If there were syntax errors, gracefully early return. This is more user friendly than
    # propagating the exception. Dependency inference simply won't be used for that file, and
    # it'll be up to the tool actually being run (e.g. Pytest or Flake8) to error.
    if parse_result is None:
        return ParsedPythonImports(FrozenOrderedSet(), FrozenOrderedSet())
    tree, ast_visitor_cls = parse_result
    ast_visitor = ast_visitor_cls(package_parts)
    ast_visitor.visit(tree)
    return ParsedPythonImports(
        explicit_imports=FrozenOrderedSet(sorted(ast_visitor.explicit_imports)),
        inferred_imports=FrozenOrderedSet(sorted(ast_visitor.inferred_imports)),
    )


# This regex is used to infer imports from strings, e.g.
#  `importlib.import_module("example.subdir.Foo")`.
_INFERRED_IMPORT_REGEX = re.compile(r"^([a-z_][a-z_\d]*\.){2,}[a-zA-Z_]\w*$")


class _BaseAstVisitor:
    def __init__(self, package_parts: Tuple[str, ...]) -> None:
        self._package_parts = package_parts
        self.explicit_imports: Set[str] = set()
        self.inferred_imports: Set[str] = set()

    def maybe_add_inferred_import(self, s: str) -> None:
        if _INFERRED_IMPORT_REGEX.match(s):
            self.inferred_imports.add(s)

    def visit_Import(self, node) -> None:
        for alias in node.names:
            self.explicit_imports.add(alias.name)

    def visit_ImportFrom(self, node) -> None:
        if node.level:
            # Relative import.
            rel_module = node.module
            abs_module = ".".join(
                self._package_parts[0 : len(self._package_parts) - node.level + 1]
                + (tuple() if rel_module is None else (rel_module,))
            )
        else:
            abs_module = node.module
        for alias in node.names:
            self.explicit_imports.add(f"{abs_module}.{alias.name}")


class _Py27AstVisitor(ast27.NodeVisitor, _BaseAstVisitor):
    def visit_Str(self, node) -> None:
        val = ensure_text(node.s)
        self.maybe_add_inferred_import(val)


class _Py3AstVisitor(ast3.NodeVisitor, _BaseAstVisitor):
    def visit_Str(self, node) -> None:
        self.maybe_add_inferred_import(node.s)


class _Py38AstVisitor(ast3.NodeVisitor, _BaseAstVisitor):
    # Python 3.8 deprecated the Str node in favor of Constant.
    def visit_Constant(self, node) -> None:
        if isinstance(node.value, str):
            self.maybe_add_inferred_import(node.value)
