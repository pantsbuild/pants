# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

import pytest

from pants.testutil.pants_integration_test import run_pants, setup_tmpdir


@pytest.mark.parametrize(
    "tgt_content",
    [
        "pex_binary(sources=['app.py'])",
        "pex_binary(sources=['app.py'], entry_point='project.app')",
        "pex_binary(sources=['app.py'], entry_point='project.app:main')",
    ],
)
def test_run_sample_script(tgt_content: str) -> None:
    """Test that we properly run a `pex_binary` target.

    This checks a few things:
    - We can handle source roots.
    - We properly load third party requirements.
    - We propagate the error code.
    """
    sources = {
        "src_root1/project/app.py": dedent(
            """\
            import sys
            from utils.strutil import upper_case


            def main():
                print(upper_case("Hello world."))
                print("Hola, mundo.", file=sys.stderr)
                sys.exit(23)

            if __name__ == "__main__":
              main()
            """
        ),
        "src_root1/project/BUILD": tgt_content,
        "src_root2/utils/strutil.py": dedent(
            """\
            def upper_case(s):
                return s.upper()
            """
        ),
        "src_root2/utils/BUILD": "python_library()",
    }
    with setup_tmpdir(sources) as tmpdir:
        result = run_pants(
            [
                "--backend-packages=pants.backend.python",
                f"--source-root-patterns=['/{tmpdir}/src_root1', '/{tmpdir}/src_root2']",
                "--pants-ignore=__pycache__",
                "--pants-ignore=/src/python",
                "run",
                f"{tmpdir}/src_root1/project/app.py",
            ]
        )

    assert "Hola, mundo.\n" in result.stderr
    assert result.stdout == "HELLO WORLD.\n"
    assert result.exit_code == 23


def test_warns_if_entry_point_not_set(caplog) -> None:
    with setup_tmpdir({"BUILD": "pex_binary()"}) as tmpdir:
        result = run_pants(
            [
                "--backend-packages=pants.backend.python",
                "run",
                tmpdir,
                # We use a passthrough arg to make sure we don't open a venv, which would never
                # terminate and cause a timeout.
                "--",
                "invalid_passthrough_arg",
            ]
        )
    result.assert_failure()
    assert len(caplog.records) == 1
    assert f"No entry point set for the `pex_binary` target {tmpdir}" in caplog.text
