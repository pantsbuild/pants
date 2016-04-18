# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import pep8

from pants.contrib.python.checks.tasks.checkstyle.common import CheckstylePlugin, Nit, PythonFile


class PEP8Error(Nit):
  def __init__(self, python_file, code, line_number, text):
    line_range = python_file.line_range(line_number)
    super(PEP8Error, self).__init__(code, Nit.ERROR, python_file, text, line_range)


class PantsReporter(pep8.BaseReport):
  def init_file(self, filename, lines, expected, line_offset):
    super(PantsReporter, self).init_file(filename, lines, expected, line_offset)
    self._python_file = PythonFile.parse(filename)
    self._errors = []

  def error(self, line_number, offset, text, check):
    code = super(PantsReporter, self).error(line_number, offset, text, check)
    if code:
      self._errors.append(PEP8Error(self._python_file, code, line_number, text[5:]))
    return code

  @property
  def errors(self):
    return self._errors


class PEP8Checker(CheckstylePlugin):
  """Enforce PEP8 checks from the pep8 tool."""

  def __init__(self, *args, **kwargs):
    super(PEP8Checker, self).__init__(*args, **kwargs)
    self.STYLE_GUIDE = pep8.StyleGuide(
        max_line_length=self.options.max_length,
        verbose=False,
        reporter=PantsReporter,
        ignore=self.options.ignore)

  def nits(self):
    report = self.STYLE_GUIDE.check_files([self.python_file.filename])
    return report.errors
