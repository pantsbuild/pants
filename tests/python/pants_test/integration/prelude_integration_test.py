# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from textwrap import dedent

from pants.testutil.pants_integration_test import PantsIntegrationTest


class PreludeIntegrationTest(PantsIntegrationTest):
    def test_build_file_prelude(self) -> None:
        sources = {
            "prelude.py": dedent(
                """\
                def make_binary_macro():
                    python_binary(name="main", sources=["main.py"])
                """
            ),
            "BUILD": "make_binary_macro()",
            "main.py": "print('Hello world!')",
        }
        with self.setup_tmpdir(sources) as tmpdir:
            run = self.run_pants(
                [
                    "--backend-packages=pants.backend.python",
                    f"--build-file-prelude-globs={os.path.join(tmpdir, 'prelude.py')}",
                    "run",
                    f"{tmpdir}:main",
                ]
            )
        run.assert_success()
        assert "Hello world!" in run.stdout
