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
from pants.util.dirutil import safe_mkdir, safe_walk


class Jacoco(CoverageEngine):
  """Class to run coverage tests with Jacoco."""

  class Factory(Subsystem, JvmToolMixin):
    options_scope = 'jacoco'

    @classmethod
    def register_options(cls, register):
      super(Jacoco.Factory, cls).register_options(register)

      def jacoco_jar(name, **kwargs):
        return JarDependency(org='org.jacoco', name=name, rev='0.8.0', **kwargs)

      # We need to inject the jacoco agent at test runtime
      cls.register_jvm_tool(register,
                            'jacoco-agent',
                            classpath=[
                              jacoco_jar(name='org.jacoco.agent', classifier='runtime')
                            ])

      # We'll use the jacoco-cli to generate reports
      cls.register_jvm_tool(register,
                            'jacoco-cli',
                            classpath=[
                              jacoco_jar(name='org.jacoco.cli')
                            ])

    def create(self, settings, targets, execute_java_for_targets):
      """
      :param settings: Generic code coverage settings.
      :type settings: :class:`CodeCoverageSettings`
      :param list targets: A list of targets to instrument and record code coverage for.
      :param execute_java_for_targets: A function that accepts a list of targets whose JVM platform
                                       constraints are used to pick a JVM `Distribution`. The
                                       function should also accept `*args` and `**kwargs` compatible
                                       with the remaining parameters accepted by
                                       `pants.java.util.execute_java`.
      """

      agent_path = self.tool_jar_from_products(settings.context.products, 'jacoco-agent',
                                               scope='jacoco')
      cli_path = self.tool_classpath_from_products(settings.context.products, 'jacoco-cli',
                                                   scope='jacoco')
      return Jacoco(settings, agent_path, cli_path, targets, execute_java_for_targets)

  _DATAFILE_NAME = 'jacoco.exec'

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
    self._coverage_targets = {t for t in targets if self.is_coverage_target(t)}
    self._agent_path = agent_path
    self._cli_path = cli_path
    self._execute_java = functools.partial(execute_java_for_targets, targets)
    self._coverage_force = options.coverage_force

  def _iter_datafiles(self, output_dir):
    for root, _, files in safe_walk(output_dir):
      for f in files:
        if f == self._DATAFILE_NAME:
          yield os.path.join(root, f)
          break

  def instrument(self, output_dir):
    # Since jacoco does runtime instrumentation, we only need to clean-up existing runs.
    for datafile in self._iter_datafiles(output_dir):
      os.unlink(datafile)

  def run_modifications(self, output_dir):
    datafile = os.path.join(output_dir, self._DATAFILE_NAME)
    agent_option = '-javaagent:{agent}=destfile={destfile}'.format(agent=self._agent_path,
                                                                   destfile=datafile)
    return self.RunModifications.create(extra_jvm_options=[agent_option])

  def _execute_jacoco_cli(self, workunit_name, args):
    main = 'org.jacoco.cli.internal.Main'
    result = self._execute_java(classpath=self._cli_path,
                                main=main,
                                jvm_options=self._settings.coverage_jvm_options,
                                args=args,
                                workunit_factory=self._context.new_workunit,
                                workunit_name=workunit_name)
    if result != 0:
      raise TaskError('java {} ... exited non-zero ({}) - failed to {}'
                      .format(main, result, workunit_name))

  def report(self, output_dir, execution_failed_exception=None):
    if execution_failed_exception:
      self._settings.log.warn('Test failed: {}'.format(execution_failed_exception))
      if self._coverage_force:
        self._settings.log.warn('Generating report even though tests failed, because the'
                                'coverage-force flag is set.')
      else:
        return

    report_dir = os.path.join(output_dir, 'coverage', 'reports')
    safe_mkdir(report_dir, clean=True)

    datafiles = list(self._iter_datafiles(output_dir))
    if len(datafiles) == 1:
      datafile = datafiles[0]
    else:
      datafile = os.path.join(output_dir, '{}.merged'.format(self._DATAFILE_NAME))
      args = ['merge'] + datafiles + ['--destfile={}'.format(datafile)]
      self._execute_jacoco_cli(workunit_name='jacoco-merge', args=args)

    for report_format in ('xml', 'csv', 'html'):
      target_path = os.path.join(report_dir, report_format)
      args = (['report', datafile] +
              self._get_target_classpaths() +
              self._get_source_roots() +
              ['--{report_format}={target_path}'.format(report_format=report_format,
                                                        target_path=target_path)])
      self._execute_jacoco_cli(workunit_name='jacoco-report-' + report_format, args=args)

    if self._settings.coverage_open:
      return os.path.join(report_dir, 'html', 'index.html')

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
    """Jacoco cli allows the specification of multiple values for certain args by repeating the
    argument with a new value. E.g. --classfiles a.class --classfiles b.class, etc. This method
    creates a list of strings interleaved with the arg name to satisfy that format.
    """
    unique_args = list(set(arg_list))

    args = [(arg_name, f) for f in unique_args]
    flattened = list(sum(args, ()))

    return flattened
