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
    """Turns a requirement that passes into one we know will fail.

    E.g. 'CPython==2.7.5' becomes 'CPython==99.7.5'
    """
    return str(requirement).replace('==2.', '==99.')

  def setUp(self):
    self._interpreter = PythonInterpreter.get()

  def _do_test(self, interpreter_requirement, filters, expected):
    mock_setup = mock.MagicMock().return_value

    # Explicitly set a repo-wide requirement that excludes our one interpreter.
    type(mock_setup).interpreter_requirement = mock.PropertyMock(
      return_value=interpreter_requirement)

    with temporary_dir() as path:
      mock_setup.scratch_dir = path
      cache = PythonInterpreterCache(mock_setup, mock.MagicMock())

      def set_interpreters(_):
        cache._interpreters.add(self._interpreter)

      cache._setup_cached = mock.Mock(side_effect=set_interpreters)
      cache._setup_paths = mock.Mock()

      self.assertEqual(cache.setup(filters=filters), expected)

  def test_cache_setup_with_no_filters_uses_repo_default_excluded(self):
    self._do_test(self._make_bad_requirement(self._interpreter.identity.requirement), [], [])

  def test_cache_setup_with_no_filters_uses_repo_default(self):
    self._do_test(None, [], [self._interpreter])

  def test_cache_setup_with_filter_overrides_repo_default(self):
    self._do_test(self._make_bad_requirement(self._interpreter.identity.requirement),
                  (str(self._interpreter.identity.requirement), ), [
                  self._interpreter])
