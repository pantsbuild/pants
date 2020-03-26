# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest


class JarDependencyIntegrationTest(PantsRunIntegrationTest):
    def test_resolve_relative(self):
        pants_run = self.run_pants(["resolve", "testprojects/3rdparty/org/pantsbuild/testprojects"])
        self.assert_success(pants_run)
