# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import re
from collections import namedtuple

from pants.backend.python.targets.python_target import PythonTarget
from pants.backend.python.tasks.checkstyle.common import Nit, PythonFile
from pants.backend.python.tasks.checkstyle.file_excluder import FileExcluder
from pants.backend.python.tasks.checkstyle.register_plugins import register_plugins
from pants.backend.python.tasks.python_task import PythonTask
from pants.base.exceptions import TaskError


_NOQA_LINE_SEARCH = re.compile(r'# noqa\b').search
_NOQA_FILE_SEARCH = re.compile(r'# (flake8|checkstyle): noqa$').search
lint_plugin = namedtuple('lint_plugin', 'name checker')


def noqa_line_filter(python_file, line_number):
  return _NOQA_LINE_SEARCH(python_file.lines[line_number]) is not None


def noqa_file_filter(python_file):
  return any(_NOQA_FILE_SEARCH(line) is not None for line in python_file.lines)


class PythonCheckStyleTask(PythonTask):
  _PYTHON_SOURCE_EXTENSION = '.py'
  _plugins = []
  _subsystems = tuple()

  def __init__(self, *args, **kwargs):
    super(PythonCheckStyleTask, self).__init__(*args, **kwargs)
    self._plugins = [plugin for plugin in self._plugins
                      if not plugin.checker.subsystem.global_instance().get_options().skip]
    self.options = self.get_options()

  @classmethod
  def global_subsystems(cls):
    return super(PythonTask, cls).global_subsystems() + cls._subsystems

  @classmethod
  def register_options(cls, register):
    super(PythonCheckStyleTask, cls).register_options(register)
    register('--severity', default='COMMENT', type=str,
             help='Only messages at this severity or higher are logged. [COMMENT WARNING ERROR].')
    register('--strict', default=False, action='store_true',
             help='If enabled, have non-zero exit status for any nit at WARNING or higher.')
    register('--skip', default=False, action='store_true',
             help='If enabled, skip this style checker.')
    register('--suppress', type=str, default=None,
             help='Takes a XML file where specific rules on specific files will be skipped.')
    register('--fail', default=True, action='store_true',
             help='Prevent test failure but still produce output for problems.')

  @classmethod
  def supports_passthru_args(cls):
    return True

  def _is_checked(self, target):
    return isinstance(target, PythonTarget) and target.has_sources(self._PYTHON_SOURCE_EXTENSION)

  @classmethod
  def clear_plugins(cls):
    """Clear all current plugins registered"""
    cls._plugins = []

  @classmethod
  def register_plugin(cls, name, checker):
    """Register plugin to be used run as part of Python Style checks

    :param name: (string) Name of the method plugin
    :param checker: (CheckstylePlugin) Plugin subclass
    """
    plugin = lint_plugin(name=name, checker=checker)
    cls._plugins.append(plugin)
    cls._subsystems += (plugin.checker.subsystem, )

  def get_nits(self, python_file):
    """Iterate over the instances style checker and yield Nits

    :param python_file: PythonFile Object
    """
    if noqa_file_filter(python_file):
      return

    if self.options.suppress:
      # Filter out any suppressed plugins
      excluder = FileExcluder(self.options.suppress, self.context.log)
      check_plugins = [plugin for plugin in self._plugins
                       if excluder.should_include(python_file.filename, plugin.name)]
    else:
      check_plugins = self._plugins

    for plugin in check_plugins:
      for nit in plugin.checker(python_file):
        if nit._line_number is None:
          yield nit
          continue

        nit_slice = python_file.line_range(nit._line_number)
        for line_number in range(nit_slice.start, nit_slice.stop):
          if noqa_line_filter(python_file, line_number):
            break
          else:
            yield nit

  def check_file(self, filename):
    """Process python file looking for indications of problems.
    :param filename: (str) Python source filename
    :return: (bool) flag indicating failure
    """
    try:
      python_file = PythonFile.parse(filename)
    except SyntaxError as e:
      print('{filename}:SyntaxError: {error}'.format(filename=filename, error=e))
      return True

    # If the user specifies an invalid severity use comment
    severity = Nit.SEVERITY.get(self.options.severity, Nit.COMMENT)

    should_fail = False
    fail_threshold = Nit.WARNING if self.options.strict else Nit.ERROR

    for i, nit in enumerate(self.get_nits(python_file)):
      if i == 0:
        print()  # add an extra newline to clean up the output only if we have nits
      if nit.severity >= severity:
        print('{nit}\n'.format(nit=nit))
      should_fail |= (nit.severity >= fail_threshold)
    return should_fail

  def checkstyle(self, sources):
    """ Iterate over sources and run checker on each file

    Files can be suppressed with a --suppress option which takes an xml file containing
    file paths that have exceptions and the plugins they need to ignore.
    :param sources: iterable containing source file names.
    :return: Boolean indicating problems found
    """
    should_fail = False
    for filename in sources:
      should_fail |= self.check_file(filename)

    if should_fail and self.options.fail:
      raise TaskError('Python Style issues found', exit_code=should_fail)

  def execute(self):
    """Run Checkstyle on all found source files"""
    if self.options.skip:
      return

    targets = self.context.targets(self._is_checked)
    sources = self.calculate_sources(targets)

    if sources:
      return self.checkstyle(sources)

  def calculate_sources(self, targets):
    """Generate a set of source files from the given targets"""
    sources = set()
    for target in targets:
      sources.update(
        source for source in target.sources_relative_to_buildroot()
        if source.endswith(self._PYTHON_SOURCE_EXTENSION)
      )
    return sources


register_plugins(PythonCheckStyleTask)
