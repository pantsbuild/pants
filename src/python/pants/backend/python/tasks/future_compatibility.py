# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import ast

from pants.backend.python.tasks.checkstyle.common import CheckstylePlugin


# Warn on non 2.x/3.x compatible symbols:
#   - basestring
#   - xrange
#
# Methods:
#   - .iteritems
#   - .iterkeys
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




class FutureCompatibility(CheckstylePlugin):
  """Warns about behavior that will likely break when moving to Python 3.x"""
  BAD_ITERS = frozenset(('iteritems', 'iterkeys', 'itervalues'))
  BAD_FUNCTIONS = frozenset(('xrange',))
  BAD_NAMES = frozenset(('basestring', 'unicode'))

  def nits(self):
    for call in self.iter_ast_types(ast.Call):
      if isinstance(call.func, ast.Attribute):
        if call.func.attr in self.BAD_ITERS:
          yield self.error(
              'T602', '%s disappears in Python 3.x.  Use non-iter instead.' % call.func.attr, call)
      elif isinstance(call.func, ast.Name):
        if call.func.id in self.BAD_FUNCTIONS:
          yield self.error(
              'T603', 'Please avoid %s as it disappears in Python 3.x.' % call.func.id, call)
    for name in self.iter_ast_types(ast.Name):
      if name.id in self.BAD_NAMES:
        yield self.error(
            'T604', 'Please avoid %s as it disappears in Python 3.x.' % name.id, name)
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
