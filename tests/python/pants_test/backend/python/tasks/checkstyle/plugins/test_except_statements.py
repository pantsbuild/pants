# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.python.tasks.checkstyle.common import Nit, PythonFile
from pants.backend.python.tasks.checkstyle.except_statements import ExceptStatements


EXCEPT_TEMPLATE = """
try:                  # 001
  1 / 0
%s
  pass
"""


def nits_from(clause):
  return list(ExceptStatements(PythonFile.from_statement(EXCEPT_TEMPLATE % clause)).nits())


def test_except_statements():
  for clause in ('except:', 'except :', 'except\t:'):
    nits = nits_from(clause)
    assert len(nits) == 1
    assert nits[0].code == 'T803'
    assert nits[0].severity == Nit.ERROR

  for clause in (
      'except KeyError, e:',
      'except (KeyError, ValueError), e:',
      'except KeyError, e :',
      'except (KeyError, ValueError), e\t:'):
    nits = nits_from(clause)
    assert len(nits) == 1
    assert nits[0].code == 'T601'
    assert nits[0].severity == Nit.ERROR

  for clause in (
      'except KeyError:',
      'except KeyError as e:',
      'except (KeyError, ValueError) as e:',
      'except (KeyError, ValueError) as e:'):
    nits = nits_from(clause)
    assert len(nits) == 0
