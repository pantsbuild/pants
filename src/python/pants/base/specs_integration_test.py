# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

from pants.testutil.pants_integration_test import PantsResult, run_pants, setup_tmpdir
from pants.testutil.python_interpreter_selection import skip_unless_python39_present

SOURCES = {
    # NB: This uses recursive globs for the `python_sources` and `python_tests` target generators,
    # even though we recommend 1:1:1, because it tests out our handling of where a generated
    # target is "resident" to.
    "py/BUILD": dedent(
        """\
        pex_binary(name="bin", entry_point="app.py")
        python_sources(name="lib", sources=["**/*.py", "!**/*_test.py"])
        python_tests(name="tests", sources=["**/*_test.py"])
        """
    ),
    "py/app.py": dedent(
        """\
        from {tmpdir}.py.base.common import NAME
        from {tmpdir}.py.base.strutil import capitalize

        if __name__ == "__main__":
            print(capitalize(NAME))
        """
    ),
    "py/base/common.py": "NAME = 'pantsbuild'",
    "py/base/common_test.py": dedent(
        """\
        from {tmpdir}.py.base.common import NAME

        def test_name():
            assert NAME == "pantsbuild"
        """
    ),
    "py/utils/strutil.py": dedent(
        """\
        def capitalize(s):
            return s.capitalize()
        """
    ),
    "py/utils/strutil_test.py": dedent(
        """\
        from {tmpdir}.py.utils.strutil import capitalize

        def test_capitalize():
            assert capitalize("hello") == "Hello"
        """
    ),
}


def run(args: list[str]) -> PantsResult:
    result = run_pants(
        [
            "--backend-packages=pants.backend.python",
            "--backend-packages=pants.backend.experimental.go",
            "--python-interpreter-constraints=['==3.9.*']",
            "--pants-ignore=__pycache__",
            *args,
        ]
    )
    result.assert_success()
    return result


@skip_unless_python39_present
def test_address_literal() -> None:
    """Semantics:

    * project introspection: do not replace target generators with generated.
    * "build" goals: replace target generators with generated.
    """
    with setup_tmpdir(SOURCES) as tmpdir:
        list_specs = [f"{tmpdir}/py:bin", f"{tmpdir}/py:tests", f"{tmpdir}/py/app.py:lib"]
        assert run(["list", *list_specs]).stdout.splitlines() == list_specs

        test_result = run(["test", f"{tmpdir}/py:tests"]).stderr
        assert f"{tmpdir}/py/utils/strutil_test.py:../tests - succeeded." in test_result
        assert f"{tmpdir}/py/base/common_test.py:../tests - succeeded." in test_result
        assert f"{tmpdir}/py:tests" not in test_result


@skip_unless_python39_present
def test_sibling_addresses() -> None:
    """Semantics:

    * project introspection: include all targets that are "resident" to the directory, i.e.
        defined there or generated and reside there.
    * "build" goals: match all targets that are resident to the directory, but replace any
        target generators with their generated targets, even if those generated targets are resident to another directory!
    """
    with setup_tmpdir(SOURCES) as tmpdir:
        assert run(["list", f"{tmpdir}/py/utils:"]).stdout.splitlines() == [
            f"{tmpdir}/py/utils/strutil.py:../lib",
            f"{tmpdir}/py/utils/strutil_test.py:../tests",
        ]
        assert run(["list", f"{tmpdir}/py:"]).stdout.splitlines() == [
            f"{tmpdir}/py:bin",
            f"{tmpdir}/py:lib",
            f"{tmpdir}/py:tests",
            f"{tmpdir}/py/app.py:lib",
        ]

        # Even though no `python_test` targets are explicitly defined in `util/`, a generated
        # target is resident there.
        test_result = run(["test", f"{tmpdir}/py/utils:"]).stderr
        assert f"{tmpdir}/py/utils/strutil_test.py:../tests - succeeded." in test_result
        assert f"{tmpdir}/py/base/common_test.py:../tests" not in test_result
        assert f"{tmpdir}/py:tests" not in test_result

        # Even though no `_test.py` files live in this dir, we match the `python_tests` target
        # and replace it with its generated targets.
        test_result = run(["test", f"{tmpdir}/py:"]).stderr
        assert f"{tmpdir}/py/utils/strutil_test.py:../tests - succeeded." in test_result
        assert f"{tmpdir}/py/base/common_test.py:../tests" in test_result
        assert f"{tmpdir}/py:tests" not in test_result


@skip_unless_python39_present
def test_descendent_addresses() -> None:
    """Semantics are the same as sibling addreses, only recursive."""
    with setup_tmpdir(SOURCES) as tmpdir:
        assert run(["list", f"{tmpdir}/py::"]).stdout.splitlines() == [
            f"{tmpdir}/py:bin",
            f"{tmpdir}/py:lib",
            f"{tmpdir}/py:tests",
            f"{tmpdir}/py/app.py:lib",
            f"{tmpdir}/py/base/common.py:../lib",
            f"{tmpdir}/py/base/common_test.py:../tests",
            f"{tmpdir}/py/utils/strutil.py:../lib",
            f"{tmpdir}/py/utils/strutil_test.py:../tests",
        ]

        test_result = run(["test", f"{tmpdir}/py::"]).stderr
        assert f"{tmpdir}/py/utils/strutil_test.py:../tests - succeeded." in test_result
        assert f"{tmpdir}/py/base/common_test.py:../tests" in test_result
        assert f"{tmpdir}/py:tests" not in test_result


@skip_unless_python39_present
def test_file_arg() -> None:
    """Semantics: find the 'owning' target, using generated target rather than target generator
    when possible (regardless of project introspection vs. "build" goal).
    """
    with setup_tmpdir(SOURCES) as tmpdir:
        assert run(
            ["list", f"{tmpdir}/py/app.py", f"{tmpdir}/py/utils/strutil_test.py"]
        ).stdout.splitlines() == [
            f"{tmpdir}/py/app.py:lib",
            f"{tmpdir}/py/utils/strutil_test.py:../tests",
        ]
