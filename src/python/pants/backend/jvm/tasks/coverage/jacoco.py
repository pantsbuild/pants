# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import functools
import os

from pants.backend.jvm.subsystems.jvm_tool_mixin import JvmToolMixin
from pants.backend.jvm.tasks.coverage.engine import CoverageEngine
from pants.base.exceptions import TaskError
from pants.java.jar.jar_dependency import JarDependency
from pants.subsystem.subsystem import Subsystem
from pants.util import desktop
from pants.util.dirutil import safe_delete, safe_mkdir


class Jacoco(CoverageEngine):
  """Class to run coverage tests with Jacoco."""

  class Factory(Subsystem, JvmToolMixin):
    options_scope = 'jacoco'

    @classmethod
    def register_options(cls, register):
      super(Jacoco.Factory, cls).register_options(register)

      # We need to inject the jacoco agent at test runtime
      cls.register_jvm_tool(register,
                        'jacoco-agent',
                        classpath=[
                          JarDependency(
                            org='org.jacoco',
                            name='org.jacoco.agent',
                            # TODO(jtrobec): get off of snapshat once jacoco release with cli is available
                            # see https://github.com/pantsbuild/pants/issues/5010
                            rev='0.7.10-SNAPSHOT',
                            classifier='runtime',
                            intransitive=True)
                        ])

      # We'll use the jacoco-cli to generate reports
      cls.register_jvm_tool(register,
                        'jacoco-cli',
                        classpath=[
                          JarDependency(
                            org='org.jacoco',
                            name='org.jacoco.cli',
                            # TODO(jtrobec): get off of snapshat once jacoco release with cli is available
                            # see https://github.com/pantsbuild/pants/issues/5010
                            rev='0.7.10-SNAPSHOT')
                        ])

    def create(self, settings, targets, execute_java_for_targets):
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

      agent_path = self.tool_jar_from_products(settings.context.products, 'jacoco-agent', scope='jacoco')
      cli_path = self.tool_classpath_from_products(settings.context.products, 'jacoco-cli', scope='jacoco')
      return Jacoco(settings, agent_path, cli_path, targets, execute_java_for_targets)

  def __init__(self, settings, agent_path, cli_path, targets, execute_java_for_targets):
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
    options = settings.options
    self._context = settings.context
    self._targets = targets
    self._coverage_targets = {t for t in targets if Jacoco.is_coverage_target(t)}
    self._agent_path = agent_path
    self._cli_path = cli_path
    self._execute_java = functools.partial(execute_java_for_targets, targets)
    self._coverage_force = options.coverage_force
    self._coverage_datafile = os.path.join(settings.coverage_dir, 'jacoco.exec')
    self._coverage_report_dir = os.path.join(settings.coverage_dir, 'reports')

  def instrument(self):
    # jacoco does runtime instrumentation, so this only does clean-up of existing run
    safe_delete(self._coverage_datafile)

  @property
  def classpath_append(self):
    return ()

  @property
  def classpath_prepend(self):
    return ()

  @property
  def extra_jvm_options(self):
    agent_option = '-javaagent:{agent}=destfile={destfile}'.format(agent=self._agent_path,
                                                                   destfile=self._coverage_datafile)
    return [agent_option]

  @staticmethod
  def is_coverage_target(tgt):
    return (tgt.is_java or tgt.is_scala) and not tgt.is_test and not tgt.is_synthetic

  def report(self, execution_failed_exception=None):
    if execution_failed_exception:
      self._settings.log.warn('Test failed: {0}'.format(execution_failed_exception))
      if self._coverage_force:
        self._settings.log.warn('Generating report even though tests failed, because the coverage-force flag is set.')
      else:
        return

    safe_mkdir(self._coverage_report_dir, clean=True)
    for report_format in ['xml', 'csv', 'html']:
      target_path = os.path.join(self._coverage_report_dir, report_format)
      args = ['report', self._coverage_datafile] + self._get_target_classpaths() + self._get_source_roots() + [
        '--{report_format}={target_path}'.format(report_format=report_format,
                                                 target_path=target_path)
      ]
      main = 'net.sourceforge.cobertura.reporting.ReportMain'
      result = self._execute_java(classpath=self._cli_path,
                                  main='org.jacoco.cli.internal.Main',
                                  jvm_options=self._settings.coverage_jvm_options,
                                  args=args,
                                  workunit_factory=self._context.new_workunit,
                                  workunit_name='jacoco-report-' + report_format)
      if result != 0:
        raise TaskError("java {0} ... exited non-zero ({1})"
                        " 'failed to report'".format(main, result))

  def _get_target_classpaths(self):
    runtime_classpath = self._context.products.get_data('runtime_classpath')

    target_paths = []
    for target in self._coverage_targets:
      paths = runtime_classpath.get_for_target(target)
      for (name, path) in paths:
        target_paths.append(path)

    return self._make_multiple_arg('--classfiles', target_paths)

  def _get_source_roots(self):
    source_roots = {t.target_base for t in self._coverage_targets}
    return self._make_multiple_arg('--sourcefiles', source_roots)

  def _make_multiple_arg(self, arg_name, arg_list):
    """Jacoco cli allows the specification of multiple values for certain args by repeating the argument
    with a new value. E.g. --classfiles a.class --classfiles b.class, etc. This method creates a list of
    strings interleaved with the arg name to satisfy that format.
    """
    unique_args = list(set(arg_list))

    args = [(arg_name, f) for f in unique_args]
    flattened = list(sum(args, ()))

    return flattened

  def maybe_open_report(self):
    if self._settings.coverage_open:
      report_file_path = os.path.join(self._settings.coverage_dir, 'reports/html', 'index.html')
      try:
        desktop.ui_open(report_file_path)
      except desktop.OpenError as e:
        raise TaskError(e)
