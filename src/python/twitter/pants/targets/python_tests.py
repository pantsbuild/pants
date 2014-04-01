# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from twitter.common.collections import maybe_list
from twitter.common.quantity import Amount, Time

from pants.base.build_manual import manual
from pants.targets.python_target import PythonTarget


@manual.builddict(tags=["python"])
class PythonTests(PythonTarget):
  """Tests a Python library."""

  def __init__(self,
               name,
               sources,
               resources=None,
               dependencies=None,
               timeout=Amount(2, Time.MINUTES),
               coverage=None,
               soft_dependencies=False,
               entry_point='pytest',
               exclusives=None):
    """
    :param name: See PythonLibrary target
    :param sources: A list of filenames representing the source code
      this library is compiled from.
    :type sources: list of strings
    :param resources: See PythonLibrary target
    :param dependencies: List of :class:`pants.base.target.Target` instances
      this target depends on.
    :type dependencies: list of targets
    :param timeout: Amount of time before this test should be considered timed-out.
    :param coverage: the module(s) whose coverage should be generated, e.g.
      'twitter.common.log' or ['twitter.common.log', 'twitter.common.http']
    :param soft_dependencies: Whether or not we should ignore dependency resolution
      errors for this test.
    :param entry_point: The entry point to use to run the tests.
    :param dict exclusives: An optional dict of exclusives tags. See CheckExclusives for details.
    """
    self._timeout = timeout
    self._soft_dependencies = bool(soft_dependencies)
    self._coverage = maybe_list(coverage) if coverage is not None else []
    self._entry_point = entry_point
    super(PythonTests, self).__init__(name, sources, resources, dependencies, exclusives=exclusives)
    self.add_labels('python', 'tests')

  @property
  def timeout(self):
    return self._timeout

  @property
  def coverage(self):
    return self._coverage

  @property
  def entry_point(self):
    return self._entry_point


class PythonTestSuite(PythonTarget):
  """Tests one or more python test targets."""

  def __init__(self, name, dependencies=None):
    super(PythonTestSuite, self).__init__(name, (), (), dependencies)
