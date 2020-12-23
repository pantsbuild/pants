# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re

from pants.testutil.pants_integration_test import (
    ensure_daemon,
    run_pants_with_workdir,
    temporary_workdir,
)
from pants.util.contextutil import overwrite_file_content
from pants.util.dirutil import read_file


@ensure_daemon
def test_fmt_then_edit(use_pantsd: bool) -> None:
    f = "testprojects/src/python/hello/greet/greet.py"
    with temporary_workdir() as workdir:

        def run() -> None:
            run_pants_with_workdir(
                [
                    "--backend-packages=['pants.backend.python', 'pants.backend.python.lint.black']",
                    "fmt",
                    f,
                ],
                workdir=workdir,
                use_pantsd=use_pantsd,
            ).assert_success()

        # Run once to start up, and then capture the file content.
        run()
        good_content = read_file(f)

        # Edit the file.
        with overwrite_file_content(f, lambda c: re.sub(b"def greet", b"def  greet", c)):
            assert good_content != read_file(f)

            # Re-run and confirm that the file was fixed.
            run()
            assert good_content == read_file(f)
