# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
# -*- coding: utf-8 -*-

# NB: This must be compatible with Python 2.7 and 3.5+.
# NB: An easy way to debug this is to just invoke it on a file.
#   E.g.
#   $ PYTHONPATH=src/python STRING_IMPORTS=y python \
#     src/python/pants/backend/python/dependency_inference/scripts/main.py FILE
#   Or
#   $ ./pants --no-python-infer-imports run \
#     src/python/pants/backend/python/dependency_inference/scripts/main.py -- FILE

from __future__ import print_function, unicode_literals

import ast
import importlib
import json
import os
import sys
from io import open

from pants.backend.python.dependency_inference.scripts.dependency_visitor_base import (
    FoundDependencies,
)


def main(filename):
    with open(filename, "rb") as f:
        content = f.read()
    try:
        tree = ast.parse(content, filename=filename)
    except SyntaxError:
        return

    package_parts = os.path.dirname(filename).split(os.path.sep)
    visitor_classnames = os.environ.get(
        "VISITOR_CLASSNAMES",
        "pants.backend.python.dependency_inference.scripts.general_dependency_visitor.GeneralDependencyVisitor",
    ).split("|")
    visitors = []
    found_dependencies = FoundDependencies()
    for visitor_classname in visitor_classnames:
        module_name, _, class_name = visitor_classname.rpartition(".")
        module = importlib.import_module(module_name)
        visitor_cls = getattr(module, class_name)
        visitors.append(visitor_cls(found_dependencies, package_parts, content))
    for visitor in visitors:
        visitor.visit(tree)

    # We have to be careful to set the encoding explicitly and write raw bytes ourselves.
    # See below for where we explicitly decode.
    buffer = sys.stdout if sys.version_info[0:2] == (2, 7) else sys.stdout.buffer

    # N.B. Start with weak and `update` with definitive so definite "wins"
    imports_result = {
        module_name: {"lineno": lineno, "weak": True}
        for module_name, lineno in found_dependencies.weak_imports.items()
    }
    imports_result.update(
        {
            module_name: {"lineno": lineno, "weak": False}
            for module_name, lineno in found_dependencies.strong_imports.items()
        }
    )

    buffer.write(
        json.dumps(
            {
                "imports": imports_result,
                "assets": sorted(found_dependencies.assets),
            }
        ).encode("utf8")
    )


if __name__ == "__main__":
    main(sys.argv[1])
