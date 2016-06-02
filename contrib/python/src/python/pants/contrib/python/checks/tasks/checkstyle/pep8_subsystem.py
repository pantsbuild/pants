# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.contrib.python.checks.tasks.checkstyle.plugin_subsystem_base import PluginSubsystemBase


class PEP8Subsystem(PluginSubsystemBase):
  options_scope = 'pycheck-pep8'

  # Code reference is here: https://pep8.readthedocs.io/en/latest/intro.html#error-codes
  DEFAULT_IGNORE_CODES = (
    # continuation_line_indentation
    'E121', # continuation line under-indented for hanging indent
    'E124', # closing bracket does not match visual indentation
    'E125', # continuation line with same indent as next logical line
    'E127', # continuation line over-indented for visual indent
    'E128', # continuation line under-indented for visual indent

    # imports_on_separate_lines
    'E401', # multiple imports on one line

    # indentation
    'E111', # indentation is not a multiple of four

    # trailing_whitespace
    'W291', # trailing whitespace
    'W293', # blank line contains whitespace

    # multiple statements
    # A common (acceptable) exception pattern at Twitter is:
    #   class MyClass(object):
    #     class Error(Exception): pass
    #     class DerpError(Error): pass
    #     class HerpError(Error): pass
    # We disable the pep8.py checking for these and instead have a more lenient filter
    # in the whitespace checker.
    'E701', # multiple statements on one line (colon)
    'E301', # expected 1 blank line, found 0
    'E302', # expected 2 blank lines, found 0
    'W292', # no newline at end of file
  )

  @classmethod
  def register_options(cls, register):
    super(PEP8Subsystem, cls).register_options(register)
    register('--ignore', fingerprint=True, type=list, default=cls.DEFAULT_IGNORE_CODES,
             help='Prevent test failure but still produce output for problems.')
    register('--max-length', fingerprint=True, type=int, default=100,
             help='Max line length to use for PEP8 checks.')

  def get_plugin_type(self):
    from pants.contrib.python.checks.tasks.checkstyle.pep8 import PEP8Checker
    return PEP8Checker
