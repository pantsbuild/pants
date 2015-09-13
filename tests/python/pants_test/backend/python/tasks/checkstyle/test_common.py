# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import ast
import textwrap
from pprint import pprint

import pytest

from pants.backend.python.tasks.checkstyle.common import (CheckstylePlugin, Nit, OffByOneList,
                                                          PythonFile)


FILE_TEXT = """
  import ast
  from os.path import (
      join,
      split,
  )

  import zookeeper


  class Keeper(object):
    def __init__(self):
      self._session = None

    def session(self):
      return self._session
"""


class MinimalCheckstylePlugin(CheckstylePlugin):
  """Minimal Checkstyle plugin used to test PythonFile interactions in Plugin"""

  def nits(self):
    return []


@pytest.fixture
def test_statement():
  """Pytest Fixture to create a test python file from statement"""
  return '\n'.join(textwrap.dedent(FILE_TEXT).splitlines()[1:])


@pytest.fixture
def test_python_file():
  """Pytest Fixture to create a test python file from statement"""
  return PythonFile(test_statement(), 'keeper.py')


@pytest.fixture
def check_plugin():
  return MinimalCheckstylePlugin(test_python_file())


def test_python_file_name(test_python_file):
  """Test that filename attrib is getting set properly"""
  assert test_python_file.filename == 'keeper.py'


def test_python_file_logical_lines(test_python_file):
  """Test that we get back logical lines we expect"""
  assert test_python_file.logical_lines == {
    1: (1, 2, 0),  # import ast
    2: (2, 6, 0),  # from os.path import (", "    join,", "    split,", ")
    7: (7, 8, 0),  # import zookeeper
    10: (10, 11, 0),  # class Keeper(object):
    11: (11, 12, 2),  # def __init__(self):
    12: (12, 13, 4),  # self._session = None
    14: (14, 15, 2),  # def session(self):
    15: (15, 16, 4),  # return self._session
  }


def test_python_file_index_offset(test_python_file):
  """Test that we can not index into a python file with 0

  PythonFile is offset by one to match users expectations
  with file line numbering.
  """
  with pytest.raises(IndexError):
    test_python_file[0]


def test_python_file_exceeds_index(test_statement):
  """Test that we get an Index error when we exceed the line number"""
  test_python_file = PythonFile(test_statement, 'keeper.py')
  with pytest.raises(IndexError):
    test_python_file[len(test_statement.splitlines()) + 1]


def test_line_retrieval(test_python_file):
  """Test that we get lines correctly when accessed by index"""
  expected = [
    ["import ast"],
    ["from os.path import (", "    join,", "    split,", ")"],
    ["    join,"],
    ["    split,"],
    [")"],
    [""],
    ["import zookeeper"],
    [""],
    [""],
    ["class Keeper(object):"],
    ["  def __init__(self):"],
    ["    self._session = None"],
    [""],
    ["  def session(self):"],
    ["    return self._session"],
  ]
  assert expected == [test_python_file[x] for x in range(1,16)], \
    "Expected:\n{} Actual:\n{}".format(
      pprint(expected), pprint([test_python_file[x] for x in range(1,16)]))


def test_rejoin(test_statement):
  """Test that when we stitch the PythonFile back up we get back our input"""
  python_file = PythonFile(test_statement, 'keeper.py')
  assert '\n'.join(python_file) == test_statement


def test_off_by_one_enumeration(test_statement):
  """Test that enumerate is offset by one"""
  python_file = PythonFile(test_statement, 'keeper.py')
  assert list(python_file.enumerate()) == list(enumerate(test_statement.splitlines(), 1))


@pytest.mark.parametrize("ln_test_input,ln_test_expected", [
  (['A123', 'You have a terrible taste in libraries'], None),
  (['A123', 'You have a terrible taste in libraries', 7], '007'),
  (['A123', 'You have a terrible taste in libraries', 2], '002-005'),
])
def test_line_number_return(check_plugin, ln_test_input, ln_test_expected):
  error = check_plugin.error(*ln_test_input)
  assert error.line_number == ln_test_expected, 'Unexpected Line number found'


@pytest.mark.parametrize("code_test_input,code_test_expected", [
  (['A123', 'You have a terrible taste in libraries'], 'A123'),
  (['A321', 'You have a terrible taste in libraries', 2], 'A321'),
  (['B321', 'You have a terrible taste in libraries', 7], 'B321'),
])
def test_code_return(check_plugin, code_test_input, code_test_expected):
  error = check_plugin.error(*code_test_input)
  assert error.code == code_test_expected, 'Unexpected code found'


def test_error_severity(check_plugin):
  """Test that we get Nit.Error when calling error"""
  error = check_plugin.error('A123', 'Uh-oh this is bad')
  assert error.severity == Nit.ERROR


def test_warn_severity(check_plugin):
  """Test that we get Nit.WARNING when calling warning"""
  error = check_plugin.warning('A123', 'No worries, its just a warning')
  assert error.severity == Nit.WARNING


def test_style_error(test_python_file):
  """Test error with actual AST node

  Verify that when we fetch a node form AST and create an error we get the
  same result as generating the error manually.
  """
  plugin = MinimalCheckstylePlugin(test_python_file)
  import_from = None
  for node in ast.walk(test_python_file.tree):
    if isinstance(node, ast.ImportFrom):
      import_from = node

  ast_error = plugin.error('B380', "I don't like your from import!", import_from)
  error = plugin.error('B380', "I don't like your from import!", 2)
  assert str(error) == str(ast_error)


def test_index_error_with_data():
  """Test index errors with data in list"""
  test_list = OffByOneList([])
  for k in (0, 4):
    with pytest.raises(IndexError):
      test_list[k]


@pytest.mark.parametrize("index",
  [-1, 0, 1, slice(-1,0), slice(0,1)]
)
def test_index_error_no_data(index):
  """Test that when start or end are -1,0, or 1 we get an index error"""
  test_list = OffByOneList([])
  with pytest.raises(IndexError):
    test_list[index]


def test_empty_slice():
  """Test that we get an empty list if no elements in slice"""
  test_list = OffByOneList([])
  for s in (slice(1, 1), slice(1, 2), slice(-2, -1)):
    assert test_list[s] == []


def test_off_by_one():
  """Test that you fetch the value you put in"""
  test_list = OffByOneList(['1', '2', '3'])
  for k in (1, 2, 3):
    assert test_list[k] == str(k)
    assert test_list[k:k + 1] == [str(k)]
    assert test_list.index(str(k)) == k
    assert test_list.count(str(k)) == 1
  assert list(reversed(test_list)) == ['3', '2', '1']


def test_index_type():
  test_list = OffByOneList([])
  # Test Index Type Sanity
  for value in (None, 2.0, type):
    with pytest.raises(TypeError):
      test_list[value]
