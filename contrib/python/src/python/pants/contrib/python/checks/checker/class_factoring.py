# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import ast

from pants.contrib.python.checks.checker.common import CheckstylePlugin


class ClassFactoring(CheckstylePlugin):
  """Enforces recommendations for accessing class attributes.

  Within classes, if you see:
    class Distiller(object):
      CONSTANT = "Foo"
      def foo(self, value):
         return os.path.join(Distiller.CONSTANT, value)

  recommend using self.CONSTANT instead of Distiller.CONSTANT as otherwise
  it makes subclassing impossible."""

  @classmethod
  def name(cls):
    return 'class-factoring'

  def iter_class_accessors(self, class_node):
    for node in ast.walk(class_node):
      if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and (
          node.value.id == class_node.name):
        yield node

  def nits(self):
    for class_def in self.iter_ast_types(ast.ClassDef):
      for node in self.iter_class_accessors(class_def):
        yield self.warning('T800',
            'Instead of {name}.{attr} use self.{attr} or cls.{attr} with instancemethods and '
            'classmethods respectively.'.format(name=class_def.name, attr=node.attr))
