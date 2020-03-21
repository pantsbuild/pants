# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import os
import subprocess

from pex.interpreter import PythonInterpreter

from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest
from pants.util.collections import assert_single_element
from pants.util.contextutil import open_zip, temporary_dir


class PexBuildUtilIntegrationTest(PantsRunIntegrationTest):

    binary_target_address = "testprojects/src/python/python_targets:test"

    def test_ipex_gets_imprecise_constraint(self) -> None:
        cur_interpreter_id = PythonInterpreter.get().identity
        interpreter_name = cur_interpreter_id.requirement.name
        major, minor, patch = cur_interpreter_id.version

        # Pin the selected interpreter to the one used by pants to execute this test.
        cur_interpreter_constraint = f"{interpreter_name}=={major}.{minor}.{patch}"

        # Validate the the .ipex file specifically matches the major and minor versions, but allows
        # any patch version.
        imprecise_constraint = f"{interpreter_name}=={major}.{minor}.*"

        with temporary_dir() as tmp_dir:
            self.do_command(
                "--binary-py-generate-ipex",
                "binary",
                self.binary_target_address,
                config={
                    "GLOBAL": {"pants_distdir": tmp_dir},
                    "python-setup": {"interpreter_constraints": [cur_interpreter_constraint]},
                },
            )

            pex_path = os.path.join(tmp_dir, "test.ipex")
            assert os.path.isfile(pex_path)
            pex_execution_result = subprocess.run([pex_path], stdout=subprocess.PIPE, check=True)
            assert pex_execution_result.stdout.decode() == "test!\n"

            with open_zip(pex_path) as zf:
                info = json.loads(zf.read("PEX-INFO"))
                constraint = assert_single_element(info["interpreter_constraints"])
                assert constraint == imprecise_constraint
