# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import functools

from pants.backend.jvm.tasks.coverage.engine import CoverageEngine
from pants.subsystem.subsystem import Subsystem


class Jacoco(CoverageEngine):
  """Class to run coverage tests with Jacoco."""

  class Factory(Subsystem):
    options_scope = 'jacoco'

    @classmethod
    def create(cls, settings, targets, execute_java_for_targets):
      """
      :param settings: Generic code coverage settings.
      :type settings: :class:`CodeCoverageSettings`
      :param list targets: A list of targets to instrument and record code coverage for.
      :param execute_java_for_targets: A function that accepts a list of targets whose JVM platform
                                       constraints are used to pick a JVM `Distribution`. The function
                                       should also accept `*args` and `**kwargs` compatible with the
                                       remaining parameters accepted by
                                       `pants.java.util.execute_java`.
      """

      return Jacoco(settings, targets, execute_java_for_targets)

  def __init__(self, settings, targets, execute_java_for_targets):
    """
    :param settings: Generic code coverage settings.
    :type settings: :class:`CodeCoverageSettings`
    :param list targets: A list of targets to instrument and record code coverage for.
    :param execute_java_for_targets: A function that accepts a list of targets whose JVM platform
                                     constraints are used to pick a JVM `Distribution`. The function
                                     should also accept `*args` and `**kwargs` compatible with the
                                     remaining parameters accepted by
                                     `pants.java.util.execute_java`.
    """
    self._settings = settings
    self._targets = targets
    self._execute_java = functools.partial(execute_java_for_targets, targets)

  def instrument(self):
    # jacoco does runtime instrumentation, so this is a noop
    pass

  @property
  def classpath_append(self):
    return ()

  @property
  def classpath_prepend(self):
    return ()

  @property
  def extra_jvm_options(self):
    # TODO(jtrobec): implement code coverage using jacoco
    return []

  def report(self, execution_failed_exception=None):
    # TODO(jtrobec): implement code coverage using jacoco
    pass

  def maybe_open_report(self):
    # TODO(jtrobec): implement code coverage using jacoco
    pass
