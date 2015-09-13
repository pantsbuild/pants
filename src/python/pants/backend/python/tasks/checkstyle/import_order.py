# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import ast
import os
from distutils import sysconfig

from pants.backend.python.tasks.checkstyle.common import CheckstylePlugin
from pants.subsystem.subsystem import Subsystem


class ImportType(object):
  """Enforce a consistent import order.

  Imports are currently grouped into five separate groups:
    stdlib
    twitter
    gen
    package-local
    third-party

  Imports should be in this order and separated by a single space.
  """

  STDLIB = 1
  TWITTER = 2
  GEN = 3
  PACKAGE = 4
  THIRD_PARTY = 5
  UNKNOWN = 0

  NAMES = {
    UNKNOWN: 'unknown',
    STDLIB: 'stdlib',
    TWITTER: 'twitter',
    GEN: 'gen',
    PACKAGE: 'package',
    THIRD_PARTY: '3rdparty'
  }

  @classmethod
  def order_names(cls, import_order):
    return ' '.join(cls.NAMES.get(import_id, 'unknown') for import_id in import_order)


class ImportOrderSubsystem(Subsystem):
  options_scope = 'pycheck-import-order'

  @classmethod
  def register_options(cls, register):
    super(ImportOrderSubsystem, cls).register_options(register)
    register('--skip', default=False, action='store_true',
             help='If enabled, skip this style checker.')


class ImportOrder(CheckstylePlugin):
  # TODO(wickman)
  #   - Warn if a package is marked as a 3rdparty but it's actually a package
  #     in the current working directory that should be a package-absolute
  #     import (i.e. from __future__ import absolute_imports)

  STANDARD_LIB_PATH = os.path.realpath(sysconfig.get_python_lib(standard_lib=1))
  subsystem = ImportOrderSubsystem

  @classmethod
  def extract_import_modules(cls, node):
    if isinstance(node, ast.Import):
      return [alias.name for alias in node.names]
    elif isinstance(node, ast.ImportFrom):
      return [node.module]
    return []

  @classmethod
  def classify_import(cls, node, name):
    if name == '' or (isinstance(node, ast.ImportFrom) and node.level > 0):
      return ImportType.PACKAGE
    if name.startswith('twitter.'):
      return ImportType.TWITTER
    if name.startswith('gen.'):
      return ImportType.GEN
    try:
      module = __import__(name)
    except ImportError:
      return ImportType.THIRD_PARTY
    if (not hasattr(module, '__file__') or
          os.path.realpath(module.__file__).startswith(cls.STANDARD_LIB_PATH)):
      return ImportType.STDLIB
    # Assume anything we can't classify is third-party
    return ImportType.THIRD_PARTY

  @classmethod
  def classify_import_node(cls, node):
    return set(cls.classify_import(node, module_name)
               for module_name in cls.extract_import_modules(node))

  def import_errors(self, node):
    errors = []
    if isinstance(node, ast.ImportFrom):
      if len(node.names) == 1 and node.names[0].name == '*':
        errors.append(self.error('T400', 'Wildcard imports are not allowed.', node))
      names = [alias.name.lower() for alias in node.names]
      if names != sorted(names):
        errors.append(self.error('T401', 'From import must import names in lexical order.', node))
    if isinstance(node, ast.Import):
      if len(node.names) > 1:
        errors.append(self.error('T402',
            'Absolute import statements should only import one module at a time.', node))
    return errors

  def classify_imports(self, chunk):
    """
      Possible import statements:

      import name
      from name import subname
      from name import subname1 as subname2
      from name import *
      from name import tuple

      AST representations:

      ImportFrom:
         module=name
         names=[alias(name, asname), ...]
                    name can be '*'

      Import:
        names=[alias(name, asname), ...]

      Imports are classified into 5 classes:
        stdlib      => Python standard library
        twitter.*   => Twitter internal / standard library
        gen.*       => Thrift gen namespaces
        .*          => Package-local imports
        3rdparty    => site-packages or third party

      classify_imports classifies the import into one of these forms.
    """
    errors = []
    all_module_types = set()
    for node in chunk:
      errors.extend(self.import_errors(node))
      module_types = self.classify_import_node(node)
      if len(module_types) > 1:
        errors.append(self.error(
          'T403',
          'Import statement imports from multiple module types: {types}.'.format(
            types=ImportType.order_names(module_types)),
          node))
      if ImportType.UNKNOWN in module_types:
        errors.append(self.warning('T404', 'Unclassifiable import.', node))
      all_module_types.update(module_types)
    if len(chunk) > 0 and len(all_module_types) > 1:
      errors.append(
          self.error(
            'T405',
            'Import block starting here contains imports '
            'from multiple module types: {types}.'.format(
              types=ImportType.order_names(all_module_types)),
            chunk[0].lineno))
    return all_module_types, errors

  # TODO(wickman) Classify imports within top-level try/except ImportError blocks.
  def iter_import_chunks(self):
    """Iterate over space-separated import chunks in a file."""
    chunk = []
    last_line = None
    for leaf in self.python_file.tree.body:
      if isinstance(leaf, (ast.Import, ast.ImportFrom)):
        # we've seen previous imports but this import is not in the same chunk
        if last_line and leaf.lineno != last_line[1]:
          yield chunk
          chunk = [leaf]
        # we've either not seen previous imports or this is part of the same chunk
        elif not last_line or last_line and leaf.lineno == last_line[1]:
          chunk.append(leaf)
        last_line = self.python_file.logical_lines[leaf.lineno]
    if chunk:
      yield chunk

  def nits(self):
    errors = []
    module_order = []

    for chunk in self.iter_import_chunks():
      module_types, chunk_errors = self.classify_imports(chunk)
      errors.extend(chunk_errors)
      module_order.append(list(module_types))

    numbered_module_order = []
    for modules in module_order:
      if len(modules) > 0:
        if modules[0] is not ImportType.UNKNOWN:
          numbered_module_order.append(modules[0])

    if numbered_module_order != sorted(numbered_module_order):
      errors.append(self.error('T406',
          'Out of order import chunks: Got {} and expect {}.'.format(
          ImportType.order_names(numbered_module_order),
          ImportType.order_names(sorted(numbered_module_order))),
          self.python_file.tree))

    return errors
