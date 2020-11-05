# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import Path

from pants.testutil.pants_integration_test import ensure_daemon, run_pants
from pants.util.contextutil import temporary_dir


def test_visualize_to():
    # Tests usage of the `--native-engine-visualize-to=` option, which triggers background
    # visualization of the graph. There are unit tests confirming the content of the rendered
    # results.
    with temporary_dir() as destdir:
        run_pants(
            [
                f"--native-engine-visualize-to={destdir}",
                "--backend-packages=pants.backend.python",
                "list",
                "testprojects/src/python/hello/greet",
            ]
        ).assert_success()
        destdir_files = list(Path(destdir).iterdir())
        assert len(destdir_files) > 0


@ensure_daemon
def test_graceful_termination():
    result = run_pants(
        [
            "--backend-packages=['pants.backend.python', 'internal_plugins.rules_for_testing']",
            "list-and-die-for-testing",
            "testprojects/src/python/hello/greet",
        ]
    )
    result.assert_failure()
    assert result.stdout == "testprojects/src/python/hello/greet\n"
    assert result.exit_code == 42
