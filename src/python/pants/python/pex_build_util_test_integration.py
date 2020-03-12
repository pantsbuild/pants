# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import subprocess

from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest
from pants.util.contextutil import temporary_dir


class PexBuildUtilIntegrationTest(PantsRunIntegrationTest):

    tests_target_address = "testprojects/src/python/python_targets:test-multiplatform-binary"

    def test_multiplatform_python_binary(self):
        with temporary_dir() as tmp_dir:
            self.do_command(
                "binary", self.tests_target_address, config={"GLOBAL": {"pants_distdir": tmp_dir}}
            )

            pex_path = os.path.join(tmp_dir, "test-multiplatform-binary.pex")
            assert os.path.isfile(pex_path)
            pex_execution_result = subprocess.run([pex_path], stdout=subprocess.PIPE, check=True)
            assert pex_execution_result.stdout.decode() == "hey!"
