# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pants.base.workunit import WorkUnit
from pants.goal.outcomes import Outcomes


class OutcomesTest(unittest.TestCase):
  def test_write_outcomes(self):
    outcome = Outcomes()
    outcome.add_outcome('key1', WorkUnit.ABORTED)
    outcome.add_outcome('key2', WorkUnit.SUCCESS)
    self.assertEquals({'key1': 'ABORTED', 'key2': 'SUCCESS'}, outcome.get_all())
