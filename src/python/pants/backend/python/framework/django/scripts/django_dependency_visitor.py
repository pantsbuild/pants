# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
# -*- coding: utf-8 -*-

# NB: This must be compatible with Python 2.7 and 3.5+.
# NB: An easy way to debug this is to invoke it directly on a file.
#   E.g.
#   $ PYTHONPATH=src/python VISITOR_CLASSNAMES=pants.backend.python.framework.django.scripts\
#     .django_dependency_visitor.DjangoDependencyVisitor \
#     python src/python/pants/backend/python/dependency_inference/scripts/main.py FILE

from __future__ import print_function, unicode_literals

import ast

from pants.backend.python.dependency_inference.scripts.dependency_visitor_base import (
    DependencyVisitorBase,
)


class DjangoDependencyVisitor(DependencyVisitorBase):
    def __init__(self, *args, **kwargs):
        super(DjangoDependencyVisitor, self).__init__(*args, **kwargs)
        self._in_migration = False

    def visit_ClassDef(self, node):
        # Detect `class Migration(migrations.Migration):`
        if (
            node.name == "Migration"
            and len(node.bases) > 0
            and node.bases[0].value.id == "migrations"
            and node.bases[0].attr == "Migration"
        ):
            self._in_migration = True
        self.generic_visit(node)
        self._in_migration = False

    def visit_Assign(self, node):
        if self._in_migration and len(node.targets) > 0 and node.targets[0].id == "dependencies":
            if isinstance(node.value, (ast.Tuple, ast.List)):
                for elt in node.value.elts:
                    if isinstance(elt, (ast.Tuple, ast.List)) and len(elt.elts) == 2:
                        app = self.maybe_str(elt.elts[0])
                        migration = self.maybe_str(elt.elts[1])
                        if app is not None and migration is not None:
                            module = "{}.migrations.{}".format(app, migration)
                            self.add_weak_import(module, node.lineno)
        self.generic_visit(node)
