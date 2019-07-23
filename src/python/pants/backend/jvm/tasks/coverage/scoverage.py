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

    def scoverage_report_jar(**kwargs):
      return [JarDependency(org='org.pantsbuild', name='scoverageReport_2.12',
        rev='0.0.1-SNAPSHOT', url='file:/Users/sameera/.m2/repository/org/pantsbuild/scoverageReport_2.12/0.0.1-SNAPSHOT/scoverageReport_2.12-0.0.1-SNAPSHOT.jar', **kwargs),
              JarDependency(org='org.apache.directory.studio', name='org.apache.commons.io', rev='2.4'),
              JarDependency(org='com.github.scopt', name='scopt_2.12', rev='3.7.0'),
              JarDependency(org='org.scala-sbt', name='util-logging_2.12', rev='1.3.0-M8'),
              JarDependency(org='com.twitter.scoverage', name='scalac-scoverage-plugin_2.12', rev='1.0.1-twitter')]

    register_jvm_tool(register,
      'scalac-scoverage-runtime',
      classpath=[
        scoverage_runtime_jar()
      ])

    register_jvm_tool(register,
      'scoverage-report',
      classpath=
        scoverage_report_jar()
      )

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
    cobertura_cp = self._settings.tool_classpath('scoverage-report')
    result = self._execute_java(classpath=cobertura_cp,
                                main='org.pantsbuild.scoverage.report.ScoverageReport',
                                jvm_options=self._settings.coverage_jvm_options,
                                args=["--measurementsDirPath",f"{output_dir}/scoverage/measurements", "--reportDirPath",f"{output_dir}/ScoverageReports"],
                               )


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
