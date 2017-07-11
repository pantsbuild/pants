# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from twitter.common.collections import maybe_list

from pants.backend.python.targets.python_target import PythonTarget


class PythonTests(PythonTarget):
  """Python tests.

  :API: public
  """

  # These are the patterns matched by pytest's test discovery.
  default_sources_globs = ('test_*.py', '*_test.py')

  @classmethod
  def alias(cls):
    return 'python_tests'

  def __init__(self, coverage=None, timeout=None, **kwargs):
    """
    :param coverage: the module(s) whose coverage should be generated, e.g.
      'twitter.common.log' or ['twitter.common.log', 'twitter.common.http']
    :param int timeout: A timeout (in seconds) which covers the total runtime of all tests in this
      target. Only applied if `--test-pytest-timeouts` is set to True.
    """
    self._coverage = maybe_list(coverage) if coverage is not None else []
    self._timeout = timeout
    super(PythonTests, self).__init__(**kwargs)
    self.add_labels('python', 'tests')

  @property
  def coverage(self):
    """
    :API: public
    """
    return self._coverage

  @property
  def timeout(self):
    """
    :API: public
    """
    return self._timeout
