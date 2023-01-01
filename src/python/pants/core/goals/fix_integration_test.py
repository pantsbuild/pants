# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re

from pants.testutil.pants_integration_test import ensure_daemon, run_pants
from pants.util.contextutil import overwrite_file_content
from pants.util.dirutil import read_file


@ensure_daemon
def test_fix_then_edit(use_pantsd: bool) -> None:
    f = "testprojects/src/python/hello/greet/greet.py"

    def run() -> None:
        run_pants(
            [
                "--backend-packages=['pants.backend.python', 'pants.backend.python.lint.autoflake']",
                "fix",
                f,
            ],
            use_pantsd=use_pantsd,
        ).assert_success()

    # Run once to start up, and then capture the file content.
    run()
    good_content = read_file(f)

    # Edit the file.
    with overwrite_file_content(
        f, lambda c: re.sub(b"import pkgutil", b"import pkgutil\nimport os", c)
    ):
        assert good_content != read_file(f)

        # Re-run and confirm that the file was fixed.
        run()
        assert good_content == read_file(f)


@ensure_daemon
def test_formatter(use_pantsd: bool) -> None:
    f = "testprojects/src/python/hello/greet/greet.py"

    def run() -> None:
        run_pants(
            [
                "--backend-packages=['pants.backend.python', 'pants.backend.python.lint.black']",
                "fix",
                f,
            ],
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


def test_formatter_and_fixer() -> None:
    f = "testprojects/src/python/hello/greet/greet.py"
    stderr = run_pants(
        [
            "--backend-packages=['pants.backend.python', 'pants.backend.python.lint.black', 'pants.backend.python.lint.autoflake']",
            "fix",
            f,
        ],
    ).stderr
    assert stderr.index("Fix with Autoflake") < stderr.index("Format with Black")
