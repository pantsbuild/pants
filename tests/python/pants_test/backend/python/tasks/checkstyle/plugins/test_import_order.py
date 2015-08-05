# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import ast
import textwrap

from pants.backend.python.tasks.checkstyle.common import Nit, PythonFile
from pants.backend.python.tasks.import_order import ImportOrder, ImportType


def strip_newline(stmt):
  return textwrap.dedent('\n'.join(filter(None, stmt.splitlines())))


IMPORT_CHUNKS = {
  ImportType.STDLIB: strip_newline("""
  import ast
  from collections import namedtuple
  import time
  """),

  ImportType.TWITTER: strip_newline("""
  from twitter.common import app
  from twitter.common.dirutil import (
      safe_mkdtemp,
      safe_open,
      safe_rmtree)
  """),

  ImportType.GEN: strip_newline("""
  from gen.twitter.aurora.ttypes import TwitterTaskInfo
  """),

  ImportType.PACKAGE: strip_newline("""
  from .import_order import (
      ImportOrder,
      ImportType
  )
  """),

  ImportType.THIRD_PARTY: strip_newline("""
  from kazoo.client import KazooClient
  import zookeeper
  """),
}


def stitch_chunks(newlines, *chunks):
  stitched = ('\n' * newlines).join(map(IMPORT_CHUNKS.get, chunks))
  return stitched


def get_import_chunk_types(import_type):
  chunks = list(ImportOrder(PythonFile(IMPORT_CHUNKS[import_type])).iter_import_chunks())
  assert len(chunks) == 1
  return tuple(map(type, chunks[0]))


def test_classify_import_chunks():
  assert get_import_chunk_types(ImportType.STDLIB) == (ast.Import, ast.ImportFrom, ast.Import)
  assert get_import_chunk_types(ImportType.TWITTER) == (ast.ImportFrom, ast.ImportFrom)
  assert get_import_chunk_types(ImportType.GEN) == (ast.ImportFrom,)
  assert get_import_chunk_types(ImportType.PACKAGE) == (ast.ImportFrom,)
  assert get_import_chunk_types(ImportType.THIRD_PARTY) == (ast.ImportFrom, ast.Import)


def test_classify_import():
  for import_type, chunk in IMPORT_CHUNKS.items():
    io = ImportOrder(PythonFile(chunk))
    import_chunks = list(io.iter_import_chunks())
    assert len(import_chunks) == 1
    module_types, chunk_errors = io.classify_imports(import_chunks[0])
    assert len(module_types) == 1
    assert module_types.pop() == import_type
    assert chunk_errors == []


PAIRS = (
  (ImportType.STDLIB, ImportType.TWITTER),
  (ImportType.TWITTER, ImportType.GEN),
  (ImportType.PACKAGE, ImportType.THIRD_PARTY),
)


def test_pairwise_classify():
  for first, second in PAIRS:
    io = ImportOrder(PythonFile(stitch_chunks(1, first, second)))
    import_chunks = list(io.iter_import_chunks())
    assert len(import_chunks) == 2

    module_types, chunk_errors = io.classify_imports(import_chunks[0])
    assert len(module_types) == 1
    assert len(chunk_errors) == 0
    assert module_types.pop() == first

    module_types, chunk_errors = io.classify_imports(import_chunks[1])
    assert len(module_types) == 1
    assert len(chunk_errors) == 0
    assert module_types.pop() == second

  for second, first in PAIRS:
    io = ImportOrder(PythonFile(stitch_chunks(1, first, second)))
    import_chunks = list(io.iter_import_chunks())
    assert len(import_chunks) == 2
    nits = list(io.nits())
    assert len(nits) == 1
    assert nits[0].code == 'T406'
    assert nits[0].severity == Nit.ERROR


def test_multiple_imports_error():
  io = ImportOrder(PythonFile(stitch_chunks(0, ImportType.STDLIB, ImportType.TWITTER)))
  import_chunks = list(io.iter_import_chunks())
  assert len(import_chunks) == 1

  module_types, chunk_errors = io.classify_imports(import_chunks[0])
  assert len(chunk_errors) == 1
  assert chunk_errors[0].code == 'T405'
  assert chunk_errors[0].severity == Nit.ERROR
  assert set(module_types) == set([ImportType.STDLIB, ImportType.TWITTER])

  io = ImportOrder(PythonFile('import time, pkg_resources'))
  import_chunks = list(io.iter_import_chunks())
  assert len(import_chunks) == 1
  module_types, chunk_errors = io.classify_imports(import_chunks[0])
  assert len(chunk_errors) == 3
  assert set(chunk_error.code for chunk_error in chunk_errors) == set(['T403', 'T405', 'T402'])
  assert set(module_types) == set([ImportType.STDLIB, ImportType.THIRD_PARTY])


def test_import_lexical_order():
  io = ImportOrder(PythonFile.from_statement("""
    from twitter.common.dirutil import safe_rmtree, safe_mkdtemp
  """))
  nits = list(io.nits())
  assert len(nits) == 1
  assert nits[0].code == 'T401'
  assert nits[0].severity == Nit.ERROR


def test_import_wildcard():
  io = ImportOrder(PythonFile.from_statement("""
    from twitter.common.dirutil import *
  """))
  nits = list(io.nits())
  assert len(nits) == 1
  assert nits[0].code == 'T400'
  assert nits[0].severity == Nit.ERROR
