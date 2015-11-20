# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import ast
import textwrap

from pants_test.contrib.python.checks.tasks.checkstyle.plugin_test_base import \
  CheckstylePluginTestBase

from pants.contrib.python.checks.tasks.checkstyle.common import Nit
from pants.contrib.python.checks.tasks.checkstyle.import_order import ImportOrder, ImportType


IMPORT_CHUNKS = {
  ImportType.STDLIB: """
  import ast
  from collections import namedtuple
  import io
  """,

  ImportType.TWITTER: """
  from twitter.common import app
  from twitter.common.dirutil import (
      safe_mkdtemp,
      safe_open,
      safe_rmtree)
  """,

  ImportType.GEN: """
  from gen.twitter.aurora.ttypes import TwitterTaskInfo
  """,

  ImportType.PACKAGE: """
  from .import_order import (
      ImportOrder,
      ImportType
  )
  """,

  ImportType.THIRD_PARTY: """
  from kazoo.client import KazooClient
  import zookeeper
  """,
}


def strip_newline(stmt):
  return textwrap.dedent('\n'.join(filter(None, stmt.splitlines())))


def stitch_chunks(newlines, *chunks):
  return ('\n' * newlines).join([strip_newline(IMPORT_CHUNKS.get(c)) for c in chunks])


class ImportOrderTest(CheckstylePluginTestBase):
  plugin_type = ImportOrder

  def get_import_chunk_types(self, import_type):
    chunks = list(self.get_plugin(IMPORT_CHUNKS[import_type]).iter_import_chunks())
    self.assertEqual(1, len(chunks))
    return tuple(map(type, chunks[0]))

  def test_classify_import_chunks(self):
    self.assertEqual((ast.Import, ast.ImportFrom, ast.Import),
                     self.get_import_chunk_types(ImportType.STDLIB))
    self.assertEqual((ast.ImportFrom, ast.ImportFrom),
                     self.get_import_chunk_types(ImportType.TWITTER))
    self.assertEqual((ast.ImportFrom,),
                     self.get_import_chunk_types(ImportType.GEN))
    self.assertEqual((ast.ImportFrom,),
                     self.get_import_chunk_types(ImportType.PACKAGE))
    self.assertEqual((ast.ImportFrom, ast.Import),
                     self.get_import_chunk_types(ImportType.THIRD_PARTY))

  def test_classify_import(self):
    for import_type, chunk in IMPORT_CHUNKS.items():
      io = self.get_plugin(chunk)
      import_chunks = list(io.iter_import_chunks())
      self.assertEqual(1, len(import_chunks))
      module_types, chunk_errors = io.classify_imports(import_chunks[0])
      self.assertEqual(1, len(module_types))
      self.assertEqual(import_type, module_types.pop())
      self.assertEqual([], chunk_errors)

  PAIRS = (
    (ImportType.STDLIB, ImportType.TWITTER),
    (ImportType.TWITTER, ImportType.GEN),
    (ImportType.PACKAGE, ImportType.THIRD_PARTY),
  )

  def test_pairwise_classify(self):
    for first, second in self.PAIRS:
      io = self.get_plugin(stitch_chunks(1, first, second))
      import_chunks = list(io.iter_import_chunks())
      self.assertEqual(2, len(import_chunks))

      module_types, chunk_errors = io.classify_imports(import_chunks[0])
      self.assertEqual(1, len(module_types))
      self.assertEqual(0, len(chunk_errors))
      self.assertEqual(first, module_types.pop())

      module_types, chunk_errors = io.classify_imports(import_chunks[1])
      self.assertEqual(1, len(module_types))
      self.assertEqual(0, len(chunk_errors))
      self.assertEqual(second, module_types.pop())

    for second, first in self.PAIRS:
      io = self.get_plugin(stitch_chunks(1, first, second))
      import_chunks = list(io.iter_import_chunks())
      self.assertEqual(2, len(import_chunks))
      nits = list(io.nits())
      self.assertEqual(1, len(nits))
      self.assertEqual('T406', nits[0].code)
      self.assertEqual(Nit.ERROR, nits[0].severity)

  def test_multiple_imports_error(self):
    io = self.get_plugin(stitch_chunks(0, ImportType.STDLIB, ImportType.TWITTER))
    import_chunks = list(io.iter_import_chunks())
    self.assertEqual(1, len(import_chunks))

    module_types, chunk_errors = io.classify_imports(import_chunks[0])
    self.assertEqual(1, len(chunk_errors))
    self.assertEqual('T405', chunk_errors[0].code)
    self.assertEqual(Nit.ERROR, chunk_errors[0].severity)
    self.assertItemsEqual([ImportType.STDLIB, ImportType.TWITTER], module_types)

    io = self.get_plugin("""
      import io, pkg_resources
    """)
    import_chunks = list(io.iter_import_chunks())
    self.assertEqual(1, len(import_chunks))
    module_types, chunk_errors = io.classify_imports(import_chunks[0])
    self.assertEqual(3, len(chunk_errors))
    self.assertItemsEqual(['T403', 'T405', 'T402'],
                          [chunk_error.code for chunk_error in chunk_errors])
    self.assertItemsEqual([ImportType.STDLIB, ImportType.THIRD_PARTY], module_types)

  def test_import_lexical_order(self):
    imp = """
      from twitter.common.dirutil import safe_rmtree, safe_mkdtemp
    """
    self.assertNit(imp, 'T401')

  def test_import_wildcard(self):
    imp = """
      from twitter.common.dirutil import *
    """
    self.assertNit(imp, 'T400')
