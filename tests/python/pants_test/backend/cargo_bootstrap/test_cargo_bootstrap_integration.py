# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.option.scope import GLOBAL_SCOPE_CONFIG_SECTION
from pants.util.contextutil import temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class CargoBootstrapIntegrationTest(PantsRunIntegrationTest):

  def test_bootstrap(self):
    with temporary_dir() as tmp_dir:
      with self.mock_buildroot(dirs_to_copy=['src/rust/engine']) as buildroot, buildroot.pushd():
        pants_run = self.run_pants_with_workdir(
          ['bootstrap-native-engine', 'src/rust/engine:new-cargo'],
          workdir=os.path.join(buildroot.new_buildroot, '.pants.d'),
          build_root=buildroot.new_buildroot,
          config={
            GLOBAL_SCOPE_CONFIG_SECTION: {
              'pants_distdir': tmp_dir,
            },
          }
        )

        # TODO: check that the engine is output to the dist dir, check that the engine works
        # somehow?
        self.assert_success(pants_run)
