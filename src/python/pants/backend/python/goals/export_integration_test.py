# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
import platform
import shutil
from dataclasses import dataclass
from textwrap import dedent
from typing import List, Mapping, MutableMapping

import pytest

from pants.backend.python.goals.export import PythonResolveExportFormat
from pants.testutil.pants_integration_test import run_pants, setup_tmpdir
from pants.util.contextutil import temporary_dir

SOURCES = {
    "3rdparty/BUILD": dedent(
        """\
        python_requirement(name='req1', requirements=['ansicolors==1.1.8'], resolve='a', modules=['colors'])
        python_requirement(name='req2', requirements=['ansicolors==1.0.2'], resolve='b', modules=['colors'])
        """
    ),
    "src/python/foo.py": "from colors import *",
    "src/python/BUILD": dedent(
        """\
        python_source(name='foo', source='foo.py', resolve=parametrize('a', 'b'))
        python_distribution(
            name='dist',
            provides=python_artifact(name='foo', version='1.2.3'),
            dependencies=[':foo@resolve=a'],
        )
        """
    ),
}


@dataclass
class _ToolConfig:
    name: str
    version: str
    experimental: bool = False
    backend_prefix: str | None = "lint"
    takes_ics: bool = True

    @property
    def package(self) -> str:
        return self.name.replace("-", "_")


EXPORTED_TOOLS: List[_ToolConfig] = [
    _ToolConfig(name="add-trailing-comma", version="2.2.3", experimental=True),
    _ToolConfig(name="bandit", version="1.6.2", takes_ics=False),
    _ToolConfig(name="black", version="22.3.0"),
    _ToolConfig(name="mypy", version="0.940", backend_prefix="typecheck"),
    _ToolConfig(name="pytest", version="7.1.0", backend_prefix=None, takes_ics=False),
]


def build_config(tmpdir: str, py_resolve_format: PythonResolveExportFormat) -> Mapping:
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
        "export": {"py_resolve_format": py_resolve_format.value},
    }
    for tool_config in EXPORTED_TOOLS:
        cfg[tool_config.name] = {
            "version": f"{tool_config.name}=={tool_config.version}",
            "lockfile": f"{tmpdir}/3rdparty/{tool_config.name}.lock",
        }
        if tool_config.takes_ics:
            cfg[tool_config.name]["interpreter_constraints"] = (f"=={platform.python_version()}",)

        if not tool_config.backend_prefix:
            continue

        plugin_suffix = f"python.{tool_config.backend_prefix}.{tool_config.package}"

        if tool_config.experimental:
            plugin_suffix = f"experimental.{plugin_suffix}"

        cfg["GLOBAL"]["backend_packages"].append(f"pants.backend.{plugin_suffix}")

    return cfg


@pytest.mark.parametrize(
    "py_resolve_format",
    [
        PythonResolveExportFormat.mutable_virtualenv,
        PythonResolveExportFormat.symlinked_immutable_virtualenv,
    ],
)
def test_export(py_resolve_format: PythonResolveExportFormat) -> None:
    with setup_tmpdir(SOURCES) as tmpdir:
        resolve_names = ["a", "b", *(tool.name for tool in EXPORTED_TOOLS)]
        run_pants(
            ["generate-lockfiles", "export", *(f"--resolve={name}" for name in resolve_names)],
            config=build_config(tmpdir, py_resolve_format),
        ).assert_success()

    export_prefix = os.path.join("dist", "export", "python", "virtualenvs")
    assert os.path.isdir(
        export_prefix
    ), f"expected export prefix dir '{export_prefix}' does not exist"
    py_minor_version = f"{platform.python_version_tuple()[0]}.{platform.python_version_tuple()[1]}"
    for resolve, ansicolors_version in [("a", "1.1.8"), ("b", "1.0.2")]:
        export_resolve_dir = os.path.join(export_prefix, resolve)
        assert os.path.isdir(
            export_resolve_dir
        ), f"expected export resolve dir '{export_resolve_dir}' does not exist"

        export_dir = os.path.join(export_resolve_dir, platform.python_version())
        assert os.path.isdir(export_dir), f"expected export dir '{export_dir}' does not exist"
        if py_resolve_format == PythonResolveExportFormat.symlinked_immutable_virtualenv:
            assert os.path.islink(
                export_dir
            ), f"expected export dir '{export_dir}' is not a symlink"

        lib_dir = os.path.join(export_dir, "lib", f"python{py_minor_version}", "site-packages")
        assert os.path.isdir(lib_dir), f"expected export lib dir '{lib_dir}' does not exist"
        expected_ansicolors_dir = os.path.join(
            lib_dir, f"ansicolors-{ansicolors_version}.dist-info"
        )
        assert os.path.isdir(
            expected_ansicolors_dir
        ), f"expected dist-info for ansicolors '{expected_ansicolors_dir}' does not exist"

        if resolve == "a" and py_resolve_format == PythonResolveExportFormat.mutable_virtualenv:
            # make sure the editable wheel for the python_distribution is installed
            expected_foo_dir = os.path.join(lib_dir, "foo-1.2.3.dist-info")
            assert os.path.isdir(
                expected_foo_dir
            ), f"expected dist-info for foo '{expected_foo_dir}' does not exist"
            # direct_url__pants__.json should be moved to direct_url.json
            expected_foo_direct_url_pants = os.path.join(
                expected_foo_dir, "direct_url__pants__.json"
            )
            assert not os.path.isfile(
                expected_foo_direct_url_pants
            ), f"expected direct_url__pants__.json for foo '{expected_foo_direct_url_pants}' was not removed"
            expected_foo_direct_url = os.path.join(expected_foo_dir, "direct_url.json")
            assert os.path.isfile(
                expected_foo_direct_url
            ), f"expected direct_url.json for foo '{expected_foo_direct_url}' does not exist"

    for tool_config in EXPORTED_TOOLS:
        export_dir = os.path.join(export_prefix, tool_config.name, platform.python_version())
        assert os.path.isdir(export_dir), f"expected export dir '{export_dir}' does not exist"

        # NOTE: Not every tool implements --version so this is the best we can do.
        lib_dir = os.path.join(export_dir, "lib", f"python{py_minor_version}", "site-packages")

        expected_tool_dir = os.path.join(
            lib_dir, f"{tool_config.package}-{tool_config.version}.dist-info"
        )
        assert os.path.isdir(
            expected_tool_dir
        ), f"expected dist-info for {tool_config.name} '{expected_tool_dir}' does not exist"


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
