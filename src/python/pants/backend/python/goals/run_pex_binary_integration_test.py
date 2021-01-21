# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import json
from textwrap import dedent

import pytest

from pants.testutil.pants_integration_test import PantsResult, run_pants, setup_tmpdir


@pytest.mark.parametrize(
    ("entry_point", "unzip", "include_tools"),
    [
        ("app.py", True, True),
        ("app.py:main", False, False),
    ],
)
def test_run_sample_script(entry_point: str, unzip: bool, include_tools: bool) -> None:
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
        "src_root1/project/BUILD": dedent(
            f"""\
            python_library(name='lib')
            pex_binary(
              entry_point={entry_point!r},
              unzip={unzip!r},
              include_tools={include_tools!r},
            )
            """
        ),
        "src_root2/utils/strutil.py": dedent(
            """\
            def upper_case(s):
                return s.upper()
            """
        ),
        "src_root2/utils/BUILD": "python_library()",
    }

    def run(*extra_args: str, **extra_env: str) -> PantsResult:
        with setup_tmpdir(sources) as tmpdir:
            args = [
                "--backend-packages=pants.backend.python",
                f"--source-root-patterns=['/{tmpdir}/src_root1', '/{tmpdir}/src_root2']",
                "--pants-ignore=__pycache__",
                "--pants-ignore=/src/python",
                "run",
                f"{tmpdir}/src_root1/project/app.py",
                *extra_args,
            ]
            return run_pants(args, extra_env=extra_env)

    result = run()
    assert "Hola, mundo.\n" in result.stderr
    assert result.stdout == "HELLO WORLD.\n"
    assert result.exit_code == 23

    if include_tools:
        result = run("--", "info", PEX_TOOLS="1")
        assert result.exit_code == 0
        pex_info = json.loads(result.stdout)
        assert unzip == pex_info["unzip"]
