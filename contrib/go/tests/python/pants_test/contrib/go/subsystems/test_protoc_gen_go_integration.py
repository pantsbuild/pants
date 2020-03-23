# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest


class ProtocGenGoTest(PantsRunIntegrationTest):
    def test_go_compile_distance(self):
        args = ["compile", "contrib/go/examples/src/go/distance"]
        pants_run = self.run_pants(args)
        self.assert_success(pants_run)

    def test_go_compile_grpc(self):
        args = ["compile", "contrib/go/examples/src/protobuf/org/pantsbuild/example/grpc:grpc-go"]
        pants_run = self.run_pants(args)
        self.assert_success(pants_run)
