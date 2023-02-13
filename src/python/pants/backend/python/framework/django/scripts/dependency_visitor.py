# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
# -*- coding: utf-8 -*-

# NB: This must be compatible with Python 2.7 and 3.5+.
# NB: Expects a json file at "./apps.json" mapping Django app labels to their package paths.
# NB: An easy way to debug this is to invoke it directly on a file.
#   E.g.
#   $ PYTHONPATH=src/python VISITOR_CLASSNAMES=pants.backend.python.framework.django.scripts\
#     .dependency_visitor.DjangoDependencyVisitor \
#     python src/python/pants/backend/python/dependency_inference/scripts/main.py FILE

from __future__ import print_function, unicode_literals

import ast
import json

from pants.backend.python.dependency_inference.scripts.dependency_visitor_base import (
    DependencyVisitorBase,
)


class DjangoDependencyVisitor(DependencyVisitorBase):
    def __init__(self, *args, **kwargs):
        super(DjangoDependencyVisitor, self).__init__(*args, **kwargs)
        with open("apps.json", "r") as fp:
            self._apps = json.load(fp)

    def visit_ClassDef(self, node):
        # Detect `class Migration(migrations.Migration):`
        if (
            node.name == "Migration"
            and len(node.bases) > 0
            and node.bases[0].value.id == "migrations"
            and node.bases[0].attr == "Migration"
        ):
            # Detect `dependencies = [("app1", "migration1"), ("app2", "migration2")]`
            for child in node.body:
                if (
                    isinstance(child, ast.Assign)
                    and len(child.targets) == 1
                    and child.targets[0].id == "dependencies"
                    and isinstance(child.value, (ast.Tuple, ast.List))
                ):
                    for elt in child.value.elts:
                        if isinstance(elt, (ast.Tuple, ast.List)) and len(elt.elts) == 2:
                            app = self.maybe_str(elt.elts[0])
                            migration = self.maybe_str(elt.elts[1])
                            if app is not None and migration is not None:
                                pkg = self._apps.get(app)
                                if pkg:
                                    module = "{}.migrations.{}".format(pkg, migration)
                                    self.add_weak_import(module, elt.lineno)

        self.generic_visit(node)
