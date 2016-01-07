# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pants.base.workunit import WorkUnit
from pants.goal.outcomes import Outcomes
from pants.util.contextutil import temporary_file_path


class OutcomesTest(unittest.TestCase):
  def test_write_outcomes(self):
    with temporary_file_path() as tmppath:
      outcome = Outcomes(tmppath)
      outcome.add_outcome('key1', WorkUnit.ABORTED)
      outcome.add_outcome('key2', WorkUnit.SUCCESS)
      self.assertEquals({'key1': 'ABORTED', 'key2': 'SUCCESS'}, outcome.get_all())

      with open(tmppath, 'r') as tmpfile:
        contents = tmpfile.read()
      self.assertIn('key1: ABORTED\n', contents)
      self.assertIn('key2: SUCCESS\n', contents)
