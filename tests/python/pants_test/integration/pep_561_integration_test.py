# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from glob import glob
from textwrap import dedent

from pants.base.build_environment import get_buildroot
from pants.testutil.pants_integration_test import PantsResult, run_pants, setup_tmpdir


def typecheck_file(filename: str) -> PantsResult:
    return run_pants(
        [
            "--backend-packages=["
            "'pants.backend.python',"
            "'pants.backend.python.typecheck.mypy'"
            "]",
            "typecheck",
            filename,
        ]
    )


def test_typecheck_works() -> None:
    project = {
        "proj1/BUILD": "python_library()",
        "proj1/ok.py": dedent(
            """\
            def dummy() -> int:
                return 42
            """
        ),
        "proj1/err.py": dedent(
            """\
            def dummy() -> int:
                return "not an int"
            """
        ),
    }

    with setup_tmpdir(project) as tmpdir:
        ok_result = typecheck_file(f"{tmpdir}/proj1/ok.py")
        err_result = typecheck_file(f"{tmpdir}/proj1/err.py")

    ok_result.assert_success()
    err_result.assert_failure()


def test_type_stubs() -> None:
    wheel = glob(f"{get_buildroot()}/pantsbuild.pants.testutil-*.whl")[0]
    project = {
        "proj1/BUILD": dedent(
            f"""\
            python_requirement_library(
                name="pants",
                requirements=["Pants @ file://{wheel}"],
            )
            python_library()
            """
        ),
        "proj1/ok.py": dedent(
            """\
            from pants.testutil.option_util import create_subsystem
            """
        ),
        "proj1/err.py": dedent(
            """\
            from pants.testutil.option_util import create_subsystem

            def dummy() -> None:
                create_subsystem()
            """
        ),
    }

    with setup_tmpdir(project) as tmpdir:
        ok_result = typecheck_file(f"{tmpdir}/proj1/ok.py")
        err_result = typecheck_file(f"{tmpdir}/proj1/err.py")

    ok_result.assert_success()
    err_result.assert_failure()
