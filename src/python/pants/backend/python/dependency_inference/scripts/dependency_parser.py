# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
# -*- coding: utf-8 -*-

# NB: This must be compatible with Python 2.7 and 3.5+.
# NB: If you're needing to debug this, an easy way is to just invoke it on a file.
#   E.g. `STRING_IMPORTS=y ... python3 src/python/pants/backend/python/dependency_inference/scripts/import_parser.py FILENAME`

from __future__ import print_function, unicode_literals

import ast
import itertools
import json
import os
import re
import sys
import tokenize
from io import open


class AstVisitor(ast.NodeVisitor):
    def __init__(self, package_parts, contents):
        self._package_parts = package_parts
        self._contents_lines = contents.decode(errors="ignore").splitlines()

        # Each of these maps module_name to first lineno of occurance
        # N.B. use `setdefault` when adding imports
        # (See `ParsedPythonImportInfo` in ../parse_python_imports.py for the delineation of
        #   weak/strong)
        self.strong_imports = {}
        self.weak_imports = {}
        self.assets = set()
        self._weaken_strong_imports = False
        if os.environ["STRING_IMPORTS"] == "y":
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

        if os.environ["ASSETS"] == "y":
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
            self.weak_imports.setdefault(s, node.lineno)
        if self._asset_regex and self._asset_regex.match(s):
            self.assets.add(s)

    def add_strong_import(self, name, lineno):
        imports = self.weak_imports if self._weaken_strong_imports else self.strong_imports
        imports.setdefault(name, lineno)

    def _is_pragma_ignored(self, line_index):
        """Return if the line at `line_index` (0-based) is pragma ignored."""
        line_iter = itertools.dropwhile(
            lambda line: line.endswith("\\"),
            itertools.islice(self._contents_lines, line_index, None),
        )
        return "# pants: no-infer-dep" in next(line_iter)

    def _visit_import_stmt(self, node, import_prefix):
        # N.B. We only add imports whose line doesn't contain "# pants: no-infer-dep"
        # However, `ast` doesn't expose the exact lines each specific import is on,
        # so we are forced to tokenize the import statement to tease out which imported
        # name is on which line so we can check for the ignore pragma.
        node_lines_iter = itertools.islice(self._contents_lines, node.lineno - 1, None)
        token_iter = tokenize.generate_tokens(lambda: next(node_lines_iter))

        def find_token(string):
            return next(itertools.dropwhile(lambda token: token[1] != string, token_iter))

        find_token("import")

        # N.B. The names in this list are in the same order as the import statement
        for alias in node.names:
            token = find_token(alias.name.split(".")[-1])
            lineno = token[3][0] + node.lineno - 1

            if not self._is_pragma_ignored(lineno - 1):
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
                self._weaken_strong_imports = True
                break

        for stmt in node.body:
            self.visit(stmt)

        self._weaken_strong_imports = False

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
            if sys.version_info[0:2] < (3, 8):
                name = node.args[0].s if isinstance(node.args[0], ast.Str) else None
            else:
                name = node.args[0].value if isinstance(node.args[0], ast.Constant) else None

            if name is not None:
                lineno = node.args[0].lineno
                if not self._is_pragma_ignored(lineno - 1):
                    self.add_strong_import(name, lineno)
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


def main(filename):
    with open(filename, "rb") as f:
        content = f.read()
    try:
        tree = ast.parse(content, filename=filename)
    except SyntaxError:
        return

    package_parts = os.path.dirname(filename).split(os.path.sep)
    visitor = AstVisitor(package_parts, content)
    visitor.visit(tree)

    # We have to be careful to set the encoding explicitly and write raw bytes ourselves.
    # See below for where we explicitly decode.
    buffer = sys.stdout if sys.version_info[0:2] == (2, 7) else sys.stdout.buffer

    # N.B. Start with weak and `update` with definitive so definite "wins"
    imports_result = {
        module_name: {"lineno": lineno, "weak": True}
        for module_name, lineno in visitor.weak_imports.items()
    }
    imports_result.update(
        {
            module_name: {"lineno": lineno, "weak": False}
            for module_name, lineno in visitor.strong_imports.items()
        }
    )

    buffer.write(
        json.dumps(
            {
                "imports": imports_result,
                "assets": sorted(visitor.assets),
            }
        ).encode("utf8")
    )


if __name__ == "__main__":
    main(sys.argv[1])
