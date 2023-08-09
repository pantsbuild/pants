# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
# -*- coding: utf-8 -*-

# NB: This must be compatible with Python 2.7 and 3.5+.
from __future__ import print_function, unicode_literals

import ast
import itertools
import os
import re
import tokenize

from pants.backend.python.dependency_inference.scripts.dependency_visitor_base import (
    DependencyVisitorBase,
)


class GeneralDependencyVisitor(DependencyVisitorBase):
    def __init__(self, *args, **kwargs):
        super(GeneralDependencyVisitor, self).__init__(*args, **kwargs)

        if os.environ.get("STRING_IMPORTS", "n") == "y":
            # This regex is used to infer imports from strings, e.g .
            #  `importlib.import_module("example.subdir.Foo")`.
            self._string_import_regex = re.compile(
                r"^([a-z_][a-z_\d]*\.){"
                + os.environ["STRING_IMPORTS_MIN_DOTS"]
                + r",}[a-zA-Z_]\w*$",
                re.UNICODE,
            )
        else:
            self._string_import_regex = None

        if os.environ.get("ASSETS", "n") == "y":
            # This regex is used to infer asset names from strings, e.g.
            #  `load_resource("data/db1.json")
            # Since Unix allows basically anything for filenames, we require some "sane" subset of
            #  possibilities namely, word-character filenames and a mandatory extension.
            self._asset_regex = re.compile(
                r"^([\w-]*\/){" + os.environ["ASSETS_MIN_SLASHES"] + r",}[\w-]*(\.[^\/\.\n]+)+$",
                re.UNICODE,
            )
        else:
            self._asset_regex = None

    def maybe_add_string_dependency(self, node, s):
        if self._string_import_regex and self._string_import_regex.match(s):
            self.add_weak_import(s, node.lineno)
        if self._asset_regex and self._asset_regex.match(s):
            self.add_asset(s, node.lineno)

    def _visit_import_stmt(self, node, import_prefix):
        # N.B. We only add imports whose line doesn't contain "# pants: no-infer-dep"
        # However, `ast` doesn't expose the exact lines each specific import is on,
        # so we are forced to tokenize the import statement to tease out which imported
        # name is on which line so we can check for the ignore pragma.
        # Note that we ensure we don't pass an empty string to generate_tokens,
        # see https://github.com/pantsbuild/pants/issues/17283.
        node_lines_iter = (
            line or " " for line in itertools.islice(self._contents_lines, node.lineno - 1, None)
        )
        token_iter = tokenize.generate_tokens(lambda: next(node_lines_iter))

        def find_token(string):
            return next(itertools.dropwhile(lambda token: token[1] != string, token_iter))

        find_token("import")

        # N.B. The names in this list are in the same order as the import statement
        for alias in node.names:
            token = find_token(alias.name.split(".")[-1])
            lineno = token[3][0] + node.lineno - 1
            self.add_strong_import(import_prefix + alias.name, lineno)
            if alias.asname and token[1] != alias.asname:
                find_token(alias.asname)

    def visit_Import(self, node):
        self._visit_import_stmt(node, "")

    def visit_ImportFrom(self, node):
        if node.level:
            # Relative import.
            rel_module = node.module
            abs_module = ".".join(
                self._package_parts[0 : len(self._package_parts) - node.level + 1]
                + ([] if rel_module is None else [rel_module])
            )
        else:
            abs_module = node.module
        self._visit_import_stmt(node, abs_module + ".")

    def visit_TryExcept(self, node):
        for handler in node.handlers:
            # N.B. Python allows any arbitrary expression as an except handler.
            # We only parse Name, or (Set/Tuple/List)-of-Names expressions
            if isinstance(handler.type, ast.Name):
                exprs = (handler.type,)
            elif isinstance(handler.type, (ast.Tuple, ast.Set, ast.List)):
                exprs = handler.type.elts
            else:
                continue

            if any(isinstance(expr, ast.Name) and expr.id == "ImportError" for expr in exprs):
                self.weaken_strong_imports = True
                break

        for stmt in node.body:
            self.visit(stmt)

        self.weaken_strong_imports = False

        for handler in node.handlers:
            self.visit(handler)

        for stmt in node.orelse:
            self.visit(stmt)

    def visit_Try(self, node):
        self.visit_TryExcept(node)
        for stmt in node.finalbody:
            self.visit(stmt)

    def visit_Call(self, node):
        # Handle __import__("string_literal").  This is commonly used in __init__.py files,
        # to explicitly mark namespace packages.  Note that we don't handle more complex
        # uses, such as those that set `level`.
        if isinstance(node.func, ast.Name) and node.func.id == "__import__" and len(node.args) == 1:
            name = self.maybe_str(node.args[0])
            if name is not None:
                self.add_strong_import(name, node.args[0].lineno)
                return

        self.generic_visit(node)

    # For Python 2.7, and Python3 < 3.8
    def visit_Str(self, node):
        try:
            val = node.s.decode("utf8") if isinstance(node.s, bytes) else node.s
            self.maybe_add_string_dependency(node, val)
        except UnicodeError:
            pass

    # For Python 3.8+
    def visit_Constant(self, node):
        if isinstance(node.value, str):
            self.maybe_add_string_dependency(node, node.value)
