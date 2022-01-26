# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Ensure that we generate interpreter constraints using the correct values.

This is necessary because the tool lockfiles we generate are used as the default for all Pants
users. We need to decouple our own internal usage (e.g. using Flake8 plugins) from what the default
should be.
"""

from __future__ import annotations

import itertools
import logging
import subprocess
from dataclasses import dataclass

from pants.backend.codegen.protobuf.python.python_protobuf_subsystem import PythonProtobufMypyPlugin
from pants.backend.docker.subsystems.dockerfile_parser import DockerfileParser
from pants.backend.python.goals.coverage_py import CoverageSubsystem
from pants.backend.python.lint.autoflake.subsystem import Autoflake
from pants.backend.python.lint.bandit.subsystem import Bandit
from pants.backend.python.lint.black.subsystem import Black
from pants.backend.python.lint.docformatter.subsystem import Docformatter
from pants.backend.python.lint.flake8.subsystem import Flake8
from pants.backend.python.lint.isort.subsystem import Isort
from pants.backend.python.lint.pylint.subsystem import Pylint
from pants.backend.python.lint.pyupgrade.subsystem import PyUpgrade
from pants.backend.python.lint.yapf.subsystem import Yapf
from pants.backend.python.subsystems.ipython import IPython
from pants.backend.python.subsystems.lambdex import Lambdex
from pants.backend.python.subsystems.pytest import PyTest
from pants.backend.python.subsystems.python_tool_base import PythonToolRequirementsBase
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.subsystems.setuptools import Setuptools
from pants.backend.python.subsystems.twine import TwineSubsystem
from pants.backend.python.typecheck.mypy.subsystem import MyPy
from pants.backend.terraform.dependency_inference import TerraformHcl2Parser

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DefaultTool:
    """How to generate the default lockfile for a tool.

    We must be careful that we configure our settings properly so that internal config does not mess
    up the default.
    """

    resolve_name: str
    args: tuple[str, ...]

    @classmethod
    def from_python_tool(
        cls,
        tool: type[PythonToolRequirementsBase],
        *,
        backend: str | None = None,
        source_plugins: bool = False,
    ) -> DefaultTool:
        args = [
            f"--{tool.options_scope}-version={tool.default_version}",
            f"--{tool.options_scope}-extra-requirements={repr(tool.default_extra_requirements)}",
            f"--{tool.options_scope}-lockfile={tool.default_lockfile_path}",  # type: ignore[attr-defined]
        ]
        if tool.register_interpreter_constraints:
            args.append(
                f"--{tool.options_scope}-interpreter-constraints={repr(tool.default_interpreter_constraints)}"
            )
        if source_plugins:
            args.append(f"--{tool.options_scope}-source-plugins=[]")
        if backend:
            args.append(f"--backend-packages=+['{backend}']")
        return DefaultTool(tool.options_scope, tuple(args))


AllTools = (
    DefaultTool.from_python_tool(Autoflake),
    DefaultTool.from_python_tool(Bandit, backend="pants.backend.python.lint.bandit"),
    DefaultTool.from_python_tool(Black),
    DefaultTool.from_python_tool(Docformatter),
    DefaultTool.from_python_tool(Flake8, source_plugins=True),
    DefaultTool.from_python_tool(Isort),
    DefaultTool.from_python_tool(
        Pylint, backend="pants.backend.python.lint.pylint", source_plugins=True
    ),
    DefaultTool.from_python_tool(Yapf, backend="pants.backend.python.lint.yapf"),
    DefaultTool.from_python_tool(
        PyUpgrade, backend="pants.backend.experimental.python.lint.pyupgrade"
    ),
    DefaultTool.from_python_tool(IPython),
    DefaultTool.from_python_tool(Setuptools),
    DefaultTool.from_python_tool(MyPy, source_plugins=True),
    DefaultTool.from_python_tool(
        PythonProtobufMypyPlugin, backend="pants.backend.codegen.protobuf.python"
    ),
    DefaultTool.from_python_tool(Lambdex, backend="pants.backend.awslambda.python"),
    DefaultTool.from_python_tool(PyTest),
    DefaultTool.from_python_tool(CoverageSubsystem),
    DefaultTool.from_python_tool(
        TerraformHcl2Parser, backend="pants.backend.experimental.terraform"
    ),
    DefaultTool.from_python_tool(DockerfileParser, backend="pants.backend.experimental.docker"),
    DefaultTool.from_python_tool(TwineSubsystem),
)


def update_internal_lockfiles() -> None:
    subprocess.run(
        [
            "./pants",
            "--concurrent",
            "--tag=-lockfile_ignore",
            # `generate_all_lockfiles.sh` will have overridden this option to solve the chicken
            # and egg problem from https://github.com/pantsbuild/pants/issues/12457. We must
            # restore it here so that the lockfile gets generated properly.
            "--python-experimental-lockfile=3rdparty/python/lockfiles/user_reqs.txt",
            "generate-lockfiles",
            "generate-user-lockfile",
            "::",
        ],
        check=True,
    )


def update_default_lockfiles() -> None:
    subprocess.run(
        [
            "./pants",
            "--concurrent",
            f"--python-interpreter-constraints={repr(PythonSetup.default_interpreter_constraints)}",
            *itertools.chain.from_iterable(tool.args for tool in AllTools),
            "generate-lockfiles",
        ],
        check=True,
    )


def main() -> None:
    update_internal_lockfiles()
    update_default_lockfiles()


if __name__ == "__main__":
    main()
