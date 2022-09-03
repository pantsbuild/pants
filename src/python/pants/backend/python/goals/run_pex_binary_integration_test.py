# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import json
from textwrap import dedent
from typing import Callable, Optional

import pytest

from pants.backend.python.target_types import PexExecutionMode, PexLayout
from pants.testutil.pants_integration_test import PantsResult, run_pants, setup_tmpdir

use_deprecated_semantics_args = pytest.mark.parametrize(
    "use_deprecated_semantics_args",
    [],
)


def run_generic_test(
    *,
    use_deprecated_semantics_args: tuple[str, ...],
    entry_point: str = "app.py",
    execution_mode: Optional[PexExecutionMode] = None,
    include_tools: bool = False,
    layout: Optional[PexLayout] = None,
) -> Callable[..., PantsResult]:
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
            python_sources(name='lib')
            pex_binary(
              name="binary",
              entry_point={entry_point!r},
              execution_mode={execution_mode.value if execution_mode is not None else None!r},
              include_tools={include_tools!r},
              layout={layout.value if layout is not None else None!r},
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

    def run(*extra_args: str, **extra_env: str) -> PantsResult:
        with setup_tmpdir(sources) as tmpdir:
            args = [
                "--backend-packages=pants.backend.python",
                "--backend-packages=pants.backend.codegen.protobuf.python",
                *use_deprecated_semantics_args,
                f"--source-root-patterns=['/{tmpdir}/src_root1', '/{tmpdir}/src_root2']",
                "--pants-ignore=__pycache__",
                "--pants-ignore=/src/python",
                "run",
                f"{tmpdir}/src_root1/project:binary",
                *extra_args,
            ]
            return run_pants(args, extra_env=extra_env)

    result = run()

    assert "Hola, mundo.\n" in result.stderr
    file = result.stdout.strip()
    if use_deprecated_semantics_args:
        assert file.endswith("src_root2/utils/strutil.py")
        assert "pants-sandbox-" in file
    else:
        assert "src_root2" not in file
        assert file.endswith("utils/strutil.py")
        if layout == PexLayout.LOOSE:
            # Loose PEXs execute their own code directly
            assert "pants-sandbox-" in file
        else:
            assert "pants-sandbox-" not in file
    assert result.exit_code == 23

    return run


@pytest.mark.parametrize("entry_point", ["app.py", "app.py:main"])
@use_deprecated_semantics_args
def test_entry_point(
    entry_point: str,
    use_deprecated_semantics_args: tuple[str, ...],
):
    run_generic_test(
        use_deprecated_semantics_args=use_deprecated_semantics_args, entry_point=entry_point
    )


@pytest.mark.parametrize("execution_mode", [None, PexExecutionMode.VENV])
@pytest.mark.parametrize("include_tools", [True, False])
@use_deprecated_semantics_args
def test_execution_mode_and_include_tools(
    execution_mode: Optional[PexExecutionMode],
    include_tools: bool,
    use_deprecated_semantics_args: tuple[str, ...],
):
    run = run_generic_test(
        use_deprecated_semantics_args=use_deprecated_semantics_args,
        execution_mode=execution_mode,
        include_tools=include_tools,
    )

    if include_tools:
        result = run("--", "info", PEX_TOOLS="1")
        assert result.exit_code == 0, result.stderr
        pex_info = json.loads(result.stdout)
        assert (execution_mode is PexExecutionMode.VENV) == pex_info["venv"]
        assert ("prepend" if execution_mode is PexExecutionMode.VENV else "false") == pex_info[
            "venv_bin_path"
        ]
        if use_deprecated_semantics_args:
            assert not pex_info["strip_pex_env"]
        else:
            assert pex_info["strip_pex_env"]


@pytest.mark.parametrize("layout", PexLayout)
@use_deprecated_semantics_args
def test_layout(
    layout: Optional[PexLayout],
    use_deprecated_semantics_args: tuple[str, ...],
):
    run_generic_test(use_deprecated_semantics_args=use_deprecated_semantics_args, layout=layout)


@use_deprecated_semantics_args
def test_no_strip_pex_env_issues_12057(use_deprecated_semantics_args: tuple[str, ...]) -> None:
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
            pex_binary(
                name="binary",
                entry_point="app.py"
            )
            """
        ),
    }
    with setup_tmpdir(sources) as tmpdir:
        args = [
            "--backend-packages=pants.backend.python",
            *use_deprecated_semantics_args,
            f"--source-root-patterns=['/{tmpdir}/src']",
            "run",
            f"{tmpdir}/src:binary",
        ]
        result = run_pants(args)
        assert result.exit_code == 42, result.stderr


@use_deprecated_semantics_args
def test_local_dist(use_deprecated_semantics_args: tuple[str, ...]) -> None:
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

            python_sources(name="main_lib", sources=["main.py"])

            python_distribution(
                name="dist",
                dependencies=[":lib"],
                provides=python_artifact(name="foo", version="9.8.7"),
                sdist=False,
                generate_setup=False,
            )

            pex_binary(
                name="bin",
                entry_point="main.py",
                # Force-exclude any dep on bar.py, so the only way to consume it is via the dist.
                dependencies=[":main_lib", ":dist", "!!:lib"])
            """
        ),
    }
    with setup_tmpdir(sources) as tmpdir:
        args = [
            "--backend-packages=pants.backend.python",
            *use_deprecated_semantics_args,
            f"--source-root-patterns=['/{tmpdir}']",
            "run",
            f"{tmpdir}/foo:bin",
        ]
        result = run_pants(args)
        assert result.stdout == "LOCAL DIST\n"


@use_deprecated_semantics_args
def test_run_script_from_3rdparty_dist_issue_13747(use_deprecated_semantics_args) -> None:
    sources = {
        "src/BUILD": dedent(
            """\
            python_requirement(name="cowsay", requirements=["cowsay==4.0"])
            pex_binary(name="test", script="cowsay", dependencies=[":cowsay"])
            """
        ),
    }
    with setup_tmpdir(sources) as tmpdir:
        SAY = "moooo"
        args = [
            "--backend-packages=pants.backend.python",
            *use_deprecated_semantics_args,
            f"--source-root-patterns=['/{tmpdir}/src']",
            "run",
            f"{tmpdir}/src:test",
            "--",
            SAY,
        ]
        result = run_pants(args)
        result.assert_success()
        assert SAY in result.stdout.strip()


# NB: Can be removed in 2.15
@use_deprecated_semantics_args
def test_filename_spec_ambiutity(use_deprecated_semantics_args) -> None:
    sources = {
        "src/app.py": dedent(
            """\
            if __name__ == "__main__":
                print(__file__)
            """
        ),
        "src/BUILD": dedent(
            """\
            python_sources(name="lib")
            pex_binary(
                name="binary",
                entry_point="app.py"
            )
            """
        ),
    }
    with setup_tmpdir(sources) as tmpdir:
        args = [
            "--backend-packages=pants.backend.python",
            *use_deprecated_semantics_args,
            f"--source-root-patterns=['/{tmpdir}/src']",
            "run",
            f"{tmpdir}/src/app.py",
        ]
        result = run_pants(args)
        file = result.stdout.strip()
        assert file.endswith("src/app.py")
        assert "pants-sandbox-" in file
