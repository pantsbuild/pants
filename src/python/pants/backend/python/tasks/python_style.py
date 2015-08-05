# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import copy
import inspect
import os
import pkgutil
import re
import sys
import xml.etree.ElementTree as ETf

from pkg_resources import resource_string

from pants.backend.python.targets.python_target import PythonTarget
from pants.backend.python.tasks.checkstyle.common import Nit, PythonFile
from pants.backend.python.tasks.checkstyle.plugins import list_plugins
from pants.backend.python.tasks.checkstyle.plugins.list_plugins import list_plugins
from pants.backend.python.tasks.python_task import PythonTask
# from pants.base.exceptions import TaskError
from pants.option.options import Options
from pants.util.dirutil import safe_open


class PythonStyleException(Exception):pass

_NOQA_LINE_SEARCH = re.compile(r'# noqa\b').search
_NOQA_FILE_SEARCH = re.compile(r'# (flake8|checkstyle): noqa$').search

def noqa_line_filter(python_file, line_number):
  return _NOQA_LINE_SEARCH(python_file.lines[line_number]) is not None


def noqa_file_filter(python_file):
  return any(_NOQA_FILE_SEARCH(line) is not None for line in python_file.lines)

def apply_filter(python_file, checker):
  if noqa_file_filter(python_file):
    return

  plugin = checker(python_file)

  for nit in plugin:
    if nit._line_number is None:
      yield nit
      continue

    nit_slice = python_file.line_range(nit._line_number)

    for line_number in range(nit_slice.start, nit_slice.stop):
      if noqa_line_filter(python_file, line_number):
        break
    else:
      yield nit


class PythonStyle(PythonTask):
  _PYTHON_SOURCE_EXTENSION = '.py'

  def __init__(self, *args, **kwargs):
    super(PythonStyle, self).__init__(*args, **kwargs)

  @classmethod
  def register_options(cls, register):
    super(PythonStyle, cls).register_options(register)
    register('--args', action='append', help='Run with these extra args to main().')
    register('--list', action='store_true', default=False,
             help='List available plugins and exit.')
    register('--enable-plugins', action='append', type=str, default=[],
             help='Explicitly list plugins to enable.')
    register('--disable-plugins', action='append', type=str, default=[],
             help='Explicitly list plugins to disable.')
    register('--all', action='store_true', default=False,
             help='Run all plugins.')
    register('--severity', default='COMMENT', type=str,
             help='Only messages at this severity or higher are logged. [COMMENT WARNING ERROR].')
    register('--strict', default=False, action='store_true',
             help='If enabled, have non-zero exit status for any nit at WARNING or higher.')
    register('--suppress', type=str, default=None,
             help='Takes a XML file where specific rules on specific files will be skipped.')
    register('--fail', default=True, action='store_true',
             help='Prevent test failure but still produce output for problems.')

  @classmethod
  def supports_passthru_args(cls):
    return True

  def _is_checked(self, target):
    return (isinstance(target, PythonTarget) and
            target.has_sources(self._PYTHON_SOURCE_EXTENSION) and
            (not target.is_synthetic))

  def checkstyle(self, targets, sources):
    def skip_plugins(plugins, plugins_to_skip):
      plugins_map = dict((plugin.__name__, plugin) for plugin in plugins)
      for plugin in self.get_options().disable_plugins:
        plugins_map.pop(plugin, None)
      return list(plugins_map.values())

    def parse_and_apply_filter(filename, plugins, should_fail, severity, is_strict):
      try:
        python_file = PythonFile.parse(filename)
      except SyntaxError as e:
        print('%s:SyntaxError: %s' % (filename, e))
        return should_fail
      for checker in plugins:
        for nit in apply_filter(python_file, checker):
          if nit.severity >= severity:
            print(nit)
            print()
          should_fail |= nit.severity >= Nit.ERROR or (
              nit.severity >= Nit.WARNING and is_strict)
      return should_fail

    options = self.get_options()
    if not(options.enable_plugins or options.disable_plugins or options.all or options.list):
      return  # Disable the any checks by default

    plugins = list_plugins()

    if options.list:
      for plugin in plugins:
        print('\n%s' % plugin.__name__)
        if plugin.__doc__:
          for line in plugin.__doc__.splitlines():
            print('    %s' % line)
        else:
          print('    No information')
      return

    if options.enable_plugins:
      plugins_map = dict((plugin.__name__, plugin) for plugin in plugins)
      plugins = list(filter(None, map(plugins_map.get, options.enable_plugins)))

    if options.disable_plugins:
      plugins = skip_plugins(plugins, options.skip_plugins)

    if options.suppress:
      root = ET.parse(options.options.suppress).getroot()
    else:
      root = []

    severity = Nit.COMMENT
    for number, name in Nit.SEVERITY.items():
      if name == options.severity:
        severity = number

    should_fail = False
    for filename in sources:
      plugins_copy = copy.deepcopy(plugins)
      for child in root:
        path = child.attrib['files']
        rules = child.attrib['checks']
        if filename == path or filename.startswith(path):
          if rules == '.*':
            break
          root.remove(child)  # improve performance
          plugins_to_skip = rules.split('|')
          plugins_copy = skip_plugins(plugins_copy, plugins_to_skip)
      else:
        should_fail |= parse_and_apply_filter(
          filename, plugins_copy, should_fail, severity, options.strict)
    if should_fail and options.fail:
      raise PythonStyleException()

  def execute(self):
    targets = self.context.targets(self._is_checked)
    sources = self.calculate_sources(targets)

    if sources:
      self.checkstyle(targets, sources)

  def calculate_sources(self, targets):
    sources = set()
    for target in targets:
      sources.update(source for source in target.sources_relative_to_buildroot()
                     if source.endswith(self._PYTHON_SOURCE_EXTENSION))
    return sources
