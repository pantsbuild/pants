# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
import os
from textwrap import dedent
from typing import Iterable, Tuple

import pytest

from pants.testutil.pants_integration_test import PantsResult, run_pants, setup_tmpdir


def run_pants_run(
    sources: dict[str, str],
    *,
    source_roots: Iterable[str],
    file: str,
    pants_args: Iterable[str] = (),
    extra_args: Iterable[str] = (),
    extra_env: dict[str, str] = {},
) -> Tuple[PantsResult, str]:
    with setup_tmpdir(sources) as tmpdir:
        source_roots_flag_value = ", ".join(
            f"'/{tmpdir}/{source_root}'" for source_root in source_roots
        )
        args = [
            "--backend-packages=pants.backend.python",
            "--backend-packages=pants.backend.codegen.protobuf.python",
            f"--source-root-patterns=[{source_roots_flag_value}]",
            "--pants-ignore=__pycache__",
            "--pants-ignore=/src/python",
            *pants_args,
            "run",
            f"{tmpdir}/{file}",
            *extra_args,
        ]
        result =  run_pants(args, extra_env=extra_env)

        # Now test using the debug adapter
        args.insert(args.index("run")+1, "--debug-adapter")
        debug_adapter_result = run_pants(args, extra_env=extra_env)
        assert result.exit_code == debug_adapter_result.exit_code, result.stderr

        return result, tmpdir



@pytest.mark.parametrize(
    "global_default_value, field_value, run_uses_sandbox",
    [
        # Nothing set -> True
        (None, None, True),
        # Field set -> use field value
        (None, True, True),
        (None, False, False),
        # Global default set -> use default
        (True, None, True),
        (False, None, False),
        # Both set -> use field
        (True, True, True),
        (True, False, False),
        (False, True, True),
        (False, False, False),
    ],
)
def test_run_sample_script(
    global_default_value: bool | None,
    field_value: bool | None,
    run_uses_sandbox: bool,
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
                {("run_goal_use_sandbox=" + str(field_value)) if field_value is not None else ""}
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

    result, test_repo_root = run_pants_run(
        sources,
        source_roots=["src_root1", "src_root2"],
        file="src_root1/project/app.py",
        pants_args=(
            (
                "--python-default-run-goal-use-sandbox"
                if global_default_value
                else "--no-python-default-run-goal-use-sandbox",
            )
            if global_default_value is not None
            else ()
        ),
    )
    assert "Hola, mundo.\n" in result.stderr
    file = result.stdout.strip()
    if run_uses_sandbox:
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
    result, _ = run_pants_run(
        sources,
        source_roots=["src"],
        file="src/app.py",
    )
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
    result, _ = run_pants_run(sources, source_roots=["src"], file="src/app.py")

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
    result, _ = run_pants_run(sources, source_roots=[""], file="foo/main.py")

    assert result.stdout == "LOCAL DIST\n", result.stderr


def test_runs_in_venv() -> None:
    # NB: We aren't just testing an implementation detail, users can and should expect their code to
    # be run just as if they ran their code in a virtualenv (as is common in the Python ecosystem).
    sources = {
        "src/app.py": dedent(
            """\
            import os
            import sys

            if __name__ == "__main__":
                sys.exit(0 if "VIRTUAL_ENV" in os.environ else 1)
            """
        ),
        "src/BUILD": dedent(
            """\
            python_sources(name="lib")
            """
        ),
    }
    result, _ = run_pants_run(sources, source_roots=["src"], file="src/app.py")
    assert result.exit_code == 0
