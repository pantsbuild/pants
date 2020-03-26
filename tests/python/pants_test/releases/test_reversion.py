# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import shutil

import requests
from pex.bin import pex as pex_main

from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest
from pants.util.contextutil import temporary_dir


class ReversionTest(PantsRunIntegrationTest):
    def test_run(self):
        with temporary_dir() as dest_dir:
            # Download an input whl.
            # TODO: Not happy about downloading things. Attempted to:
            #  ./pants setup-py --run="bdist_wheel" $target
            # but was unable to locate the output whl in the context of a test (perhaps due to
            # mismatched cwd?)
            name_template = "virtualenv-{}-py2.py3-none-any.whl"
            input_name = name_template.format("15.1.0")
            url = (
                "https://files.pythonhosted.org/packages/6f/86/"
                "3dc328ee7b1a6419ebfac7896d882fba83c48e3561d22ddddf38294d3e83/{}".format(input_name)
            )
            input_whl_file = os.path.join(dest_dir, input_name)
            with open(input_whl_file, "wb") as f:
                shutil.copyfileobj(requests.get(url, stream=True).raw, f)

            # Rewrite it.
            output_version = "9.1.9"
            output_name = name_template.format(output_version)
            output_whl_file = os.path.join(dest_dir, output_name)
            command = [
                "--quiet",
                "run",
                "src/python/pants/releases:reversion",
                "--",
                input_whl_file,
                dest_dir,
                output_version,
            ]
            self.assert_success(self.run_pants(command))
            self.assertTrue(os.path.isfile(output_whl_file))

            # Confirm that it can be consumed.
            output_pex_file = os.path.join(dest_dir, "out.pex")
            pex_main.main(["--disable-cache", "-o", output_pex_file, output_whl_file])
            self.assertTrue(os.path.isfile(output_pex_file))
