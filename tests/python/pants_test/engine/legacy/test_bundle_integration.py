# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class BundleIntegrationTest(PantsRunIntegrationTest):

  def test_bundle_basic(self):
    args = ['-q', 'bundle', 'testprojects/src/java/org/pantsbuild/testproject/bundle']
    self.do_command(*args, success=True, enable_v2_engine=True)
