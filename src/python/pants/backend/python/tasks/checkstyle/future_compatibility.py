# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import ast

from pants.backend.python.tasks.checkstyle.common import CheckstylePlugin
from pants.subsystem.subsystem import Subsystem


# Warn on non 2.x/3.x compatible symbols:
#   - basestring
#   - xrange
#
# Methods:
#   - .iteritems
#   - .iterkeys
#   - .itervalues
#
# Comprehension builtins
#   - filter
#   - map
#   - range
#
#   => Make sure that these are not assigned.
#   Warn if they are assigned or returned directly from functions
#
# Class internals:
#   __metaclass__
class FutureCompatibilitySubsystem(Subsystem):
  options_scope = 'pycheck-future-compat'

  @classmethod
  def register_options(cls, register):
    super(FutureCompatibilitySubsystem, cls).register_options(register)
    register('--skip', default=False, action='store_true',
             help='If enabled, skip this style checker.')


class FutureCompatibility(CheckstylePlugin):
  """Warns about behavior that will likely break when moving to Python 3.x"""
  BAD_ITERS = frozenset(('iteritems', 'iterkeys', 'itervalues'))
  BAD_FUNCTIONS = frozenset(('xrange',))
  BAD_NAMES = frozenset(('basestring', 'unicode'))
  subsystem = FutureCompatibilitySubsystem

  def nits(self):
    for call in self.iter_ast_types(ast.Call):
      if isinstance(call.func, ast.Attribute):
        # Not a perfect solution since a user could have a dictionary named six or something similar
        #   However, this should catch most cases where people are using iter* without six.
        if call.func.attr in self.BAD_ITERS and getattr(call.func.value, 'id', '') != 'six':
          yield self.error(
            'T602',
            '{attr} disappears in Python 3.x.  Use non-iter instead.'.format(attr=call.func.attr),
            call)
      elif isinstance(call.func, ast.Name):
        if call.func.id in self.BAD_FUNCTIONS:
          yield self.error(
            'T603',
            'Please avoid {func_id} as it disappears in Python 3.x.'.format(func_id=call.func.id),
            call)
    for name in self.iter_ast_types(ast.Name):
      if name.id in self.BAD_NAMES:
        yield self.error(
            'T604', 'Please avoid {id} as it disappears in Python 3.x.'.format(id=name.id), name)
    for class_def in self.iter_ast_types(ast.ClassDef):
      for node in class_def.body:
        if not isinstance(node, ast.Assign):
          continue
        for name in node.targets:
          if not isinstance(name, ast.Name):
            continue
          if name.id == '__metaclass__':
            yield self.warning('T605',
                'This metaclass style is deprecated and gone entirely in Python 3.x.', name)
