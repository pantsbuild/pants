# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import functools
import os
import subprocess
import re
from pants.java.jar.jar_dependency import JarDependency
from pants.backend.jvm.tasks.coverage.engine import CoverageEngine
from pants.base.exceptions import TaskError
from pants.subsystem.subsystem import Subsystem
from pants.util.dirutil import relativize_paths, safe_mkdir, safe_mkdir_for, safe_walk, touch


report_generator = 'src/scala/org/pantsbuild/scoverage/report:gen2'


class Scoverage(CoverageEngine):
  """Class to run coverage tests with scoverage"""


  class Factory(Subsystem):
    options_scope = 'scoverage-runtime'

    @classmethod
    def create(cls, settings, targets, execute_java_for_targets):
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

      return Scoverage(settings, targets, execute_java_for_targets)


  @staticmethod
  def register_junit_options(register, register_jvm_tool):

    def scoverage_runtime_jar(**kwargs):
      return JarDependency(org='com.twitter.scoverage', name='scalac-scoverage-runtime_2.12',
        rev='1.0.1-twitter', **kwargs)

    register_jvm_tool(register,
      'scalac-scoverage-runtime',
      classpath=[
        scoverage_runtime_jar()
      ])

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
    self._context = settings.context
    self._targets = targets
    self._target_filters = []    # TODO(sameera): add target filtering for scoverage
    self._execute_java = functools.partial(execute_java_for_targets, targets)

  def _iter_datafiles(self, output_dir):
    for root, _, files in safe_walk(output_dir):
      for f in files:
        if f.startswith("scoverage"):
          yield os.path.join(root, f)

  def _iter_datadirs(self, output_dir):
    for root, dirs, _ in safe_walk(output_dir):
      for d in dirs:
        if d.startswith("measurements"):
          yield os.path.join(root, d)
          break


  def instrument(self, output_dir):
    # Since scoverage does compile time instrumentation, we only need to clean-up existing runs.
    for datafile in self._iter_datafiles(output_dir):
      os.unlink(datafile)


  def run_modifications(self, output_dir):
    measurement_dir = os.path.join(output_dir, "scoverage", "measurements")
    safe_mkdir(measurement_dir, clean=True)
    data_dir_option = f'-Dscoverage_measurement_path={measurement_dir}'

    return self.RunModifications.create(
      classpath_prepend=self._settings.tool_classpath('scalac-scoverage-runtime'),
      extra_jvm_options=[data_dir_option])


  def report(self, output_dir, execution_failed_exception=None):
    if execution_failed_exception:
      self._settings.log.warn('Test failed: {}'.format(execution_failed_exception))
      return

    for md in self._iter_datadirs(output_dir):
      parent_dir = os.path.dirname(md)
      base_report_dir = os.path.join(parent_dir, 'reports')
      safe_mkdir(base_report_dir, clean=True)

      # TODO(sameera): add target filtering for scoverage
      filtered_targets = self.filter_scoverage_targets(md)
      self._execute_scoverage_report_gen(measurements_dir=md, report_dir=base_report_dir,
        target_filter=filtered_targets)

    # Opening the last generated report in case `--no-test-junit-fast` is specified.
    if self._settings.coverage_open:
      return os.path.join(base_report_dir, 'html', 'index.html')

  def _execute_scoverage_report_gen(self, measurements_dir, report_dir, target_filter):
    cmd = [
      './pants',
      '--scoverage-enable-scoverage=True',
      'run',
      f'{report_generator}',
      f'--jvm-run-jvm-program-args=["-measurementsDirPath","{measurements_dir}","-reportDirPath",'
      f'"{report_dir}"]',
    ]

    # if target_filter:
    # cmd += ['--jvm-run-jvm-program-args="-neededTargets={}"'.format(','.join(target_filter))]

    with self._context.new_workunit(name='scoverage_report_generator') as workunit:
      result = subprocess.call(cmd)

      if result != 0:
        raise TaskError("scoverage ... exited non-zero ({0})"
                        " 'failed to generate report'".format(result))

  def filter_scoverage_targets(self, measurements_dir):
    return [d for d in os.listdir(measurements_dir) if self._include_dir(d)]

  def _include_dir(self, dir):
    if len(self._target_filters) == 0:
      return True
    else:
      for filter in self._target_filters:
        filter = filter.replace("/", ".")
        if re.search(filter, dir) is not None:
          return True
    return False
