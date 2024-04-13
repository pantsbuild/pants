# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.testutil.pants_integration_test import run_pants


def test_generate_lockfile_without_python_backend() -> None:
    """Regression test for https://github.com/pantsbuild/pants/issues/14876."""
    run_pants(
        [
            "--backend-packages=pants.backend.experimental.cc.lint.clangformat",
            "--python-resolves={'clang-format':'cf.lock'}",
            "generate-lockfiles",
            "--resolve=clang-format",
        ]
    ).assert_success()
