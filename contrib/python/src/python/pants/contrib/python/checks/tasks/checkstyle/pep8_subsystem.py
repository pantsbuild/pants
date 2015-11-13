# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.option.custom_types import list_option

from pants.contrib.python.checks.tasks.checkstyle.plugin_subsystem_base import PluginSubsystemBase


class PEP8Subsystem(PluginSubsystemBase):
  options_scope = 'pycheck-pep8'

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

  @classmethod
  def register_options(cls, register):
    super(PEP8Subsystem, cls).register_options(register)
    register('--ignore', type=list_option, default=cls.DEFAULT_IGNORE_CODES,
             help='Prevent test failure but still produce output for problems.')
    register('--max-length', type=int, default=100,
             help='Max line length to use for PEP8 checks.')

  def get_plugin_type(self):
    from pants.contrib.python.checks.tasks.checkstyle.pep8 import PEP8Checker
    return PEP8Checker
