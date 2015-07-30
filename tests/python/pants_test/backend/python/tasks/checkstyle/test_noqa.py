# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.python.tasks.checkstyle.common import CheckstylePlugin, PythonFile
from pants.backend.python.tasks.python_style import apply_filter


class Rage(CheckstylePlugin):
  def nits(self):
    for line_no, _ in self.python_file.enumerate():
      yield self.error('T999', 'I hate everything!', line_no)


def test_noqa_line_filter():
  nits = apply_filter(PythonFile.from_statement("""
    print('This is not fine')
    print('This is fine')  # noqa
  """), Rage)
  
  nits = list(nits)
  assert len(nits) == 1, ('Actually got nits: %s' % (' '.join('%s:%s' % (nit._line_number, nit) for nit in nits)))
  assert nits[0].code == 'T999'


def test_noqa_file_filter():
  nits = apply_filter(PythonFile.from_statement("""
    # checkstyle: noqa
    print('This is not fine')
    print('This is fine')
  """), Rage)
  
  nits = list(nits)
  assert len(nits) == 0
