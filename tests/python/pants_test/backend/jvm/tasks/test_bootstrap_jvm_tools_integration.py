# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class BootstrapJvmToolsIntegrationTest(PantsRunIntegrationTest):

  def test_bootstrap_jarjar_succeeds_normally(self):
    # NB(gmalmquist): The choice of jarjar here is arbitrary; any jvm-tool that is integral to pants
    # would suffice (eg, nailgun or jar-tool).
    self.assert_success(self.run_pants(['clean-all']))
    pants_run = self.run_pants(['bootstrap', '3rdparty:junit'])
    self.assert_success(pants_run)

  def test_bootstrap_jarjar_failure(self):
    self.assert_success(self.run_pants(['clean-all']))
    pants_run = self.run_pants(['bootstrap', '--shader-jarjar="fake-target"', '3rdparty:junit'])
    self.assert_failure(pants_run)
    self.assertIn('fake-target', pants_run.stdout_data)
