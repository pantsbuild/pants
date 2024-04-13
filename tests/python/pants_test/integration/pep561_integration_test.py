# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import Path
from textwrap import dedent

from pants.testutil.pants_integration_test import PantsResult, run_pants, setup_tmpdir


def typecheck_file(path: str, filename: str) -> PantsResult:
    return run_pants(
        [
            "--backend-packages=pants.backend.python",
            "--backend-packages=pants.backend.python.typecheck.mypy",
            "--python-interpreter-constraints=['==3.9.*']",
            "check",
            f"{path}/{filename}",
        ],
        config={
            "mypy": {"config": f"{path}/mypy.ini"},
        },
    )


def test_typechecking() -> None:
    # NB: We install pantsbuild.pants.testutil and pantsbuild.pants in the same test because
    # pantsbuild.pants.testutil depends on pantsbuild.pants, and we need to install that dependency
    # from the filesystem, rather than falling back to PyPI.
    pants_wheel = list(Path.cwd().glob("pantsbuild.pants-*.whl"))[0]
    testutil_wheel = list(Path.cwd().glob("pantsbuild.pants.testutil-*.whl"))[0]
    project = {
        "BUILD": dedent(
            f"""\
            python_requirement(
                name="pants",
                requirements=["pantsbuild.pants @ file://{pants_wheel}"],
            )
            python_requirement(
                name="testutil",
                requirements=["pantsbuild.pants.testutil @ file://{testutil_wheel}"],
            )
            python_sources(name="lib", dependencies=[":pants", ":testutil"])
            """
        ),
        "ok.py": dedent(
            """\
            from pants.util.strutil import ensure_text
            from pants.testutil.rule_runner import RuleRunner

            assert ensure_text(b"hello world") == "hello world"
            RuleRunner(rules=[], target_types=[])
            """
        ),
        "err.py": dedent(
            """\
            from pants.util.strutil import ensure_text
            from pants.testutil.rule_runner import RuleRunner

            assert ensure_text(123) == "123"
            RuleRunner(bad_kwargs="foo")
            """
        ),
        "mypy.ini": dedent(
            """\
            [mypy]
            namespace_packages = true
            explicit_package_bases = true
            mypy_path = "src/python:tests/python:testprojects/src/python"
            """
        ),
    }
    with setup_tmpdir(project) as tmpdir:
        typecheck_file(tmpdir, "ok.py").assert_success()
        typecheck_file(tmpdir, "err.py").assert_failure()
