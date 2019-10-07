# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import ast

from pants.contrib.python.checks.checker.common import CheckstylePlugin


class NewStyleClasses(CheckstylePlugin):
    """Enforce the use of new-style classes."""

    @classmethod
    def name(cls):
        return "newstyle-classes"

    def nits(self):
        for class_def in self.iter_ast_types(ast.ClassDef):
            if not class_def.bases:
                yield self.error("T606", "Classes must be new-style classes.", class_def)
