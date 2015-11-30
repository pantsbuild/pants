# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import ast
import textwrap
import unittest

from pants_test.option.util.fakes import create_options

from pants.contrib.python.checks.tasks.checkstyle.common import (CheckstylePlugin, Nit,
                                                                 OffByOneList, PythonFile)


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
  """Minimal Checkstyle plugin used to test PythonFile interactions in Plugin."""

  def nits(self):
    return []


class CommonTest(unittest.TestCase):

  def _statement_for_testing(self):
    """Pytest Fixture to create a test python file from statement."""
    return '\n'.join(textwrap.dedent(FILE_TEXT).split('\n')[1:])

  def _python_file_for_testing(self):
    """Pytest Fixture to create a test python file from statement."""
    return PythonFile(self._statement_for_testing(), 'keeper.py')

  def _plugin_for_testing(self):
    options_object = create_options({'foo': {'skip': False}}).for_scope('foo')
    return MinimalCheckstylePlugin(options_object, self._python_file_for_testing())

  def test_python_file_name(self):
    """Test that filename attrib is getting set properly."""
    self.assertEqual('keeper.py', self._python_file_for_testing().filename)

  def test_python_file_logical_lines(self):
    """Test that we get back logical lines we expect."""
    self.assertEqual({
      1: (1, 2, 0),  # import ast
      2: (2, 6, 0),  # from os.path import (", "    join,", "    split,", ")
      7: (7, 8, 0),  # import zookeeper
      10: (10, 11, 0),  # class Keeper(object):
      11: (11, 12, 2),  # def __init__(self):
      12: (12, 13, 4),  # self._session = None
      14: (14, 15, 2),  # def session(self):
      15: (15, 16, 4),  # return self._session
    }, self._python_file_for_testing().logical_lines)

  def test_python_file_index_offset(self):
    """Test that we can not index into a python file with 0.

    PythonFile is offset by one to match users expectations with file line numbering.
    """
    with self.assertRaises(IndexError):
      self._python_file_for_testing()[0]

  def test_python_file_exceeds_index(self):
    """Test that we get an Index error when we exceed the line number."""
    with self.assertRaises(IndexError):
      self._python_file_for_testing()[len(self._statement_for_testing().split('\n')) + 1]

  def test_line_retrieval(self):
    """Test that we get lines correctly when accessed by index."""
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
      [""]
    ]
    self.assertEqual(expected, [self._python_file_for_testing()[x] for x in range(1,17)])

  def test_rejoin(self):
    """Test that when we stitch the PythonFile back up we get back our input."""
    self.assertEqual(self._statement_for_testing(), '\n'.join(self._python_file_for_testing()))

  def test_off_by_one_enumeration(self):
    """Test that enumerate is offset by one."""
    self.assertEqual(list(enumerate(self._statement_for_testing().split('\n'), 1)),
                     list(self._python_file_for_testing().enumerate()))

  def test_line_number_return(self):
    for ln_test_input, ln_test_expected in [
      (['A123', 'You have a terrible taste in libraries'], None),
      (['A123', 'You have a terrible taste in libraries', 7], '007'),
      (['A123', 'You have a terrible taste in libraries', 2], '002-005'),
    ]:
      error = self._plugin_for_testing().error(*ln_test_input)
      self.assertEqual(ln_test_expected, error.line_number)

  def test_code_return(self):
    for code_test_input, code_test_expected in [
      (['A123', 'You have a terrible taste in libraries'], 'A123'),
      (['A321', 'You have a terrible taste in libraries', 2], 'A321'),
      (['B321', 'You have a terrible taste in libraries', 7], 'B321'),
    ]:
      error = self._plugin_for_testing().error(*code_test_input)
      self.assertEqual(code_test_expected, error.code)

  def test_error_severity(self):
    """Test that we get Nit.Error when calling error."""
    error = self._plugin_for_testing().error('A123', 'Uh-oh this is bad')
    self.assertEqual(Nit.ERROR, error.severity)

  def test_warn_severity(self):
    """Test that we get Nit.WARNING when calling warning."""
    error = self._plugin_for_testing().warning('A123', 'No worries, its just a warning')
    self.assertEqual(Nit.WARNING, error.severity)

  def test_style_error(self):
    """Test error with actual AST node.

    Verify that when we fetch a node form AST and create an error we get the
    same result as generating the error manually.
    """
    plugin = MinimalCheckstylePlugin({}, PythonFile.from_statement(FILE_TEXT))
    import_from = None
    for node in ast.walk(self._python_file_for_testing().tree):
      if isinstance(node, ast.ImportFrom):
        import_from = node

    ast_error = plugin.error('B380', "I don't like your from import!", import_from)
    error = plugin.error('B380', "I don't like your from import!", 2)
    self.assertEqual(str(ast_error), str(error))

  def test_index_error_with_data(self):
    """Test index errors with data in list."""
    test_list = OffByOneList([])
    for k in (0, 4):
      with self.assertRaises(IndexError):
        test_list[k]

  def test_index_error_no_data(self):
    """Test that when start or end are -1,0, or 1 we get an index error."""
    for index in [-1, 0, 1, slice(-1,0), slice(0,1)]:
      test_list = OffByOneList([])
      with self.assertRaises(IndexError):
        test_list[index]

  def test_empty_slice(self):
    """Test that we get an empty list if no elements in slice."""
    test_list = OffByOneList([])
    for s in (slice(1, 1), slice(1, 2), slice(-2, -1)):
      self.assertEqual([], test_list[s])

  def test_off_by_one(self):
    """Test that you fetch the value you put in."""
    test_list = OffByOneList(['1', '2', '3'])
    for k in (1, 2, 3):
      self.assertEqual(str(k), test_list[k])
      self.assertEqual([str(k)], test_list[k:k + 1])
      self.assertEqual(k, test_list.index(str(k)))
      self.assertEqual(1, test_list.count(str(k)))
    self.assertEqual(['3', '2', '1'], list(reversed(test_list)))

  def test_index_type(self):
    test_list = OffByOneList([])
    # Test index type sanity.
    for value in (None, 2.0, type):
      with self.assertRaises(TypeError):
        test_list[value]
