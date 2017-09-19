# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import functools
import os
from collections import defaultdict

from twitter.common.collections import OrderedSet

from pants.backend.jvm.tasks.coverage.base import BaseCoverage, CoverageTaskSettings
from pants.base.exceptions import TaskError
from pants.java.jar.jar_dependency import JarDependency
from pants.util import desktop
from pants.util.contextutil import temporary_file
from pants.util.dirutil import relativize_paths, safe_delete, safe_mkdir, touch


class JacocoTaskSettings(CoverageTaskSettings):
  """A class that holds task settings for jacoco coverage."""


class Jacoco(BaseCoverage):
  """Class to run coverage tests with Jacoco."""

  @classmethod
  def register_options(cls, register, register_jvm_tool):
    super(Jacoco, cls).register_options(register, register_jvm_tool)

  def __init__(self, settings, targets, execute_java_for_targets):
    """
    :param settings: The options for a `Jacoco` coverage run.
    :type settings: :class:`JacocoTaskSettings`
    :param list targets: A list of targets to instrument and record code coverage for.
    :param execute_java_for_targets: A function that accepts a list of targets whose JVM platform
                                     constraints are used to pick a JVM `Distribution`. The function
                                     should also accept `*args` and `**kwargs` compatible with the
                                     remaining parameters accepted by
                                     `pants.java.util.execute_java`.
    """
    super(Jacoco, self).__init__(settings)

  def instrument(self):
    # jacoco does runtime instrumentation, so this is a noop
    return

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
    return

  def maybe_open_report(self):
    # TODO(jtrobec): implement code coverage using jacoco
    return
