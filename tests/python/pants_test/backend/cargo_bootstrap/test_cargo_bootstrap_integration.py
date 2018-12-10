# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os

from pants.option.scope import GLOBAL_SCOPE_CONFIG_SECTION
from pants.util.contextutil import temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class CargoBootstrapIntegrationTest(PantsRunIntegrationTest):

  def test_bootstrap(self):
    pants_run = self.run_pants(['bootstrap-native-engine', 'src/rust/engine:new-cargo'])

    # TODO: check that the engine is output to the dist dir, check that the engine works
    # somehow?
    self.assert_success(pants_run)
