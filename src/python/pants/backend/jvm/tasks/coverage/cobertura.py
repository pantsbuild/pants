# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import functools
import os
import shutil
from collections import defaultdict

from twitter.common.collections import OrderedSet

from pants.backend.jvm.tasks.coverage.engine import CoverageEngine
from pants.base.exceptions import TaskError
from pants.java.jar.jar_dependency import JarDependency
from pants.subsystem.subsystem import Subsystem
from pants.util.contextutil import temporary_file
from pants.util.dirutil import relativize_paths, safe_mkdir, safe_mkdir_for, safe_walk, touch


class Cobertura(CoverageEngine):
  """Subsystem for getting code coverage with cobertura."""

  class Factory(Subsystem):
    options_scope = 'cobertura'

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

      return Cobertura(settings, targets, execute_java_for_targets)

  # TODO(jtrobec): deprecate these options and move them to subsystem scope
  @staticmethod
  def register_junit_options(register, register_jvm_tool):
    register('--coverage-cobertura-include-classes', advanced=True, type=list, fingerprint=True,
             help='Regex patterns passed to cobertura specifying which classes should be '
                  'instrumented. (see the "includeclasses" element description here: '
                  'https://github.com/cobertura/cobertura/wiki/Ant-Task-Reference)')

    register('--coverage-cobertura-exclude-classes', advanced=True, type=list, fingerprint=True,
             help='Regex patterns passed to cobertura specifying which classes should NOT be '
                  'instrumented. (see the "excludeclasses" element description here: '
                  'https://github.com/cobertura/cobertura/wiki/Ant-Task-Reference')

    def slf4j_jar(name):
      return JarDependency(org='org.slf4j', name=name, rev='1.7.5')

    def cobertura_jar(**kwargs):
      return JarDependency(org='net.sourceforge.cobertura', name='cobertura', rev='2.1.1', **kwargs)

    # The Cobertura jar needs all its dependencies when instrumenting code.
    register_jvm_tool(register,
                      'cobertura-instrument',
                      classpath=[
                        cobertura_jar(),
                        slf4j_jar('slf4j-simple')
                      ])

    # Instrumented code needs cobertura.jar in the classpath to run, but not most of the
    # dependencies; inject the SLF4J API so that Cobertura doesn't crash when it attempts to log
    register_jvm_tool(register,
                      'cobertura-run',
                      classpath=[
                        cobertura_jar(intransitive=True),
                        slf4j_jar('slf4j-api')
                      ])

    register_jvm_tool(register, 'cobertura-merge', classpath=[cobertura_jar()])
    register_jvm_tool(register, 'cobertura-report', classpath=[cobertura_jar()])

  _DATAFILE_NAME = 'cobertura.ser'

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
    options = settings.options
    self._context = settings.context
    self._coverage_force = options.coverage_force
    self._canonical_datafile = None
    self._rootdirs = defaultdict(OrderedSet)
    self._include_classes = options.coverage_cobertura_include_classes
    self._exclude_classes = options.coverage_cobertura_exclude_classes
    self._targets = targets
    self._execute_java = functools.partial(execute_java_for_targets, targets)

  @staticmethod
  def initialize_instrument_classpath(output_dir, settings, targets, instrumentation_classpath):
    """Clones the existing runtime_classpath and corresponding binaries to instrumentation specific
    paths.

    :param targets: the targets for which we should create an instrumentation_classpath entry based
    on their runtime_classpath entry.
    """
    instrument_dir = os.path.join(output_dir, 'coverage', 'classes')
    settings.safe_makedir(instrument_dir, clean=True)

    for target in targets:
      if not Cobertura.is_coverage_target(target):
        continue
      # Do not instrument transitive dependencies.
      paths = instrumentation_classpath.get_for_target(target)
      target_instrumentation_path = os.path.join(instrument_dir, target.id)
      for (index, (config, path)) in enumerate(paths):
        # There are two sorts of classpath entries we see in the compile classpath: jars and dirs.
        # The branches below handle the cloning of those respectively.
        entry_instrumentation_path = os.path.join(target_instrumentation_path, str(index))
        if settings.is_file(path):
          settings.safe_makedir(entry_instrumentation_path, clean=True)
          settings.copy2(path, entry_instrumentation_path)
          new_path = os.path.join(entry_instrumentation_path, os.path.basename(path))
        else:
          settings.copytree(path, entry_instrumentation_path)
          new_path = entry_instrumentation_path

        instrumentation_classpath.remove_for_target(target, [(config, path)])
        instrumentation_classpath.add_for_target(target, [(config, new_path)])
        settings.log.debug(
          "runtime_classpath ({}) cloned to instrument_classpath ({})".format(path, new_path))

  def _iter_datafiles(self, output_dir):
    for root, _, files in safe_walk(output_dir):
      for f in files:
        if f == self._DATAFILE_NAME:
          yield os.path.join(root, f)
          break

  @property
  def canonical_datafile(self):
    if self._canonical_datafile is None:
      raise AssertionError('Expected a canonical datafile to have been created via a call to'
                           '`instrument`.')
    elif not os.path.exists(self._canonical_datafile):
      raise AssertionError('The canonical datafile at {} has unexpectedly been deleted.'
                           .format(self._canonical_datafile))
    return self._canonical_datafile

  def instrument(self, output_dir):
    for datafile in self._iter_datafiles(output_dir):
      os.unlink(datafile)

    self._canonical_datafile = os.path.join(output_dir, '{}.canonical'.format(self._DATAFILE_NAME))
    # It's conceivable we'll be executing a test that has no source file dependencies; ie: we'll
    # never generate a canonical coverage datafile below. Create an empty one here to allow the
    # test run to proceeed normally.
    touch(self._canonical_datafile)

    # Setup an instrumentation classpath based on the existing runtime classpath.
    runtime_classpath = self._context.products.get_data('runtime_classpath')
    instrumentation_classpath = self._context.products.safe_create_data('instrument_classpath',
                                                                        runtime_classpath.copy)
    self.initialize_instrument_classpath(output_dir,
                                         self._settings,
                                         self._targets,
                                         instrumentation_classpath)

    cobertura_cp = self._settings.tool_classpath('cobertura-instrument')
    files_to_instrument = []
    for target in self._targets:
      if Cobertura.is_coverage_target(target):
        paths = instrumentation_classpath.get_for_target(target)
        for (name, path) in paths:
          files_to_instrument.append(path)

    if len(files_to_instrument) > 0:
      unique_files = list(set(files_to_instrument))
      relativize_paths(unique_files, self._settings.workdir)

      args = [
        '--basedir',
        self._settings.workdir,
        '--datafile',
        self._canonical_datafile,
      ]
      # apply class incl/excl filters
      if len(self._include_classes) > 0:
        for pattern in self._include_classes:
          args += ["--includeClasses", pattern]
      else:
        args += ["--includeClasses", '.*']  # default to instrumenting all classes
      for pattern in self._exclude_classes:
        args += ["--excludeClasses", pattern]

      with temporary_file() as tmp_file:
        tmp_file.write("\n".join(unique_files))
        tmp_file.flush()

        args += ["--listOfFilesToInstrument", tmp_file.name]

        main = 'net.sourceforge.cobertura.instrument.InstrumentMain'
        self._settings.log.debug(
          "executing cobertura instrumentation with the following args: {}".format(args))
        result = self._execute_java(classpath=cobertura_cp,
                                    main=main,
                                    jvm_options=self._settings.coverage_jvm_options,
                                    args=args,
                                    workunit_factory=self._context.new_workunit,
                                    workunit_name='cobertura-instrument')
        if result != 0:
          raise TaskError("java {0} ... exited non-zero ({1})"
                          " 'failed to instrument'".format(main, result))

  def run_modifications(self, output_dir):
    datafile = os.path.join(output_dir, self._DATAFILE_NAME)
    safe_mkdir_for(datafile)
    shutil.copy(self.canonical_datafile, datafile)
    datafile_option = '-Dnet.sourceforge.cobertura.datafile={datafile}'.format(datafile=datafile)
    return self.RunModifications(classpath_prepend=self._settings.tool_classpath('cobertura-run'),
                                 extra_jvm_options=[datafile_option])

  def should_report(self, execution_failed_exception=None):
    if execution_failed_exception:
      self._settings.log.warn('Test failed: {0}'.format(execution_failed_exception))
      if self._settings.coverage_force:
        self._settings.log.warn('Generating report even though tests failed.')
        return True
      else:
        return False
    return True

  def _execute_cobertura(self, workunit_name, tool_classpath, main, args):
    cobertura_cp = self._settings.tool_classpath(tool_classpath)
    result = self._execute_java(classpath=cobertura_cp,
                                main=main,
                                jvm_options=self._settings.coverage_jvm_options,
                                args=args,
                                workunit_factory=self._context.new_workunit,
                                workunit_name=workunit_name)
    if result != 0:
      raise TaskError('java {} ... exited non-zero ({}) - failed to {}'
                      .format(main, result, workunit_name))

  def report(self, output_dir, execution_failed_exception=None):
    if self.should_report(execution_failed_exception):
      datafiles = list(self._iter_datafiles(output_dir))
      if len(datafiles) == 1:
        datafile = datafiles[0]
      else:
        datafile = os.path.join(output_dir, '{}.merged'.format(self._DATAFILE_NAME))
        self._execute_cobertura(workunit_name='cobertura-merge',
                                tool_classpath='cobertura-merge',
                                main='net.sourceforge.cobertura.merge.MergeMain',
                                args=['--datafile', datafile] + datafiles)

      base_report_dir = os.path.join(output_dir, 'coverage', 'reports')
      safe_mkdir(base_report_dir, clean=True)

      source_roots = {t.target_base for t in self._targets if Cobertura.is_coverage_target(t)}
      base_args = list(source_roots) + ['--datafile', datafile]
      for report_format in ('xml', 'html'):
        report_dir = os.path.join(base_report_dir, report_format)
        safe_mkdir(report_dir, clean=True)
        self._execute_cobertura(workunit_name='cobertura-report-{}'.format(report_format),
                                tool_classpath='cobertura-report',
                                main='net.sourceforge.cobertura.reporting.ReportMain',
                                args=base_args + ['--destination', report_dir,
                                                  '--format', report_format])
      if self._settings.coverage_open:
        return os.path.join(base_report_dir, 'html', 'index.html')
