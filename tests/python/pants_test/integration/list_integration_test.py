# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re

from pants.testutil.pants_integration_test import run_pants


def test_list_all() -> None:
    pants_run = run_pants(["--backend-packages=pants.backend.python", "list", "::"])
    pants_run.assert_success()
    assert len(pants_run.stdout.strip().split()) > 1


def test_list_none() -> None:
    pants_run = run_pants(["list"])
    pants_run.assert_success()
    assert re.search("WARN.* No targets were matched in", pants_run.stderr)


def test_list_invalid_dir() -> None:
    pants_run = run_pants(["list", "abcde::"])
    pants_run.assert_failure()
    assert "ResolveError" in pants_run.stderr


def test_list_testproject() -> None:
    pants_run = run_pants(
        [
            "--backend-packages=pants.backend.python",
            "list",
            "testprojects/src/python/hello::",
        ]
    )
    pants_run.assert_success()
    assert pants_run.stdout.strip() == "\n".join(
        [
            "testprojects/src/python/hello",
            "testprojects/src/python/hello/__init__.py",
            "testprojects/src/python/hello/greet",
            "testprojects/src/python/hello/greet/__init__.py",
            "testprojects/src/python/hello/greet/greet.py",
            "testprojects/src/python/hello/main",
            "testprojects/src/python/hello/main:lib",
            "testprojects/src/python/hello/main/__init__.py:lib",
            "testprojects/src/python/hello/main/main.py:lib",
        ]
    )
