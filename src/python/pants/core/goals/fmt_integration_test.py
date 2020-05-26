# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re

from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest, ensure_daemon
from pants.util.dirutil import read_file


class FmtIntegrationTest(PantsRunIntegrationTest):
    @ensure_daemon
    def test_fmt_then_edit(self):
        f = "examples/src/python/example/hello/greet/greet.py"
        with self.temporary_workdir() as workdir:
            run = lambda: self.run_pants_with_workdir(
                ["--no-v1", "--v2", "fmt", f], workdir=workdir
            )

            # Run once to start up, and then capture the file content.
            self.assert_success(run())
            good_content = read_file(f)

            # Edit the file.
            with self.with_overwritten_file_content(
                f, lambda c: re.sub(b"def greet", b"def  greet", c)
            ):
                assert good_content != read_file(f)

                # Re-run and confirm that the file was fixed.
                self.assert_success(run())
                assert good_content == read_file(f)
