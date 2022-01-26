# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import argparse
import itertools
import logging
import subprocess
import sys
from dataclasses import dataclass

from pants.backend.codegen.avro.java.subsystem import AvroSubsystem
from pants.backend.codegen.protobuf.python.python_protobuf_subsystem import PythonProtobufMypyPlugin
from pants.backend.codegen.protobuf.scala.subsystem import ScalaPBSubsystem
from pants.backend.codegen.thrift.scrooge.subsystem import ScroogeSubsystem
from pants.backend.docker.subsystems.dockerfile_parser import DockerfileParser
from pants.backend.java.lint.google_java_format.subsystem import GoogleJavaFormatSubsystem
from pants.backend.java.subsystems.junit import JUnit
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
from pants.backend.scala.lint.scalafmt.subsystem import ScalafmtSubsystem
from pants.backend.scala.subsystems.scalac import Scalac
from pants.backend.scala.subsystems.scalatest import Scalatest
from pants.backend.terraform.dependency_inference import TerraformHcl2Parser
from pants.jvm.resolve.jvm_tool import JvmToolBase

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
    def python(
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

    @classmethod
    def jvm(cls, tool: type[JvmToolBase], *, backend: str | None = None) -> DefaultTool:
        args = [
            f"--{tool.options_scope}-version={tool.default_version}",
            f"--{tool.options_scope}-artifacts={tool.default_artifacts}",
            f"--{tool.options_scope}-lockfile={tool.default_lockfile_path}",  # type: ignore[attr-defined]
        ]
        if backend:
            args.append(f"--backend-packages=+['{backend}']")
        return DefaultTool(tool.options_scope, tuple(args))


AllTools = (
    # Python
    DefaultTool.python(Autoflake),
    DefaultTool.python(Bandit, backend="pants.backend.python.lint.bandit"),
    DefaultTool.python(Black),
    DefaultTool.python(Docformatter),
    DefaultTool.python(Flake8, source_plugins=True),
    DefaultTool.python(Isort),
    DefaultTool.python(Pylint, backend="pants.backend.python.lint.pylint", source_plugins=True),
    DefaultTool.python(Yapf, backend="pants.backend.python.lint.yapf"),
    DefaultTool.python(PyUpgrade, backend="pants.backend.experimental.python.lint.pyupgrade"),
    DefaultTool.python(IPython),
    DefaultTool.python(Setuptools),
    DefaultTool.python(MyPy, source_plugins=True),
    DefaultTool.python(PythonProtobufMypyPlugin, backend="pants.backend.codegen.protobuf.python"),
    DefaultTool.python(Lambdex, backend="pants.backend.awslambda.python"),
    DefaultTool.python(PyTest),
    DefaultTool.python(CoverageSubsystem),
    DefaultTool.python(TerraformHcl2Parser, backend="pants.backend.experimental.terraform"),
    DefaultTool.python(DockerfileParser, backend="pants.backend.experimental.docker"),
    DefaultTool.python(TwineSubsystem),
    # JVM
    DefaultTool.jvm(JUnit),
    DefaultTool.jvm(GoogleJavaFormatSubsystem),
    DefaultTool.jvm(ScalafmtSubsystem),
    DefaultTool.jvm(ScalaPBSubsystem, backend="pants.backend.experimental.codegen.protobuf.scala"),
    DefaultTool.jvm(Scalatest),
    DefaultTool.jvm(
        ScroogeSubsystem, backend="pants.backend.experimental.codegen.thrift.scrooge.scala"
    ),
    DefaultTool.jvm(AvroSubsystem, backend="pants.backend.experimental.codegen.avro.java"),
    DefaultTool(
        "scalac-plugins",
        (f"--scalac-plugins-global-lockfile={Scalac.default_plugins_lockfile_path}",),
    ),
)


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate lockfiles for internal usage + default tool lockfiles that we distribute. "
            "This script makes sure that tool lockfiles are generated with the correct values."
        ),
        prog="generate_all_lockfiles.sh",
    )
    parser.add_argument(
        "--internal", action="store_true", help="Regenerate all internal lockfiles."
    )
    parser.add_argument(
        "--tool",
        nargs="*",
        help=(
            f"Regenerate these default tool lockfile(s). Valid options: "
            f"{sorted(tool.resolve_name for tool in AllTools)}"
        ),
    )
    parser.add_argument(
        "--all", action="store_true", help="Regenerate all internal and default tool lockfiles."
    )
    return parser


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


def update_default_lockfiles(specified: list[str] | None) -> None:
    args = [
        "./pants",
        "--concurrent",
        f"--python-interpreter-constraints={repr(PythonSetup.default_interpreter_constraints)}",
        *itertools.chain.from_iterable(tool.args for tool in AllTools),
        "generate-lockfiles",
    ]
    if specified:
        args.append(f"--resolve={repr(specified)}")
    subprocess.run(args, check=True)


def main() -> None:
    if len(sys.argv) == 1:
        create_parser().print_help()
        return
    args = create_parser().parse_args()

    if args.all:
        update_internal_lockfiles()
        update_default_lockfiles(specified=None)
        return

    if args.internal:
        update_internal_lockfiles()
    if args.tool:
        update_default_lockfiles(specified=args.tool)


if __name__ == "__main__":
    main()
