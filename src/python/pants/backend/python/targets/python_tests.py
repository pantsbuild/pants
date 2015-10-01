# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from twitter.common.collections import maybe_list

from pants.backend.python.targets.python_target import PythonTarget


class PythonTests(PythonTarget):
  """Tests a Python library."""

  def __init__(self, coverage=None, **kwargs):
    """
    :param coverage: the module(s) whose coverage should be generated, e.g.
      'twitter.common.log' or ['twitter.common.log', 'twitter.common.http']
    """
    self._coverage = maybe_list(coverage) if coverage is not None else []
    super(PythonTests, self).__init__(**kwargs)
    self.add_labels('python', 'tests')

  @property
  def coverage(self):
    return self._coverage
