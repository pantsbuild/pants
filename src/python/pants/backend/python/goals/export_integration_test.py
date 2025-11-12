# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import platform
import shutil
from collections.abc import Mapping
from pathlib import Path
from textwrap import dedent
from typing import Any

import pytest

from pants.backend.python.goals.export import PythonResolveExportFormat
from pants.testutil.pants_integration_test import run_pants, setup_tmpdir
from pants.util.contextutil import temporary_dir

SOURCES = {
    "3rdparty/BUILD": dedent(
        """\
        python_requirement(name='req1', requirements=['ansicolors==1.1.8'], resolve='a', modules=['colors'])
        python_requirement(name='req2', requirements=['ansicolors==1.0.2'], resolve='b', modules=['colors'])
        python_requirement(name='req3', requirements=['wheel'], resolve=parametrize('a', 'b'))
        """
    ),
    "src/python/foo.py": "from colors import *",
    "src/python/BUILD": dedent(
        """\
        python_source(name='foo', source='foo.py', resolve=parametrize('a', 'b'))
        python_distribution(
            name='dist',
            provides=python_artifact(name='foo-dist', version='1.2.3'),
            dependencies=[':foo@resolve=a'],
        )
        """
    ),
}


def build_config(
    py_resolve_format: PythonResolveExportFormat, py_hermetic_scripts: bool = True
) -> Mapping[str, Any]:
    return {
        "GLOBAL": {
            "backend_packages": ["pants.backend.python"],
        },
        "python": {
            "enable_resolves": True,
            "interpreter_constraints": [f"=={platform.python_version()}"],
            "resolves": {
                "a": "3rdparty/a.lock",
                "b": "3rdparty/b.lock",
            },
        },
        "export": {
            "py_resolve_format": py_resolve_format.value,
            "py_non_hermetic_scripts_in_resolve": [] if py_hermetic_scripts else ["a", "b"],
        },
    }


@pytest.mark.parametrize(
    "py_resolve_format,py_hermetic_scripts",
    [
        (PythonResolveExportFormat.mutable_virtualenv, True),
        (PythonResolveExportFormat.mutable_virtualenv, False),
        (PythonResolveExportFormat.symlinked_immutable_virtualenv, True),
    ],
)
def test_export(py_resolve_format: PythonResolveExportFormat, py_hermetic_scripts: bool) -> None:
    with setup_tmpdir(SOURCES):
        resolve_names = ["a", "b"]
        run_pants(
            [
                "--print-stacktrace",
                "generate-lockfiles",
                "export",
                *(f"--resolve={name}" for name in resolve_names),
                "--export-py-editable-in-resolve=['a']",
            ],
            config=build_config(py_resolve_format, py_hermetic_scripts),
        ).assert_success()

    export_prefix = Path("dist") / "export" / "python" / "virtualenvs"
    assert export_prefix.is_dir(), f"export prefix dir '{export_prefix}' does not exist"

    py_minor_version = f"{platform.python_version_tuple()[0]}.{platform.python_version_tuple()[1]}"
    for resolve, ansicolors_version in [("a", "1.1.8"), ("b", "1.0.2")]:
        export_resolve_dir = export_prefix / resolve
        assert export_resolve_dir.is_dir(), (
            f"expected export resolve dir '{export_resolve_dir}' does not exist"
        )

        export_dir = export_resolve_dir / platform.python_version()
        assert export_dir.is_dir(), f"expected export dir '{export_dir}' does not exist"
        if py_resolve_format == PythonResolveExportFormat.symlinked_immutable_virtualenv:
            assert export_dir.is_symlink(), f"expected export dir '{export_dir}' is not a symlink"

        lib_dir = export_dir / "lib" / f"python{py_minor_version}" / "site-packages"
        assert lib_dir.is_dir(), f"expected export lib dir '{lib_dir}' does not exist"
        expected_ansicolors_dir = lib_dir / f"ansicolors-{ansicolors_version}.dist-info"
        assert expected_ansicolors_dir.is_dir(), (
            f"expected dist-info for ansicolors '{expected_ansicolors_dir}' does not exist"
        )

        if py_resolve_format == PythonResolveExportFormat.mutable_virtualenv:
            activate_path = export_dir / "bin" / "activate"
            activate_contents = activate_path.read_text()
            expected_version = f"{resolve}/{platform.python_version()}"
            assert any(
                line.strip().startswith("PS1=") and expected_version in line
                for line in activate_contents.splitlines()
            ), "Expected PS1 prompt not defined in bin/activate."

            script_path = export_dir / "bin" / "wheel"
            with script_path.open() as script_file:
                shebang = script_file.readline().strip()
                if py_hermetic_scripts:
                    assert shebang.endswith(" -sE")
                else:
                    assert not shebang.endswith(" -sE")

            expected_foo_dir = lib_dir / "foo_dist-1.2.3.dist-info"
            if resolve == "b":
                assert not expected_foo_dir.is_dir(), (
                    f"unexpected dist-info for foo-dist '{expected_foo_dir}' exists"
                )
            elif resolve == "a":
                # make sure the editable wheel for the python_distribution is installed
                assert expected_foo_dir.is_dir(), (
                    f"expected dist-info for foo-dist '{expected_foo_dir}' does not exist"
                )

                # direct_url__pants__.json should be moved to direct_url.json
                expected_foo_direct_url_pants = expected_foo_dir / "direct_url__pants__.json"
                assert not expected_foo_direct_url_pants.is_file(), (
                    f"expected direct_url__pants__.json for foo-dist '{expected_foo_direct_url_pants}' was not removed"
                )

                expected_foo_direct_url = expected_foo_dir / "direct_url.json"
                assert expected_foo_direct_url.is_file(), (
                    f"expected direct_url.json for foo-dist '{expected_foo_direct_url}' does not exist"
                )


def test_symlinked_venv_resilience() -> None:
    with temporary_dir() as named_caches:
        pex_root = Path(named_caches).resolve() / "pex_root"
        with setup_tmpdir(SOURCES):
            run_pants(
                [
                    f"--named-caches-dir={named_caches}",
                    "generate-lockfiles",
                    "export",
                    "--resolve=a",
                ],
                config=build_config(PythonResolveExportFormat.symlinked_immutable_virtualenv),
            ).assert_success()

            def check():
                py = platform.python_version()
                export_dir = Path("dist") / "export" / "python" / "virtualenvs" / "a" / py
                assert export_dir.is_symlink()
                export_dir_tgt = export_dir.readlink()
                assert export_dir_tgt.is_dir()
                assert export_dir_tgt.is_relative_to(pex_root)

            check()

            shutil.rmtree(pex_root)

            run_pants(
                [f"--named-caches-dir={named_caches}", "export", "--resolve=a"],
                config=build_config(PythonResolveExportFormat.symlinked_immutable_virtualenv),
            ).assert_success()

            check()
