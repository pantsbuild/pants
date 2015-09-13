# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import ast

from pants.backend.python.tasks.checkstyle.common import CheckstylePlugin
from pants.subsystem.subsystem import Subsystem


class NewStyleClassesSubsystem(Subsystem):
  options_scope = 'pycheck-newstyle-classes'

  @classmethod
  def register_options(cls, register):
    super(NewStyleClassesSubsystem, cls).register_options(register)
    register('--skip', default=False, action='store_true',
             help='If enabled, skip this style checker.')


class NewStyleClasses(CheckstylePlugin):
  """Enforce the use of new-style classes."""
  subsystem = NewStyleClassesSubsystem

  def nits(self):
    for class_def in self.iter_ast_types(ast.ClassDef):
      if not class_def.bases:
        yield self.error('T606', 'Classes must be new-style classes.', class_def)
