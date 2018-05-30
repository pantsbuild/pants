# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import argparse
import ast
import sys

from pants.contrib.python.checks.tasks.checkstyleV2.common import CheckstylePlugin, PythonFile


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
    nits = 0
    for pf in self.python_files:
      for class_def in self.iter_ast_types(ast.ClassDef, pf):
        for node in self.iter_class_accessors(class_def):
          nits += 1
          nit = self.warning('T800',
              'Instead of {name}.{attr} use self.{attr} or cls.{attr} with instancemethods and '
              'classmethods respectively.'.format(name=class_def.name, attr=node.attr), pf)
          print('{nit}\n'.format(nit=nit))
    return nits

if __name__ == "__main__":
  parser = argparse.ArgumentParser(
    description='Style checker that enforces recommendations for accessing class attributes.',
    formatter_class=argparse.ArgumentDefaultsHelpFormatter)
  parser.add_argument(
    '--severity', default='COMMENT', help='Only messages at this severity or higher are logged. [COMMENT WARNING ERROR].', type=str)
  parser.add_argument(
    '--strict',
    default=False,
    help='If enabled, have non-zero exit status for any nit at WARNING or higher.',
    type=bool,
  )

  options, _ = parser.parse_known_args()
  files = []
  for fname in sys.argv[1:]:
    files.append(PythonFile.parse(fname))
  if files:
    checker = ClassFactoring(options, files)
    fail_count = checker.nits()
    print('Fails for classfactoring: {}'.format(fail_count))
