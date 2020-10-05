# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re
from dataclasses import dataclass
from typing import Any, Optional, Set, Tuple, Type, TypeVar, Union

import libcst as cst
from pex.interpreter import PythonIdentity
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


def parse_file(
    identity: PythonIdentity,
    *,
    filename: str,
    content: str,
) -> Tuple[Any, "_VisitorInterface"]:
    major, minor, _patch = identity.version
    if major == 2:
        py27_tree = ast27.parse(content, filename=filename)
        return py27_tree, _Py27AstVisitor

    if major != 3:
        raise ValueError(
            f"Unrecognized python version: {identity}. Currently only 2.7 "
            "and 3.5-3.8 are supported."
        )

    # Parse all python 3 code with libCST.
    config = cst.PartialParserConfig(python_version=f"{major}.{minor}")
    cst_tree = cst.parse_module(content, config=config)
    visitor_cls = _CSTVisitor
    return cst_tree, visitor_cls


def find_python_imports(
    identity: PythonIdentity,
    *,
    filename: str,
    content: str,
    module_name: str,
) -> ParsedPythonImports:
    # If there were syntax errors, gracefully early return. This is more user friendly than
    # propagating the exception. Dependency inference simply won't be used for that file, and
    # it'll be up to the tool actually being run (e.g. Pytest or Flake8) to error.
    try:
        parse_result = parse_file(identity, filename=filename, content=content)
    except (SyntaxError, cst.ParserSyntaxError):
        return ParsedPythonImports(FrozenOrderedSet(), FrozenOrderedSet())
    tree, ast_visitor_cls = parse_result
    ast_visitor = ast_visitor_cls.visit_tree(tree, module_name)
    return ParsedPythonImports(
        explicit_imports=FrozenOrderedSet(sorted(ast_visitor.explicit_imports)),
        inferred_imports=FrozenOrderedSet(sorted(ast_visitor.inferred_imports)),
    )


# This regex is used to infer imports from strings, e.g.
#  `importlib.import_module("example.subdir.Foo")`.
_INFERRED_IMPORT_REGEX = re.compile(r"^([a-z_][a-z_\d]*\.){2,}[a-zA-Z_]\w*$")


_Visitor = TypeVar("_Visitor")


class _VisitorInterface:
    def __init__(self, module_name: str) -> None:
        ...

    @classmethod
    def visit_tree(cls: Type[_Visitor], tree: Any, module_name: str) -> _Visitor:
        ...


class _Py27AstVisitor(ast27.NodeVisitor, _VisitorInterface):
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


class _CSTVisitor(cst.CSTVisitor, _VisitorInterface):
    def __init__(self, module_name: str) -> None:
        self._module_parts = module_name.split(".")
        self.explicit_imports: Set[str] = set()
        self.inferred_imports: Set[str] = set()

    @classmethod
    def visit_tree(cls: Type[_Visitor], tree: Any, module_name: str) -> _Visitor:
        visitor = cls(module_name)
        tree.visit(visitor)
        return visitor

    def _maybe_add_inferred_import(self, s: str) -> None:
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
