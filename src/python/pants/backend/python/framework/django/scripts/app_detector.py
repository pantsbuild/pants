# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
# -*- coding: utf-8 -*-

# NB: This must be compatible with Python 2.7 and 3.5+.
# NB: An easy way to debug this is to just invoke it on a file.
#   E.g.
#   $ python src/python/pants/backend/python/framework/django/scripts/app_detector.py PATHS
#   Or
#   $ ./pants run src/python/pants/backend/python/framework/django/scripts/app_detector.py -- PATHS

from __future__ import print_function, unicode_literals

import ast
import json
import os
import sys


class DjangoAppDetector(ast.NodeVisitor):
    @staticmethod
    def maybe_str(node):
        if sys.version_info[0:2] < (3, 8):
            return node.s if isinstance(node, ast.Str) else None
        else:
            return node.value if isinstance(node, ast.Constant) else None

    def __init__(self):
        self._app_name = ""
        self._app_label = ""

    @property
    def app_name(self):
        return self._app_name

    @property
    def app_label(self):
        return self._app_label or self._app_name.rpartition(".")[2]

    def visit_ClassDef(self, node):
        # We detect an AppConfig subclass via the following heuristics:
        # A) The definition is exactly `MyClassName(AppConfig)` (rather than
        #    `MyClassName(apps.AppConfig)` and so on). This is what Django's
        #    startapp tool generates, and is a very strong convention.
        # - or -
        # B) The class name ends with `AppConfig`.
        #    This catches violations of the conventions of A), e.g., if there
        #    are custom intermediate subclasses of AppConfig, or custom extra
        #    base classes.
        #
        # These should catch every non-perverse case in practice.
        if node.name.endswith("AppConfig") or (
            len(node.bases) == 1
            and isinstance(node.bases[0], ast.Name)
            and node.bases[0].id == "AppConfig"
        ):
            for child in node.body:
                if isinstance(child, ast.Assign) and len(child.targets) == 1:
                    node_id = child.targets[0].id
                    if node_id == "name":
                        self._app_name = self.maybe_str(child.value)
                    elif node_id == "label":
                        self._app_label = self.maybe_str(child.value)


def handle_file(apps, path):
    if os.path.basename(path) != "apps.py":
        return
    with open(path, "rb") as f:
        content = f.read()
    try:
        tree = ast.parse(content, filename=path)
    except SyntaxError:
        return

    visitor = DjangoAppDetector()
    visitor.visit(tree)

    if visitor.app_name:
        apps[visitor.app_label] = visitor.app_name


def main(paths):
    apps = {}  # label -> full Python module path
    for path in paths:
        if os.path.isfile(path):
            handle_file(apps, path)
        elif os.path.isdir(path):
            for dirpath, _, filenames in os.walk(path):
                for filename in filenames:
                    handle_file(apps, os.path.join(dirpath, filename))

    # We have to be careful to set the encoding explicitly and write raw bytes ourselves.
    buffer = sys.stdout if sys.version_info[0:2] == (2, 7) else sys.stdout.buffer
    buffer.write(json.dumps(apps).encode("utf8"))


if __name__ == "__main__":
    main(sys.argv[1:])
