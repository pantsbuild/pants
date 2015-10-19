# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shutil
from abc import ABCMeta, abstractmethod, abstractproperty

from pants.backend.jvm.tasks.classpath_util import ClasspathUtil
from pants.util.dirutil import safe_mkdir
from pants.util.strutil import safe_shlex_split


class Coverage(object):
  """Base class for emma-like coverage processors. Do not instantiate."""
  __metaclass__ = ABCMeta

  @classmethod
  def register_options(cls, register, register_jvm_tool):
    register('--coverage-patterns', advanced=True, action='append',
             help='Restrict coverage measurement. Values are class name prefixes in dotted form '
                  'with ? and * wildcards. If preceded with a - the pattern is excluded. For '
                  'example, to include all code in org.pantsbuild.raven except claws and the eye '
                  'you would use: {flag}=org.pantsbuild.raven.* {flag}=-org.pantsbuild.raven.claw '
                  '{flag}=-org.pantsbuild.raven.Eye.'.format(flag='--coverage_patterns'))
    register('--coverage-jvm-options', advanced=True, action='append',
             help='JVM flags to be added when running the coverage processor. For example: '
                  '{flag}=-Xmx4g {flag}=-XX:MaxPermSize=1g'.format(flag='--coverage-jvm-options'))
    register('--coverage-open', action='store_true',
             help='Open the generated HTML coverage report in a browser. Implies --coverage.')
    register('--coverage-force', advanced=True, action='store_true',
             help='Attempt to run the reporting phase of coverage even if tests failed '
                  '(defaults to False, as otherwise the coverage results would be unreliable).')

  def __init__(self, task_exports, context):
    options = task_exports.task_options
    self._task_exports = task_exports
    self._context = context
    self._coverage = options.coverage
    self._coverage_filters = options.coverage_patterns or []

    self._coverage_jvm_options = []
    for jvm_option in options.coverage_jvm_options:
      self._coverage_jvm_options.extend(safe_shlex_split(jvm_option))

    self._coverage_dir = os.path.join(task_exports.workdir, 'coverage')
    self._coverage_instrument_dir = os.path.join(self._coverage_dir, 'classes')
    # TODO(ji): These may need to be transferred down to the Emma class, as the suffixes
    # may be emma-specific. Resolve when we also provide cobertura support.
    self._coverage_metadata_file = os.path.join(self._coverage_dir, 'coverage.em')
    self._coverage_file = os.path.join(self._coverage_dir, 'coverage.ec')
    self._coverage_console_file = os.path.join(self._coverage_dir, 'coverage.txt')
    self._coverage_xml_file = os.path.join(self._coverage_dir, 'coverage.xml')
    self._coverage_html_file = os.path.join(self._coverage_dir, 'html', 'index.html')
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

  def get_coverage_patterns(self, targets):
    if self._coverage_filters:
      return self._coverage_filters
    else:
      classes_under_test = set()
      classpath_products = self._context.products.get_data('runtime_classpath')

      def add_sources_under_test(tgt):
        if self.is_coverage_target(tgt):
          contents = ClasspathUtil.classpath_contents(
            (tgt,),
            classpath_products,
            confs=self._task_exports.confs,
            transitive=False)
          for f in contents:
            clsname = ClasspathUtil.classname_for_rel_classfile(f)
            if clsname:
              classes_under_test.add(clsname)

      for target in targets:
        target.walk(add_sources_under_test)
      return classes_under_test

  def initialize_instrument_classpath(self, targets):
    """Clones the existing runtime_classpath and corresponding binaries to instrumentation specific
    paths.

    :param targets: the targets which should be mutated.
    :returns the instrument_classpath ClasspathProducts containing the mutated paths.
    """
    safe_mkdir(self._coverage_instrument_dir, clean=True)

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
          shutil.copy2(path, self._coverage_instrument_dir)
          new_path = os.path.join(self._coverage_instrument_dir, os.path.basename(path))
        else:
          files = os.listdir(path)
          for file in files:
            shutil.copy2(file, self._coverage_instrument_dir)
          new_path = self._coverage_instrument_dir

        instrumentation_classpath.remove_for_target(target, [(config, path)])
        instrumentation_classpath.add_for_target(target, [(config, new_path)])
        self._context.log.debug(
          "runtime_classpath ({}) mutated to instrument_classpath ({})".format(path, new_path))
    return instrumentation_classpath
