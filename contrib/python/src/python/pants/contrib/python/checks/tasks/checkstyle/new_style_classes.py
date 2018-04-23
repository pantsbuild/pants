# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import ast

from pants.contrib.python.checks.tasks.checkstyle.common import CheckstylePlugin


class NewStyleClasses(CheckstylePlugin):
  """Enforce the use of new-style classes."""

  def __init__(self, options, python_file):
    super(NewStyleClasses, self).__init__(options, python_file)

    special_decorators = options.special_decorators
    if not isinstance(special_decorators, list):
      raise TypeError(
        "NewStyleClasses special decorators must be a list (was: {!r})."
        .format(special_decorators))
    invalid_decorators = []
    for decorator in special_decorators:
      if not isinstance(decorator, str):
        invalid_decorators.append(
          "decorator name was not a string: {!r}"
          .format(decorator))
    if invalid_decorators:
      raise TypeError("NewStyleClasses special decorators were invalid:\n{}"
                      .format('\n'.join(invalid_decorators)))

    self._special_decorators = frozenset(special_decorators)

  def nits(self):
    for class_def in self.iter_ast_types(ast.ClassDef):
      if not class_def.bases:
        decorator_ids = frozenset(
          call.func.id for call in class_def.decorator_list)
        if not decorator_ids.intersection(self._special_decorators):
          yield self.error(
            'T606', 'Classes must be new-style classes.', class_def)
