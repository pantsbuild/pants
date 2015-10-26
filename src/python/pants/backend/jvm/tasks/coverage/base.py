# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shutil
from abc import ABCMeta, abstractmethod, abstractproperty

from pants.util.dirutil import safe_mkdir
from pants.util.strutil import safe_shlex_split


class CoverageTaskSettings(object):
  """A class containing settings for code coverage tasks."""

  def __init__(self, task):
    self.options = task.get_options()
    self.context = task.context
    self.workdir = task.workdir
    self.tool_classpath = task.tool_classpath
    self.confs = task.confs
    self.coverage_dir = os.path.join(self.workdir, 'coverage')
    self.coverage_instrument_dir = os.path.join(self.coverage_dir, 'classes')
    self.coverage_console_file = os.path.join(self.coverage_dir, 'coverage.txt')
    self.coverage_xml_file = os.path.join(self.coverage_dir, 'coverage.xml')
    self.coverage_html_file = os.path.join(self.coverage_dir, 'html', 'index.html')


class Coverage(object):
  """Base class for coverage processors. Do not instantiate."""
  __metaclass__ = ABCMeta

  @classmethod
  def register_options(cls, register, register_jvm_tool):
    register('--coverage', action='store_true', help='Collect code coverage data.')
    register('--coverage-processor', advanced=True, default='cobertura',
             help='Which coverage subsystem to use.')
    register('--coverage-jvm-options', advanced=True, action='append',
             help='JVM flags to be added when running the coverage processor. For example: '
                  '{flag}=-Xmx4g {flag}=-XX:MaxPermSize=1g'.format(flag='--coverage-jvm-options'))
    register('--coverage-open', action='store_true',
             help='Open the generated HTML coverage report in a browser. Implies --coverage.')
    register('--coverage-force', advanced=True, action='store_true',
             help='Attempt to run the reporting phase of coverage even if tests failed '
                  '(defaults to False, as otherwise the coverage results would be unreliable).')

  def __init__(self, settings):
    self._settings = settings
    options = settings.options
    self._context = settings.context
    self._coverage = options.coverage

    self._coverage_jvm_options = []
    for jvm_option in options.coverage_jvm_options:
      self._coverage_jvm_options.extend(safe_shlex_split(jvm_option))

    self._coverage_open = options.coverage_open
    self._coverage_force = options.coverage_force

  @abstractmethod
  def instrument(self, targets, tests, compute_junit_classpath, execute_java_for_targets):
    pass

  @abstractmethod
  def report(self, targets, tests, execute_java_for_targets, tests_failed_exception):
    pass

  @abstractproperty
  def classpath_prepend(self):
    pass

  @abstractproperty
  def classpath_append(self):
    pass

  @abstractproperty
  def extra_jvm_options(self):
    pass

  # Utility methods, called from subclasses
  def is_coverage_target(self, tgt):
    return (tgt.is_java or tgt.is_scala) and not tgt.is_test and not tgt.is_codegen

  def initialize_instrument_classpath(self, targets):
    """Clones the existing runtime_classpath and corresponding binaries to instrumentation specific
    paths.

    :param targets: the targets which should be mutated.
    :returns the instrument_classpath ClasspathProducts containing the mutated paths.
    """
    safe_mkdir(self._settings.coverage_instrument_dir, clean=True)

    runtime_classpath = self._context.products.get_data('runtime_classpath')
    self._context.products.safe_create_data('instrument_classpath', runtime_classpath.copy)
    instrumentation_classpath = self._context.products.get_data('instrument_classpath')

    for target in targets:
      if not self.is_coverage_target(target):
        continue
      paths = instrumentation_classpath.get_for_target(target, False)
      for (config, path) in paths:
        # there are two sorts of classpath entries we see in the compile classpath: jars and dirs
        # the branches below handle the cloning of those respectively.
        if os.path.isfile(path):
          shutil.copy2(path, self._settings.coverage_instrument_dir)
          new_path = os.path.join(self._settings.coverage_instrument_dir, os.path.basename(path))
        else:
          files = os.listdir(path)
          for file in files:
            shutil.copy2(file, self._settings.coverage_instrument_dir)
          new_path = self._settings.coverage_instrument_dir

        instrumentation_classpath.remove_for_target(target, [(config, path)])
        instrumentation_classpath.add_for_target(target, [(config, new_path)])
        self._context.log.debug(
          "runtime_classpath ({}) mutated to instrument_classpath ({})".format(path, new_path))
    return instrumentation_classpath
