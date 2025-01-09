# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.testutil.pants_integration_test import run_pants


def test_plugin_with_dependencies() -> None:
    testproject_backend_pkg_name = "test_pants_plugin"

    pants_run = run_pants(
        [
            "--no-pantsd",
            f"--backend-packages=['{testproject_backend_pkg_name}']",
            "help",
        ],
        config={"GLOBAL": {"pythonpath": ["%(buildroot)s/testprojects/pants-plugins/src/python"]}},
        extra_env={
            "_IMPORT_REQUIREMENT": "True",
        },
    )
    pants_run.assert_success()
