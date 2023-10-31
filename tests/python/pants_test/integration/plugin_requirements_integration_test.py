# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import os
import sys

from pants.base.build_environment import get_buildroot
from pants.testutil.pants_integration_test import run_pants


def test_plugin_with_dependencies() -> None:
    testproject_backend_src_dir = os.path.join(
        get_buildroot(), "testprojects/pants-plugins/src/python"
    )
    testproject_backend_pkg_name = "test_pants_plugin"

    pants_run = run_pants(
        [
            "--no-pantsd",
            f"--backend-packages=['{testproject_backend_pkg_name}']",
            "help",
        ],
        extra_env={
            "_IMPORT_REQUIREMENT": "True",
            "PYTHONPATH": os.pathsep.join(sys.path + [testproject_backend_src_dir]),
        },
    )
    pants_run.assert_success()
