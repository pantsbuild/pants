# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import ast

from pants.backend.python.tasks.checkstyle.checker import PythonCheckStyleTask
from pants.backend.python.tasks.checkstyle.common import CheckstylePlugin


class ClassFactoring(CheckstylePlugin):
  """Enforces recommendations for accessing class attributes.

  Within classes, if you see:
    class Distiller(object):
      CONSTANT = "Foo"
      def foo(self, value):
         return os.path.join(Distiller.CONSTANT, value)

  recommend using self.CONSTANT instead of Distiller.CONSTANT as otherwise
  it makes subclassing impossible."""

  def iter_class_accessors(self, class_node):
    for node in ast.walk(class_node):
      if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and (
          node.value.id == class_node.name):
        yield node

  def nits(self):
    for class_def in self.iter_ast_types(ast.ClassDef):
      for node in self.iter_class_accessors(class_def):
        yield self.warning('T800',
            'Instead of %s.%s use self.%s or cls.%s with instancemethods and classmethods '
            'respectively.' % (class_def.name, node.attr, node.attr, node.attr),
            node)


class ClassFactoring(PythonCheckStyleTask):
  def __init__(self, *args, **kwargs):
    super(ClassFactoring, self).__init__(*args, **kwargs)
    self._checker = ClassFactoring()
    self._name = 'ClassFactoring'

  @classmethod
  def register_options(cls, register):
    super(ClassFactoring, cls).register_options(register)
    register('--args', action='append', help='Run with these extra args to main().')
    register('--severity', default='COMMENT', type=str,
             help='Only messages at this severity or higher are logged. [COMMENT WARNING ERROR].')
    register('--strict', default=False, action='store_true',
             help='If enabled, have non-zero exit status for any nit at WARNING or higher.')
    register('--skip', default=False, action='store_true',
             help='If enabled, skip this style checker.')
    register('--suppress', type=str, default=None,
             help='Takes a XML file where specific rules on specific files will be skipped.')
    register('--fail', default=True, action='store_true',
             help='Prevent test failure but still produce output for problems.')
