# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from contextlib import contextmanager
from textwrap import dedent

from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest
from pants.util.contextutil import temporary_dir


class TestUnknownArgumentsIntegration(PantsRunIntegrationTest):
    @contextmanager
    def temp_target_spec(self, **kwargs):
        with temporary_dir(".") as tmpdir:
            spec = os.path.basename(tmpdir)
            with open(os.path.join(tmpdir, "BUILD"), "w") as f:
                f.write(
                    dedent(
                        """
                        java_library(name='{name}',
                          {parameters}
                        )
                        """
                    ).format(
                        name=spec,
                        parameters="".join(
                            '\n    {}="{}",'.format(key, val) for key, val in kwargs.items()
                        ),
                    )
                )
            yield spec

    def test_future_params(self):
        param = "nonexistent_parameter"
        with self.temp_target_spec(**{param: "value"}) as spec:
            run = self.run_pants(
                [
                    f'--target-arguments-ignored={{"java_library": ["{param}"]}}',
                    "-ldebug",
                    "clean-all",
                    spec,
                ]
            )
            self.assert_success(run)
            self.assertIn(f"{spec} ignoring the unimplemented arguments: {param}", run.stderr_data)

    def test_unknown_params(self):
        future = "nonexistent_parameter"
        unknown = "unexpected_nonexistent_parameter"
        with self.temp_target_spec(**{future: "value", unknown: "other value"}) as spec:
            run = self.run_pants(
                [f'--target-arguments-ignored={{"java_library": ["{future}"]}}', "clean-all", spec]
            )
            self.assert_failure(run)
            self.assertIn(f"Invalid target {spec}", run.stderr_data)
