# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.contrib.python.checks.tasks.checkstyle.plugin_test_base import \
  CheckstylePluginTestBase

from pants.contrib.python.checks.tasks.checkstyle.except_statements import ExceptStatements


EXCEPT_TEMPLATE = """
  try:                  # 001
    1 / 0
  {}
    pass
  """


class ExceptStatementsTest(CheckstylePluginTestBase):
  plugin_type = ExceptStatements

  def test_except_statements(self):
    for clause in ('except:', 'except :', 'except\t:'):
      self.assertNit(EXCEPT_TEMPLATE.format(clause), 'T803')

    for clause in (
        'except KeyError, e:',
        'except (KeyError, ValueError), e:',
        'except KeyError, e :',
        'except (KeyError, ValueError), e\t:'):
      self.assertNit(EXCEPT_TEMPLATE.format(clause), 'T601')

    for clause in (
        'except KeyError:',
        'except KeyError as e:',
        'except (KeyError, ValueError) as e:',
        'except (KeyError, ValueError) as e:'):
      self.assertNoNits(EXCEPT_TEMPLATE.format(clause))
