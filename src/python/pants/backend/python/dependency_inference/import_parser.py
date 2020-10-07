# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import re
from dataclasses import dataclass
from typing import Any, Optional, Set, Type, TypeVar, Union

import libcst as cst
from typed_ast import ast27

from pants.util.memo import memoized_property
from pants.util.ordered_set import FrozenOrderedSet
from pants.util.strutil import ensure_text


logger = logging.getLogger(__name__)


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


_Visitor = TypeVar("_Visitor")


class VisitorInterface:
    explicit_imports: Set[str]
    inferred_imports: Set[str]

    def __init__(self, module_name: str) -> None:
        ...

    @classmethod
    def visit_tree(cls: Type[_Visitor], tree: Any, module_name: str) -> _Visitor:
        ...


def parse_file(*, filename: str, content: str, module_name: str) -> Optional[VisitorInterface]:
    """Parse the file for python imports, and return a visitor with the imports it found."""
    # Parse all python 3 code with libCST. We parse assuming python 3 goes first, because we assume
    # most user code will be python 3.
    # TODO(#10921): identify the appropriate interpreter version beforehand!
    try:
        # NB: Since all python 3 code is forwards-compatible with the 3.8 parser, and the import
        # syntax remains unchanged, we are safely able to use the 3.8 parser for parsing imports.
        # TODO(#10922): Support parsing python 3.9/3.10 with libCST!
        config = cst.PartialParserConfig(python_version="3.8")
        cst_tree = cst.parse_module(content, config=config)
        completed_visitor = _CSTVisitor.visit_tree(cst_tree, module_name=module_name)
        return completed_visitor
    except cst.ParserSyntaxError as e:
        # NB: When the python 3 ast visitor fails to parse python 2 syntax, it raises a
        # ParserSyntaxError. This may also occur when the file contains invalid python code. If we
        # successfully parse a python 2 file with a python 3 parser, that should not change the
        # imports we calculate.
        logger.debug(f"Failed to parse {filename} with python 3.8 libCST parser: {e}")

    try:
        py27_tree = ast27.parse(content, filename=filename)
        completed_visitor = _Py27AstVisitor.visit_tree(py27_tree, module_name=module_name)
        return completed_visitor
    except SyntaxError as e:
        logger.debug(f"Failed to parse {filename} with python 2.7 typed-ast parser: {e}")

    return None


def find_python_imports(*, filename: str, content: str, module_name: str) -> ParsedPythonImports:
    completed_visitor = parse_file(filename=filename, content=content, module_name=module_name)
    # If there were syntax errors, gracefully early return. This is more user friendly than
    # propagating the exception. Dependency inference simply won't be used for that file, and
    # it'll be up to the tool actually being run (e.g. Pytest or Flake8) to error.
    if completed_visitor is None:
        return ParsedPythonImports(FrozenOrderedSet(), FrozenOrderedSet())
    return ParsedPythonImports(
        explicit_imports=FrozenOrderedSet(sorted(completed_visitor.explicit_imports)),
        inferred_imports=FrozenOrderedSet(sorted(completed_visitor.inferred_imports)),
    )


# This regex is used to infer imports from strings, e.g.
#  `importlib.import_module("example.subdir.Foo")`.
_INFERRED_IMPORT_REGEX = re.compile(r"^([a-z_][a-z_\d]*\.){2,}[a-zA-Z_]\w*$")


class _Py27AstVisitor(ast27.NodeVisitor, VisitorInterface):
    def __init__(self, module_name: str) -> None:
        self._module_parts = module_name.split(".")
        self.explicit_imports: Set[str] = set()
        self.inferred_imports: Set[str] = set()

    @classmethod
    def visit_tree(cls: Type[_Visitor], tree: Any, module_name: str) -> _Visitor:
        visitor = cls(module_name)
        visitor.visit(tree)
        return visitor

    def _maybe_add_inferred_import(self, s: str) -> None:
        if _INFERRED_IMPORT_REGEX.match(s):
            self.inferred_imports.add(s)

    def visit_Import(self, node) -> None:
        for alias in node.names:
            self.explicit_imports.add(alias.name)

    def visit_ImportFrom(self, node) -> None:
        rel_module = node.module
        abs_module = ".".join(
            self._module_parts[0 : -node.level] + ([] if rel_module is None else [rel_module])
        )
        for alias in node.names:
            self.explicit_imports.add(f"{abs_module}.{alias.name}")

    def visit_Str(self, node) -> None:
        val = ensure_text(node.s)
        self._maybe_add_inferred_import(val)


class _CSTVisitor(cst.CSTVisitor, VisitorInterface):
    def __init__(self, module_name: str) -> None:
        self._module_parts = module_name.split(".")
        self.explicit_imports: Set[str] = set()
        self.inferred_imports: Set[str] = set()

    @classmethod
    def visit_tree(cls: Type[_Visitor], tree: Any, module_name: str) -> _Visitor:
        visitor = cls(module_name)
        tree.visit(visitor)
        return visitor

    def _maybe_add_inferred_import(self, s: Union[str, bytes]) -> None:
        if isinstance(s, bytes):
            return
        if _INFERRED_IMPORT_REGEX.match(s):
            self.inferred_imports.add(s)

    def _flatten_attribute_or_name(self, node: Optional[Union[cst.Attribute, cst.Name]]) -> str:
        if node is None:
            return ""
        if isinstance(node, cst.Name):
            return node.value
        inner = self._flatten_attribute_or_name(node.value)
        return f"{inner}.{node.attr.value}"

    def visit_Import(self, node) -> None:
        for alias in node.names:
            self.explicit_imports.add(self._flatten_attribute_or_name(alias.name))

    def visit_ImportFrom(self, node) -> None:
        rel_module = self._flatten_attribute_or_name(node.module)
        abs_module = ".".join(
            self._module_parts[0 : -len(node.relative)]
            + ([] if rel_module is None else [rel_module])
        )
        for alias in node.names:
            self.explicit_imports.add(f"{abs_module}.{alias.name.value}")

    def visit_SimpleString(self, node) -> None:
        self._maybe_add_inferred_import(node.evaluated_value)
