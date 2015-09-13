# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import ast

from pants.backend.python.tasks.checkstyle.common import CheckstylePlugin
from pants.subsystem.subsystem import Subsystem


class ClassFactoringSubsystem(Subsystem):
  options_scope = 'pycheck-class-factoring'

  @classmethod
  def register_options(cls, register):
    super(ClassFactoringSubsystem, cls).register_options(register)
    register('--skip', default=False, action='store_true',
             help='If enabled, skip this style checker.')


class ClassFactoring(CheckstylePlugin):
  """Enforces recommendations for accessing class attributes.

  Within classes, if you see:
    class Distiller(object):
      CONSTANT = "Foo"
      def foo(self, value):
         return os.path.join(Distiller.CONSTANT, value)

  recommend using self.CONSTANT instead of Distiller.CONSTANT as otherwise
  it makes subclassing impossible."""
  subsystem = ClassFactoringSubsystem

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
