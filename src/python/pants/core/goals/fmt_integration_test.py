# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re

from pants.testutil.pants_integration_test import PantsIntegrationTest, ensure_daemon
from pants.util.dirutil import read_file


class FmtIntegrationTest(PantsIntegrationTest):
    @ensure_daemon
    def test_fmt_then_edit(self):
        f = "examples/src/python/example/hello/greet/greet.py"
        with self.temporary_workdir() as workdir:

            def run() -> None:
                result = self.run_pants_with_workdir(
                    [
                        "--backend-packages=['pants.backend.python', 'pants.backend.python.lint.black']",
                        "fmt",
                        f,
                    ],
                    workdir=workdir,
                )
                self.assert_success(result)

            # Run once to start up, and then capture the file content.
            run()
            good_content = read_file(f)

            # Edit the file.
            with self.with_overwritten_file_content(
                f, lambda c: re.sub(b"def greet", b"def  greet", c)
            ):
                assert good_content != read_file(f)

                # Re-run and confirm that the file was fixed.
                run()
                assert good_content == read_file(f)
