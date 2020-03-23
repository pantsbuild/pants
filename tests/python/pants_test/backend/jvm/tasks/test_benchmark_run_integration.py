# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest


class BenchmarkRunIntegrationTest(PantsRunIntegrationTest):
    def test_running_an_empty_benchmark_target(self):
        pants_run = self.run_pants(
            [
                "bench",
                "--target=org.pantsbuild.testproject.bench.CaliperBench",
                "testprojects/src/java/org/pantsbuild/testproject/bench",
            ]
        )
        self.assert_success(pants_run)
