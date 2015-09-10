# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import pep8

from pants.backend.python.tasks.checkstyle.common import CheckstylePlugin, Nit, PythonFile
from pants.option.custom_types import list_option
from pants.subsystem.subsystem import Subsystem


class PEP8Subsystem(Subsystem):
  options_scope = 'pycheck-pep8'

  @classmethod
  def register_options(cls, register):
    super(PEP8Subsystem, cls).register_options(register)
    register('--ignore', type=list_option, default=DEFAULT_IGNORE_CODES,
             help='Prevent test failure but still produce output for problems.')
    register('--max-length', type=int, default=100,
             help='Max line length to use for PEP8 checks.')
    register('--skip', default=False, action='store_true',
             help='If enabled, skip this style checker.')


class PEP8Error(Nit):
  def __init__(self, python_file, code, line_number, offset, text, doc):
    super(PEP8Error, self).__init__(code, Nit.ERROR, python_file, text, line_number)


class PantsReporter(pep8.BaseReport):
  def init_file(self, filename, lines, expected, line_offset):
    super(PantsReporter, self).init_file(filename, lines, expected, line_offset)
    self._python_file = PythonFile.parse(filename)
    self._twitter_errors = []

  def error(self, line_number, offset, text, check):
    code = super(PantsReporter, self).error(line_number, offset, text, check)
    if code:
      self._twitter_errors.append(
          PEP8Error(self._python_file, code, line_number, offset, text[5:], check.__doc__))
    return code

  @property
  def twitter_errors(self):
    return self._twitter_errors


DEFAULT_IGNORE_CODES = (
  # continuation_line_indentation
  'E121',
  'E124',
  'E125',
  'E127',
  'E128',

  # imports_on_separate_lines
  'E401',

  # indentation
  'E111',

  # trailing_whitespace
  'W291',
  'W293',

  # multiple statements
  # A common (acceptable) exception pattern at Twitter is:
  #   class MyClass(object):
  #     class Error(Exception): pass
  #     class DerpError(Error): pass
  #     class HerpError(Error): pass
  # We disable the pep8.py checking for these and instead have a more lenient filter
  # in the whitespace checker.
  'E701',
  'E301',
  'E302',
  'W292'
)


class PEP8Checker(CheckstylePlugin):
  """Enforce PEP8 checks from the pep8 tool."""
  subsystem = PEP8Subsystem

  def __init__(self, *args, **kwargs):
    super(PEP8Checker, self).__init__(*args, **kwargs)
    self.STYLE_GUIDE = pep8.StyleGuide(
        max_line_length=self.subsystem.global_instance().get_options().max_length,
        verbose=False,
        reporter=PantsReporter,
        ignore=self.subsystem.global_instance().get_options().ignore)

  def nits(self):
    report = self.STYLE_GUIDE.check_files([self.python_file.filename])
    return report.twitter_errors
