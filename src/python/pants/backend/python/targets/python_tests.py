# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from twitter.common.collections import maybe_list
from twitter.common.quantity import Amount, Time

from pants.base.build_manual import manual
from pants.backend.python.targets.python_target import PythonTarget


@manual.builddict(tags=["python"])
class PythonTests(PythonTarget):
  """Tests a Python library."""

  def __init__(self, coverage=None, **kwargs):
    """
    :param name: See PythonLibrary target
    :param sources: A list of filenames representing the source code
      this library is compiled from.
    :type sources: list of strings
    :param resources: See PythonLibrary target
    :param dependencies: List of :class:`pants.base.target.Target` instances
      this target depends on.
    :type dependencies: list of targets
    :param coverage: the module(s) whose coverage should be generated, e.g.
      'twitter.common.log' or ['twitter.common.log', 'twitter.common.http']
    :param dict exclusives: An optional dict of exclusives tags. See CheckExclusives for details.
    """
    self._coverage = maybe_list(coverage) if coverage is not None else []
    self._timeout = kwargs.pop('timeout', Amount(2, Time.MINUTES))
    super(PythonTests, self).__init__(**kwargs)
    self.add_labels('python', 'tests')

  @property
  def timeout(self):
    return self._timeout

  @property
  def coverage(self):
    return self._coverage
