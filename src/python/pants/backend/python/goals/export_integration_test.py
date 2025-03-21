# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
import platform
import re
import shutil
from collections.abc import Mapping, MutableMapping
from textwrap import dedent

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
    tmpdir: str, py_resolve_format: PythonResolveExportFormat, py_hermetic_scripts: bool = True
) -> Mapping:
    cfg: MutableMapping = {
        "GLOBAL": {
            "backend_packages": ["pants.backend.python"],
        },
        "python": {
            "enable_resolves": True,
            "interpreter_constraints": [f"=={platform.python_version()}"],
            "resolves": {
                "a": f"{tmpdir}/3rdparty/a.lock",
                "b": f"{tmpdir}/3rdparty/b.lock",
            },
        },
        "export": {
            "py_resolve_format": py_resolve_format.value,
            "py_non_hermetic_scripts_in_resolve": [] if py_hermetic_scripts else ["a", "b"],
        },
    }

    return cfg


@pytest.mark.parametrize(
    "py_resolve_format,py_hermetic_scripts",
    [
        (PythonResolveExportFormat.mutable_virtualenv, True),
        (PythonResolveExportFormat.mutable_virtualenv, False),
        (PythonResolveExportFormat.symlinked_immutable_virtualenv, True),
    ],
)
def test_export(py_resolve_format: PythonResolveExportFormat, py_hermetic_scripts: bool) -> None:
    with setup_tmpdir(SOURCES) as tmpdir:
        resolve_names = ["a", "b"]
        run_pants(
            [
                "generate-lockfiles",
                "export",
                *(f"--resolve={name}" for name in resolve_names),
                "--export-py-editable-in-resolve=['a']",
            ],
            config=build_config(tmpdir, py_resolve_format, py_hermetic_scripts),
        ).assert_success()

    export_prefix = os.path.join("dist", "export", "python", "virtualenvs")
    assert os.path.isdir(export_prefix), (
        f"expected export prefix dir '{export_prefix}' does not exist"
    )
    py_minor_version = f"{platform.python_version_tuple()[0]}.{platform.python_version_tuple()[1]}"
    for resolve, ansicolors_version in [("a", "1.1.8"), ("b", "1.0.2")]:
        export_resolve_dir = os.path.join(export_prefix, resolve)
        assert os.path.isdir(export_resolve_dir), (
            f"expected export resolve dir '{export_resolve_dir}' does not exist"
        )

        export_dir = os.path.join(export_resolve_dir, platform.python_version())
        assert os.path.isdir(export_dir), f"expected export dir '{export_dir}' does not exist"
        if py_resolve_format == PythonResolveExportFormat.symlinked_immutable_virtualenv:
            assert os.path.islink(export_dir), (
                f"expected export dir '{export_dir}' is not a symlink"
            )

        lib_dir = os.path.join(export_dir, "lib", f"python{py_minor_version}", "site-packages")
        assert os.path.isdir(lib_dir), f"expected export lib dir '{lib_dir}' does not exist"
        expected_ansicolors_dir = os.path.join(
            lib_dir, f"ansicolors-{ansicolors_version}.dist-info"
        )
        assert os.path.isdir(expected_ansicolors_dir), (
            f"expected dist-info for ansicolors '{expected_ansicolors_dir}' does not exist"
        )

        if py_resolve_format == PythonResolveExportFormat.mutable_virtualenv:
            activate_path = os.path.join(export_dir, "bin", "activate")
            assert os.path.isfile(activate_path), "virtualenv's bin/activate is missing"
            with open(activate_path) as activate_file:
                activate_content = activate_file.read()

            prompt_re = re.compile(rf"""PS1=('|")\({resolve}/{platform.python_version()}\) """)
            assert prompt_re.search(activate_content) is not None, (
                "Expected PS1 prompt not defined in bin/activate."
            )

            script_path = os.path.join(export_dir, "bin", "wheel")
            assert os.path.isfile(script_path), (
                "expected wheel to be installed, but bin/wheel is missing"
            )
            with open(script_path) as script_file:
                shebang = script_file.readline().strip()
            if py_hermetic_scripts:
                assert shebang.endswith(" -sE")
            else:
                assert not shebang.endswith(" -sE")

            expected_foo_dir = os.path.join(lib_dir, "foo_dist-1.2.3.dist-info")
            if resolve == "b":
                assert not os.path.isdir(expected_foo_dir), (
                    f"unexpected dist-info for foo-dist '{expected_foo_dir}' exists"
                )
            elif resolve == "a":
                # make sure the editable wheel for the python_distribution is installed
                assert os.path.isdir(expected_foo_dir), (
                    f"expected dist-info for foo-dist '{expected_foo_dir}' does not exist"
                )
                # direct_url__pants__.json should be moved to direct_url.json
                expected_foo_direct_url_pants = os.path.join(
                    expected_foo_dir, "direct_url__pants__.json"
                )
                assert not os.path.isfile(expected_foo_direct_url_pants), (
                    f"expected direct_url__pants__.json for foo-dist '{expected_foo_direct_url_pants}' was not removed"
                )
                expected_foo_direct_url = os.path.join(expected_foo_dir, "direct_url.json")
                assert os.path.isfile(expected_foo_direct_url), (
                    f"expected direct_url.json for foo-dist '{expected_foo_direct_url}' does not exist"
                )


def test_symlinked_venv_resilience() -> None:
    with temporary_dir() as named_caches:
        pex_root = os.path.join(os.path.realpath(named_caches), "pex_root")
        with setup_tmpdir(SOURCES) as tmpdir:
            run_pants(
                [
                    f"--named-caches-dir={named_caches}",
                    "generate-lockfiles",
                    "export",
                    "--resolve=a",
                ],
                config=build_config(
                    tmpdir, PythonResolveExportFormat.symlinked_immutable_virtualenv
                ),
            ).assert_success()

            def check():
                export_dir = os.path.join(
                    "dist", "export", "python", "virtualenvs", "a", platform.python_version()
                )
                assert os.path.islink(export_dir)
                export_dir_tgt = os.readlink(export_dir)
                assert os.path.isdir(export_dir_tgt)
                assert os.path.commonpath([pex_root, export_dir_tgt]) == pex_root

            check()

            shutil.rmtree(pex_root)

            run_pants(
                [f"--named-caches-dir={named_caches}", "export", "--resolve=a"],
                config=build_config(
                    tmpdir, PythonResolveExportFormat.symlinked_immutable_virtualenv
                ),
            ).assert_success()

            check()
