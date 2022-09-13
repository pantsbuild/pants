# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
import platform
from dataclasses import dataclass
from textwrap import dedent
from typing import List, Mapping, MutableMapping

from pants.testutil.pants_integration_test import run_pants, setup_tmpdir

SOURCES = {
    "3rdparty/BUILD": dedent(
        """\
        python_requirement(name='req1', requirements=['ansicolors==1.1.8'], resolve='a', modules=['colors'])
        python_requirement(name='req2', requirements=['ansicolors==1.0.2'], resolve='b', modules=['colors'])
        """
    ),
    "src/python/foo.py": "from colors import *",
    "src/python/BUILD": "python_source(name='foo', source='foo.py', resolve=parametrize('a', 'b'))",
}


@dataclass
class _ToolConfig:
    name: str
    version: str
    experimental: bool = False
    backend_prefix: str | None = "lint"

    @property
    def package(self) -> str:
        return self.name.replace("-", "_")


EXPORTED_TOOLS: List[_ToolConfig] = [
    _ToolConfig(name="add-trailing-comma", version="2.2.3", experimental=True),
    _ToolConfig(name="autoflake", version="1.3.1", experimental=True),
    _ToolConfig(name="bandit", version="1.6.2"),
    _ToolConfig(name="black", version="22.3.0"),
    _ToolConfig(name="docformatter", version="1.3.1"),
    _ToolConfig(name="flake8", version="4.0.1"),
    _ToolConfig(name="isort", version="5.10.1"),
    _ToolConfig(name="pylint", version="2.13.1"),
    _ToolConfig(name="pyupgrade", version="2.31.1", experimental=True),
    _ToolConfig(name="yapf", version="0.32.0"),
    _ToolConfig(name="mypy", version="0.940", backend_prefix="typecheck"),
    _ToolConfig(name="pytest", version="7.1.0", backend_prefix=None),
]


def build_config(tmpdir: str) -> Mapping:
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
    }
    for tool_config in EXPORTED_TOOLS:
        cfg[tool_config.name] = {
            "version": f"{tool_config.name}=={tool_config.version}",
            "lockfile": f"{tmpdir}/3rdparty/{tool_config.name}.lock",
        }

        if not tool_config.backend_prefix:
            continue

        plugin_suffix = f"python.{tool_config.backend_prefix}.{tool_config.package}"

        if tool_config.experimental:
            plugin_suffix = f"experimental.{plugin_suffix}"

        cfg["GLOBAL"]["backend_packages"].append(f"pants.backend.{plugin_suffix}")

    return cfg


def test_export() -> None:
    with setup_tmpdir(SOURCES) as tmpdir:
        run_pants(
            ["generate-lockfiles", "export", f"{tmpdir}/::"], config=build_config(tmpdir)
        ).assert_success()

    export_prefix = os.path.join("dist", "export", "python", "virtualenvs")
    py_minor_version = f"{platform.python_version_tuple()[0]}.{platform.python_version_tuple()[1]}"
    for resolve, ansicolors_version in [("a", "1.1.8"), ("b", "1.0.2")]:
        export_dir = os.path.join(export_prefix, resolve, platform.python_version())
        assert os.path.isdir(export_dir), f"expected export dir '{export_dir}' does not exist"

        lib_dir = os.path.join(export_dir, "lib", f"python{py_minor_version}", "site-packages")
        expected_ansicolors_dir = os.path.join(
            lib_dir, f"ansicolors-{ansicolors_version}.dist-info"
        )
        assert os.path.isdir(
            expected_ansicolors_dir
        ), f"expected dist-info for ansicolors '{expected_ansicolors_dir}' does not exist"

    for tool_config in EXPORTED_TOOLS:
        export_dir = os.path.join(export_prefix, "tools", tool_config.name)
        assert os.path.isdir(export_dir), f"expected export dir '{export_dir}' does not exist"

        # NOTE: Not every tool implements --version so this is the best we can do.
        lib_dir = os.path.join(export_dir, "lib", f"python{py_minor_version}", "site-packages")
        expected_tool_dir = os.path.join(
            lib_dir, f"{tool_config.package}-{tool_config.version}.dist-info"
        )
        assert os.path.isdir(
            expected_tool_dir
        ), f"expected dist-info for {tool_config.name} '{expected_tool_dir}' does not exist"
