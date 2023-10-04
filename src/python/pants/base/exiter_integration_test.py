# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pants.testutil.pants_integration_test import ensure_daemon, run_pants, setup_tmpdir

dir_layout = {
    # This file is expected to fail to "compile" when run via `./pants run` due to a SyntaxError.
    # Because the error itself contains unicode, it can exercise that error handling codepaths
    # are unicode aware.
    os.path.join(
        "exiter_integration_test_harness", "main.py"
    ): "if __name__ == '__main__':\n    import sys¡",
    os.path.join(
        "exiter_integration_test_harness", "BUILD"
    ): "python_sources()\npex_binary(name='bin', entry_point='main.py')",
}


@ensure_daemon
def test_unicode_containing_exception(use_pantsd: bool) -> None:
    with setup_tmpdir(dir_layout) as tmpdir:
        pants_run = run_pants(
            [
                "--backend-packages=pants.backend.python",
                "run",
                os.path.join(tmpdir, "exiter_integration_test_harness:bin"),
            ],
            use_pantsd=use_pantsd,
        )
    pants_run.assert_failure()
    assert "import sys¡" in pants_run.stderr
