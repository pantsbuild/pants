# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from glob import glob
from textwrap import dedent

import pytest

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
        ],
        # match the setup_py_commands --python-tag of src/python/pants/testutil:testutil_wheel
        config={"python-setup": {"interpreter_constraints": ["CPython>=3.7<=3.9"]}},
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


@pytest.mark.parametrize(
    "wheel_glob, import_package, member",
    [
        ("pantsbuild.pants.testutil-*.whl", "pants.testutil.option_util", "create_subsystem"),
        ("pantsbuild.pants-*.whl", "pants.engine.unions", "is_union"),
    ],
)
def test_type_stubs(wheel_glob, import_package, member) -> None:
    wheel = glob(f"{os.getcwd()}/{wheel_glob}")[0]
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
            f"""\
            from {import_package} import {member}
            """
        ),
        "proj1/err.py": dedent(
            f"""\
            from {import_package} import {member}

            def dummy() -> None:
                {member}()
            """
        ),
    }

    with setup_tmpdir(project) as tmpdir:
        ok_result = typecheck_file(f"{tmpdir}/proj1/ok.py")
        err_result = typecheck_file(f"{tmpdir}/proj1/err.py")

    ok_result.assert_success()
    err_result.assert_failure()
