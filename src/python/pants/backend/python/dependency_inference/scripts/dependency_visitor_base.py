# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
# -*- coding: utf-8 -*-

# NB: This must be compatible with Python 2.7 and 3.5+.

from __future__ import print_function, unicode_literals

import ast
import itertools
import sys


class FoundDependencies:
    def __init__(self):
        # Each of these maps module_name to first lineno of occurance
        # N.B. use `setdefault` when adding imports
        # (See `ParsedPythonImportInfo` in parse_python_imports.py for the delineation of
        #   weak/strong)
        self.strong_imports = {}
        self.weak_imports = {}
        self.assets = set()


class DependencyVisitorBase(ast.NodeVisitor):
    """Base class for code that extracts dependencies from the AST."""

    @staticmethod
    def maybe_str(node):
        if sys.version_info[0:2] < (3, 8):
            return node.s if isinstance(node, ast.Str) else None
        else:
            return node.value if isinstance(node, ast.Constant) else None

    def __init__(self, found_dependencies, package_parts, contents):
        self._found_dependencies = found_dependencies
        self._package_parts = package_parts
        self._contents_lines = contents.decode(errors="ignore").splitlines()

        # While this is set to True, otherwise-strong imports will be treated as weak.
        self.weaken_strong_imports = False

    def add_strong_import(self, name, lineno):
        if not self._is_pragma_ignored(lineno - 1):
            imports = (
                self._found_dependencies.weak_imports
                if self.weaken_strong_imports
                else self._found_dependencies.strong_imports
            )
            imports.setdefault(name, lineno)

    def add_weak_import(self, name, lineno):
        if not self._is_pragma_ignored(lineno - 1):
            self._found_dependencies.weak_imports.setdefault(name, lineno)

    def add_asset(self, name, lineno):
        if not self._is_pragma_ignored(lineno - 1):
            self._found_dependencies.assets.add(name)

    def _is_pragma_ignored(self, line_index):
        """Return if the line at `line_index` (0-based) is pragma ignored."""
        line_iter = itertools.dropwhile(
            lambda line: line.endswith("\\"),
            itertools.islice(self._contents_lines, line_index, None),
        )
        return "# pants: no-infer-dep" in next(line_iter)
