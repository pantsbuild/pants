# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.util.contextutil import temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class CleanAllTest(PantsRunIntegrationTest):

  def test_clean_all_on_wrong_dir(self):
    with temporary_dir() as workdir:
      self.assert_failure(self.run_pants_with_workdir(["clean-all"], workdir))
