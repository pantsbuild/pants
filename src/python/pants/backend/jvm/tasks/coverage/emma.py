# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import sys

from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.tasks.coverage.base import Coverage
from pants.base.exceptions import TaskError
from pants.binaries import binary_util
from pants.util.dirutil import safe_mkdir, safe_open


class Emma(Coverage):
  """Class to run coverage tests with Emma."""

  @classmethod
  def register_options(cls, register, register_jvm_tool):
    register_jvm_tool(register,
                      'emma',
                      classpath=[
                        JarDependency(org='emma', name='emma', rev='2.1.5320')
                      ])

  def instrument(self, targets, tests, compute_junit_classpath, execute_java_for_targets):
    junit_classpath = compute_junit_classpath()
    safe_mkdir(self._coverage_instrument_dir, clean=True)
    self._emma_classpath = self._task_exports.tool_classpath('emma')
    with binary_util.safe_args(self.get_coverage_patterns(targets),
                               self._task_exports.task_options) as patterns:
      args = [
        'instr',
        '-out', self._coverage_metadata_file,
        '-d', self._coverage_instrument_dir,
        '-cp', os.pathsep.join(junit_classpath),
        '-exit'
      ]
      for pattern in patterns:
        args.extend(['-filter', pattern])
      main = 'emma'
      result = execute_java_for_targets(targets,
                                        classpath=self._emma_classpath,
                                        main=main,
                                        jvm_options=self._coverage_jvm_options,
                                        args=args,
                                        workunit_factory=self._context.new_workunit,
                                        workunit_name='emma-instrument')
      if result != 0:
        raise TaskError("java {0} ... exited non-zero ({1})"
                        " 'failed to instrument'".format(main, result))

  @property
  def classpath_prepend(self):
    return [self._coverage_instrument_dir]

  @property
  def classpath_append(self):
    return self._emma_classpath

  @property
  def extra_jvm_options(self):
    return ['-Demma.coverage.out.file={0}'.format(self._coverage_file)]

  def report(self, targets, tests, execute_java_for_targets, tests_failed_exception=None):
    if tests_failed_exception:
      self._context.log.warn('Test failed: {0}'.format(str(tests_failed_exception)))
      if self._coverage_force:
        self._context.log.warn('Generating report even though tests failed')
      else:
        return
    args = [
      'report',
      '-in', self._coverage_metadata_file,
      '-in', self._coverage_file,
      '-exit'
    ]
    source_bases = set()

    def collect_source_base(target):
      if self.is_coverage_target(target):
        source_bases.add(target.target_base)

    for target in targets:
      target.walk(collect_source_base)
    for source_base in source_bases:
      args.extend(['-sp', source_base])

    sorting = ['-Dreport.sort', '+name,+class,+method,+block']
    args.extend(['-r', 'txt',
                 '-Dreport.txt.out.file={0}'.format(self._coverage_console_file)] + sorting)
    args.extend(['-r', 'xml', '-Dreport.xml.out.file={0}'.format(self._coverage_xml_file)])
    args.extend(['-r', 'html',
                 '-Dreport.html.out.file={0}'.format(self._coverage_html_file),
                 '-Dreport.out.encoding=UTF-8'] + sorting)

    main = 'emma'
    result = execute_java_for_targets(targets,
                                      classpath=self._emma_classpath,
                                      main=main,
                                      jvm_options=self._coverage_jvm_options,
                                      args=args,
                                      workunit_factory=self._context.new_workunit,
                                      workunit_name='emma-report')
    if result != 0:
      raise TaskError("java {0} ... exited non-zero ({1})"
                      " 'failed to generate code coverage reports'".format(main, result))

    with safe_open(self._coverage_console_file) as console_report:
      sys.stdout.write(console_report.read())
    if self._coverage_open:
      binary_util.ui_open(self._coverage_html_file)
