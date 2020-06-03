# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest


class BackendIndependenceTest(PantsRunIntegrationTest):
    """Verifies that this backend works with no other backends present."""

    @classmethod
    def hermetic(cls):
        return True

    @pytest.mark.skip(reason="flaky: https://github.com/pantsbuild/pants/issues/7168")
    def test_independent_test_run(self):
        pants_run = self.run_pants(
            command=["test", "examples/tests/java/org/pantsbuild/example/hello/greet"],
            config={
                "GLOBAL": {
                    "pythonpath": ["%(buildroot)s/pants-plugins/src/python"],
                    # We need the internal backend for the repo specifications in the example BUILD files.
                    # TODO: Don't use the real pants repos in example code, which are ideally self-contained.
                    "backend_packages": ["pants.backend.jvm", "internal_backend.repositories"],
                },
                "source": {"root_patterns": ["tests/java"]},
            },
        )
        self.assert_success(pants_run)
