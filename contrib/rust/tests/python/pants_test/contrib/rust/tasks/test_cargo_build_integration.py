# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class CargoTaskBuildIntegrationTest(PantsRunIntegrationTest):

  def test_cargo_compile_targets_nightly(self):
    args = ['compile', 'contrib/rust/examples/src/rust/::', '--bootstrap-cargo-toolchain=nightly']
    pants_run = self.run_pants(args)
    self.assert_success(pants_run)

  def test_cargo_compile_targets_nightly_2018_12_31(self):
    args = ['compile', 'contrib/rust/examples/src/rust/::',
            '--bootstrap-cargo-toolchain=nightly-2018-12-31']
    pants_run = self.run_pants(args)
    self.assert_success(pants_run)
