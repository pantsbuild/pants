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

  def __init__(self, options, context, workdir, tool_classpath, confs, log):
    self.options = options
    self.context = context
    self.workdir = workdir
    self.tool_classpath = tool_classpath
    self.confs = confs
    self.log = log

    self.coverage_dir = os.path.join(self.workdir, 'coverage')
    self.coverage_instrument_dir = os.path.join(self.coverage_dir, 'classes')
    self.coverage_console_file = os.path.join(self.coverage_dir, 'coverage.txt')
    self.coverage_xml_file = os.path.join(self.coverage_dir, 'coverage.xml')
    self.coverage_html_file = os.path.join(self.coverage_dir, 'html', 'index.html')

  @classmethod
  def from_task(cls, task):
    return cls(
      options=task.get_options(),
      context=task.context,
      workdir=task.workdir,
      tool_classpath=task.tool_classpath,
      confs=task.confs,
      log=task.context.log)


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

  def __init__(self, settings, copy2=shutil.copy2, copytree=shutil.copytree, is_file=os.path.isfile,
               safe_md=safe_mkdir):
    self._settings = settings
    options = settings.options
    self._context = settings.context
    self._coverage = options.coverage

    self._coverage_jvm_options = []
    for jvm_option in options.coverage_jvm_options:
      self._coverage_jvm_options.extend(safe_shlex_split(jvm_option))

    self._coverage_open = options.coverage_open
    self._coverage_force = options.coverage_force

    # Injecting these methods to make testing cleaner.
    self._copy2 = copy2
    self._copytree = copytree
    self._is_file = is_file
    self._safe_makedir = safe_md

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

  def initialize_instrument_classpath(self, targets, instrumentation_classpath):
    """Clones the existing runtime_classpath and corresponding binaries to instrumentation specific
    paths.

    :param targets: the targets for which we should create an instrumentation_classpath entry based
    on their runtime_classpath entry.
    """
    self._safe_makedir(self._settings.coverage_instrument_dir, clean=True)

    for target in targets:
      if not self.is_coverage_target(target):
        continue
      # Do not instrument transitive dependencies.
      paths = instrumentation_classpath.get_for_target(target)
      target_instrumentation_path = os.path.join(self._settings.coverage_instrument_dir, target.id)
      for (index, (config, path)) in enumerate(paths):
        # There are two sorts of classpath entries we see in the compile classpath: jars and dirs.
        # The branches below handle the cloning of those respectively.
        entry_instrumentation_path = os.path.join(target_instrumentation_path, str(index))
        if self._is_file(path):
          self._safe_makedir(entry_instrumentation_path, clean=True)
          self._copy2(path, entry_instrumentation_path)
          new_path = os.path.join(entry_instrumentation_path, os.path.basename(path))
        else:
          self._copytree(path, entry_instrumentation_path)
          new_path = entry_instrumentation_path

        instrumentation_classpath.remove_for_target(target, [(config, path)])
        instrumentation_classpath.add_for_target(target, [(config, new_path)])
        self._settings.log.debug(
          "runtime_classpath ({}) cloned to instrument_classpath ({})".format(path, new_path))
