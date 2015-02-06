# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

import mock

from pants.backend.python.interpreter_cache import PythonInterpreter, PythonInterpreterCache
from pants.util.contextutil import temporary_dir


class TestInterpreterCache(unittest.TestCase):
  def _make_bad_requirement(self, requirement):
    """
    Turn a requirement that passes into one we know will fail. E.g. 'CPython==2.7.5' becomes
    'CPython==99.7.5'
    """
    return str(requirement).replace('==2.', '==99.')

  @mock.patch('pants.backend.python.interpreter_cache.PythonSetup', return_value=mock.MagicMock())
  def test_cache_setup_with_no_filters_uses_repo_default_excluded(self, MockSetup):
    # This is the interpreter we'll inject into the cache
    interpreter = PythonInterpreter.get()

    mock_setup = MockSetup.return_value
    # Explicitly set a repo-wide requirement that excludes our one interpreter
    type(mock_setup).interpreter_requirement = mock.PropertyMock(
        return_value=self._make_bad_requirement(interpreter.identity.requirement))

    with temporary_dir() as path:
      mock_setup.scratch_dir.return_value = path

      cache = PythonInterpreterCache(mock.MagicMock())

      def set_interpreters(_):
        cache._interpreters.add(interpreter)

      cache._setup_cached = mock.Mock(side_effect=set_interpreters)
      cache._setup_paths = mock.Mock()

      self.assertEqual(len(cache.setup()), 0)

  @mock.patch('pants.backend.python.interpreter_cache.PythonSetup', return_value=mock.MagicMock())
  def test_cache_setup_with_no_filters_uses_repo_default_excluded(self, MockSetup):
    interpreter = PythonInterpreter.get()

    mock_setup = MockSetup.return_value
    type(mock_setup).interpreter_requirement = mock.PropertyMock(return_value=None)

    with temporary_dir() as path:
      mock_setup.scratch_dir.return_value = path

      cache = PythonInterpreterCache(mock.MagicMock())

      def set_interpreters(_):
        cache._interpreters.add(interpreter)

      cache._setup_cached = mock.Mock(side_effect=set_interpreters)

      self.assertEqual(cache.setup(), [interpreter])

  @mock.patch('pants.backend.python.interpreter_cache.PythonSetup', return_value=mock.MagicMock())
  def test_cache_setup_with_filter_overrides_repo_default(self, MockSetup):
    interpreter = PythonInterpreter.get()

    mock_setup = MockSetup.return_value
    # Explicitly set a repo-wide requirement that excludes our one interpreter
    type(mock_setup).interpreter_requirement = mock.PropertyMock(
        return_value=self._make_bad_requirement(interpreter.identity.requirement))

    with temporary_dir() as path:
      mock_setup.scratch_dir.return_value = path

      cache = PythonInterpreterCache(mock.MagicMock())

      def set_interpreters(_):
        cache._interpreters.add(interpreter)

      cache._setup_cached = mock.Mock(side_effect=set_interpreters)

      self.assertEqual(cache.setup(filters=(str(interpreter.identity.requirement),)), [interpreter])
