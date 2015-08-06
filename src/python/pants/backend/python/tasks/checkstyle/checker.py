# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re
import xml.etree.ElementTree as ET

from pants.backend.python.targets.python_target import PythonTarget
from pants.backend.python.tasks.checkstyle.common import Nit, PythonFile
from pants.backend.python.tasks.python_task import PythonTask


_NOQA_LINE_SEARCH = re.compile(r'# noqa\b').search
_NOQA_FILE_SEARCH = re.compile(r'# (flake8|checkstyle): noqa$').search


def noqa_line_filter(python_file, line_number):
  return _NOQA_LINE_SEARCH(python_file.lines[line_number]) is not None


def noqa_file_filter(python_file):
  return any(_NOQA_FILE_SEARCH(line) is not None for line in python_file.lines)


class PythonCheckStyleTask(PythonTask):
  _PYTHON_SOURCE_EXTENSION = '.py'

  def __init__(self, *args, **kwargs):
    super(PythonCheckStyleTask, self).__init__(*args, **kwargs)
    self.options = self.get_options()

    self._checker = []  # Default to emtpy iterator
    self._name = 'DefaultStyleChecker'

  def _is_checked(self, target):
    return isinstance(target, PythonTarget) and target.has_sources(self._PYTHON_SOURCE_EXTENSION)

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

  def apply_filter(self, python_file):
    if noqa_file_filter(python_file):
      return

    for nit in self._checker(python_file):
      if nit._line_number is None:
        yield nit
        continue

      nit_slice = python_file.line_range(nit._line_number)
      for line_number in range(nit_slice.start, nit_slice.stop):
        if noqa_line_filter(python_file, line_number):
          break
        else:
          yield nit

  def parse_and_apply_filter(self, filename, severity):
    is_strict = self.options.strict
    should_fail = False
    try:
      python_file = PythonFile.parse(filename)
    except SyntaxError as e:
      print('%s:SyntaxError: %s' % (filename, e))
      return should_fail

    for nit in self.apply_filter(python_file):
      if nit.severity >= severity:
        print('{nit}\n'.format(nit=nit))
      should_fail |= nit.severity >= Nit.ERROR or (nit.severity >= Nit.WARNING and is_strict)
    return should_fail

  def checkstyle(self, sources):
    """ Iterate over sources and run checker on each file

    Files can be suppressed with a --suppress option which takes an xml file containing
    file paths that have exceptions and the plugins they need to ignore.
    :param sources: iterable containing source file names.
    :return: Boolean indicating problems found
    """
    self.options = self.get_options()
    if self.options.skip:
      return

    # If the user specifies an invalid severity use comment
    severity = Nit.SEVERITY.get(self.options.severity, Nit.COMMENT)

    # Update sources to strip out any suppressed files
    root = ET.parse(self.options.suppress).getroot() if self.options.suppress else []
    suppressions = {
      child.attrib['files']: True for child in root
      if child.attrib['checks'] == '.*' or self._name in child.attrib['checks'].split('|')
      }
    sources = [src for src in sources if os.path.dirname(src) not in suppressions]

    should_fail = False
    for filename in sources:
      should_fail |= self.parse_and_apply_filter(filename, severity)

    return should_fail and self.options.fail

  def execute(self):
    targets = self.context.targets(self._is_checked)
    sources = self.calculate_sources(targets)

    if sources:
      return self.checkstyle(sources)

  def calculate_sources(self, targets):
    sources = set()
    for target in targets:
      sources.update(
        source for source in target.sources_relative_to_buildroot()
        if source.endswith(self._PYTHON_SOURCE_EXTENSION)
      )
    return sources
