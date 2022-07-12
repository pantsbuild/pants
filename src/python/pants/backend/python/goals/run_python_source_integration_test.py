# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import os
from textwrap import dedent
from typing import Tuple

import pytest

from pants.testutil.pants_integration_test import PantsResult, run_pants, setup_tmpdir


@pytest.mark.parametrize(
    "run_in_sandbox",
    [True, False],
)
def test_run_sample_script(
    run_in_sandbox: bool,
) -> None:
    """Test that we properly run a `python_source` target.

    This checks a few things:
    - We can handle source roots.
    - We run in-repo when requested, and handle codegen correctly.
    - We propagate the error code.
    """
    sources = {
        "src_root1/project/app.py": dedent(
            """\
            import sys
            from utils.strutil import my_file
            from codegen.hello_pb2 import Hi

            def main():
                print("Hola, mundo.", file=sys.stderr)
                print(my_file())
                sys.exit(23)

            if __name__ == "__main__":
              main()
            """
        ),
        "src_root1/project/BUILD": dedent(
            f"""\
            python_sources(
                name='lib',
                run_goal_use_sandbox={run_in_sandbox},
            )
            """
        ),
        "src_root2/utils/strutil.py": dedent(
            """\
            def my_file():
                return __file__
            """
        ),
        "src_root2/utils/BUILD": "python_sources()",
        "src_root2/codegen/hello.proto": 'syntax = "proto3";\nmessage Hi {{}}',
        "src_root2/codegen/BUILD": dedent(
            """\
            protobuf_sources()
            python_requirement(name='protobuf', requirements=['protobuf'])
            """
        ),
    }

    def run(*extra_args: str, **extra_env: str) -> Tuple[PantsResult, str]:
        with setup_tmpdir(sources) as tmpdir:
            args = [
                "--backend-packages=pants.backend.python",
                "--backend-packages=pants.backend.codegen.protobuf.python",
                f"--source-root-patterns=['/{tmpdir}/src_root1', '/{tmpdir}/src_root2']",
                "--pants-ignore=__pycache__",
                "--pants-ignore=/src/python",
                "run",
                f"{tmpdir}/src_root1/project/app.py",
                *extra_args,
            ]
            return run_pants(args, extra_env=extra_env), tmpdir

    result, test_repo_root = run()
    assert "Hola, mundo.\n" in result.stderr
    file = result.stdout.strip()
    if run_in_sandbox:
        assert file.endswith("src_root2/utils/strutil.py")
        assert "pants-sandbox-" in file
    else:
        assert file.endswith(os.path.join(test_repo_root, "src_root2/utils/strutil.py"))
    assert result.exit_code == 23


def test_no_strip_pex_env_issues_12057() -> None:
    sources = {
        "src/app.py": dedent(
            """\
            import os
            import sys


            if __name__ == "__main__":
                exit_code = os.environ.get("PANTS_ISSUES_12057")
                if exit_code is None:
                    os.environ["PANTS_ISSUES_12057"] = "42"
                    os.execv(sys.executable, [sys.executable, *sys.argv])
                sys.exit(int(exit_code))
            """
        ),
        "src/BUILD": dedent(
            """\
            python_sources(name="lib")
            """
        ),
    }
    with setup_tmpdir(sources) as tmpdir:
        args = [
            "--backend-packages=pants.backend.python",
            f"--source-root-patterns=['/{tmpdir}/src']",
            "run",
            f"{tmpdir}/src/app.py",
        ]
        result = run_pants(args)
        assert result.exit_code == 42, result.stderr


def test_no_leak_pex_root_issues_12055() -> None:
    read_config_result = run_pants(["help-all"])
    read_config_result.assert_success()
    config_data = json.loads(read_config_result.stdout)
    global_advanced_options = {
        option["config_key"]: [
            ranked_value["value"] for ranked_value in option["value_history"]["ranked_values"]
        ][-1]
        for option in config_data["scope_to_help_info"][""]["advanced"]
    }
    named_caches_dir = global_advanced_options["named_caches_dir"]

    sources = {
        "src/app.py": "import os; print(os.environ['PEX_ROOT'])",
        "src/BUILD": dedent(
            """\
            python_sources(name="lib")
            """
        ),
    }
    with setup_tmpdir(sources) as tmpdir:
        args = [
            "--backend-packages=pants.backend.python",
            f"--source-root-patterns=['/{tmpdir}/src']",
            "run",
            f"{tmpdir}/src/app.py",
        ]
        result = run_pants(args)
        result.assert_success()
        assert os.path.join(named_caches_dir, "pex_root") == result.stdout.strip()


def test_local_dist() -> None:
    sources = {
        "foo/bar.py": "BAR = 'LOCAL DIST'",
        "foo/setup.py": dedent(
            """\
            from setuptools import setup

            # Double-brace the package_dir to avoid setup_tmpdir treating it as a format.
            setup(name="foo", version="9.8.7", packages=["foo"], package_dir={{"foo": "."}},)
            """
        ),
        "foo/main.py": "from foo.bar import BAR; print(BAR)",
        "foo/BUILD": dedent(
            """\
            python_sources(name="lib", sources=["bar.py", "setup.py"])

            python_distribution(
                name="dist",
                dependencies=[":lib"],
                provides=python_artifact(name="foo", version="9.8.7"),
                sdist=False,
                generate_setup=False,
            )

            python_sources(name="main_lib",
                sources=["main.py"],
                # Force-exclude any dep on bar.py, so the only way to consume it is via the dist.
                dependencies=[":dist", "!:lib"],
            )
            """
        ),
    }
    with setup_tmpdir(sources) as tmpdir:
        args = [
            "--backend-packages=pants.backend.python",
            f"--source-root-patterns=['/{tmpdir}']",
            "run",
            f"{tmpdir}/foo/main.py",
        ]
        result = run_pants(args)
        assert result.stdout == "LOCAL DIST\n"
