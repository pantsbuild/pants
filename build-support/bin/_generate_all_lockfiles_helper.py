# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import argparse
import itertools
import logging
import subprocess
import sys
from dataclasses import dataclass

from pants.backend.cc.lint.clangformat.subsystem import ClangFormat
from pants.backend.codegen.avro.java.subsystem import AvroSubsystem
from pants.backend.codegen.protobuf.java.subsystem import JavaProtobufGrpcSubsystem
from pants.backend.codegen.protobuf.python.python_protobuf_subsystem import PythonProtobufMypyPlugin
from pants.backend.codegen.protobuf.scala.subsystem import ScalaPBSubsystem
from pants.backend.codegen.thrift.scrooge.subsystem import ScroogeSubsystem
from pants.backend.docker.subsystems.dockerfile_parser import DockerfileParser
from pants.backend.java.lint.google_java_format.subsystem import GoogleJavaFormatSubsystem
from pants.backend.java.subsystems.junit import JUnit
from pants.backend.kotlin.lint.ktlint.subsystem import KtlintSubsystem
from pants.backend.python.goals.coverage_py import CoverageSubsystem
from pants.backend.python.lint.add_trailing_comma.subsystem import AddTrailingComma
from pants.backend.python.lint.autoflake.subsystem import Autoflake
from pants.backend.python.lint.bandit.subsystem import Bandit
from pants.backend.python.lint.black.subsystem import Black
from pants.backend.python.lint.docformatter.subsystem import Docformatter
from pants.backend.python.lint.flake8.subsystem import Flake8
from pants.backend.python.lint.isort.subsystem import Isort
from pants.backend.python.lint.pydocstyle.subsystem import Pydocstyle
from pants.backend.python.lint.pylint.subsystem import Pylint
from pants.backend.python.lint.pyupgrade.subsystem import PyUpgrade
from pants.backend.python.lint.ruff.subsystem import Ruff
from pants.backend.python.lint.yapf.subsystem import Yapf
from pants.backend.python.packaging.pyoxidizer.subsystem import PyOxidizer
from pants.backend.python.subsystems.debugpy import DebugPy
from pants.backend.python.subsystems.ipython import IPython
from pants.backend.python.subsystems.lambdex import Lambdex
from pants.backend.python.subsystems.pytest import PyTest
from pants.backend.python.subsystems.python_tool_base import PythonToolRequirementsBase
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.subsystems.setuptools import Setuptools
from pants.backend.python.subsystems.setuptools_scm import SetuptoolsSCM
from pants.backend.python.subsystems.twine import TwineSubsystem
from pants.backend.python.typecheck.mypy.subsystem import MyPy
from pants.backend.scala.lint.scalafmt.subsystem import ScalafmtSubsystem
from pants.backend.scala.subsystems.scalatest import Scalatest
from pants.backend.terraform.dependency_inference import TerraformHcl2Parser
from pants.backend.tools.yamllint.subsystem import Yamllint
from pants.jvm.resolve.jvm_tool import JvmToolBase
from pants.util.strutil import softwrap

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
    DefaultTool.python(
        AddTrailingComma, backend="pants.backend.experimental.python.lint.add_trailing_comma"
    ),
    DefaultTool.python(Autoflake),
    DefaultTool.python(Bandit, backend="pants.backend.python.lint.bandit"),
    DefaultTool.python(Black),
    DefaultTool.python(ClangFormat, backend="pants.backend.experimental.cc.lint.clangformat"),
    DefaultTool.python(CoverageSubsystem),
    DefaultTool.python(DebugPy),
    DefaultTool.python(Docformatter),
    DefaultTool.python(DockerfileParser, backend="pants.backend.docker"),
    DefaultTool.python(Flake8, source_plugins=True),
    DefaultTool.python(IPython),
    DefaultTool.python(Isort),
    DefaultTool.python(Lambdex, backend="pants.backend.awslambda.python"),
    DefaultTool.python(MyPy, source_plugins=True),
    DefaultTool.python(Pydocstyle, backend="pants.backend.python.lint.pydocstyle"),
    DefaultTool.python(PyTest),
    DefaultTool.python(PyUpgrade, backend="pants.backend.experimental.python.lint.pyupgrade"),
    DefaultTool.python(Pylint, backend="pants.backend.python.lint.pylint", source_plugins=True),
    DefaultTool.python(PythonProtobufMypyPlugin, backend="pants.backend.codegen.protobuf.python"),
    DefaultTool.python(PyOxidizer),
    DefaultTool.python(Setuptools),
    DefaultTool.python(SetuptoolsSCM),
    DefaultTool.python(TerraformHcl2Parser, backend="pants.backend.experimental.terraform"),
    DefaultTool.python(TwineSubsystem),
    DefaultTool.python(Yamllint, backend="pants.backend.experimental.tools.yamllint"),
    DefaultTool.python(Yapf, backend="pants.backend.python.lint.yapf"),
    DefaultTool.python(Ruff, backend="pants.backend.experimental.python.lint.ruff"),
    # JVM
    DefaultTool.jvm(AvroSubsystem, backend="pants.backend.experimental.codegen.avro.java"),
    DefaultTool.jvm(GoogleJavaFormatSubsystem),
    DefaultTool.jvm(JUnit),
    DefaultTool.jvm(KtlintSubsystem, backend="pants.backend.experimental.kotlin.lint.ktlint"),
    DefaultTool.jvm(ScalaPBSubsystem, backend="pants.backend.experimental.codegen.protobuf.scala"),
    DefaultTool.jvm(
        JavaProtobufGrpcSubsystem, backend="pants.backend.experimental.codegen.protobuf.java"
    ),
    DefaultTool.jvm(ScalafmtSubsystem),
    DefaultTool.jvm(Scalatest),
    DefaultTool.jvm(
        ScroogeSubsystem, backend="pants.backend.experimental.codegen.thrift.scrooge.scala"
    ),
)


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=softwrap(
            """
            Generate lockfiles for internal usage + default tool lockfiles that we distribute.
            This script makes sure that tool lockfiles are generated with the correct values.
            """
        ),
        prog="generate_all_lockfiles.sh",
    )
    parser.add_argument(
        "--internal",
        action="store_true",
        help=softwrap(
            """
            Regenerate all internal lockfiles. Use this when you change our
            `requirements.txt` and/or internal config of tools, like adding a new Flake8 plugin.
            """
        ),
    )
    parser.add_argument(
        "--tool",
        nargs="*",
        help=softwrap(
            f"""
            Regenerate these default tool lockfile(s). Use this when bumping default versions
            of particular tools. Valid options:
            {sorted(tool.resolve_name for tool in AllTools)}
            """
        ),
    )
    parser.add_argument(
        "--pex",
        action="store_true",
        help=softwrap(
            """
            Use when bumping the PEX version. (Will regenerate our internal user lockfile &
            the Lambdex tool's lockfile.)
            """
        ),
    )
    parser.add_argument(
        "--all", action="store_true", help="Regenerate all internal and default tool lockfiles."
    )
    return parser


def update_internal_lockfiles(specified: list[str] | None) -> None:
    args = [
        "./pants",
        "--concurrent",
        f"--python-interpreter-constraints={repr(PythonSetup.default_interpreter_constraints)}",
        # `generate_all_lockfiles.sh` will have overridden this option to solve the chicken
        # and egg problem from https://github.com/pantsbuild/pants/issues/12457. We must
        # restore it here so that the lockfile gets generated properly.
        "--python-enable-resolves",
        "generate-lockfiles",
    ]
    if specified:
        args.append(f"--resolve={repr(specified)}")
    subprocess.run(args, check=True)


def update_default_lockfiles(specified: list[str] | None) -> None:
    args = [
        "./pants",
        "--concurrent",
        f"--python-interpreter-constraints={repr(PythonSetup.default_interpreter_constraints)}",
        *itertools.chain.from_iterable(tool.args for tool in AllTools),
        # `generate_all_lockfiles.sh` will have overridden this option to solve the chicken
        # and egg problem from https://github.com/pantsbuild/pants/issues/12457. We must
        # restore it here so that the lockfile gets generated properly.
        "--python-enable-resolves",
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
        update_internal_lockfiles(specified=None)
        update_default_lockfiles(specified=None)
        return

    if args.pex:
        update_internal_lockfiles(specified=["python-default"])
        update_default_lockfiles(specified=[Lambdex.options_scope])
        return

    if args.internal:
        update_internal_lockfiles(specified=None)
    if args.tool:
        update_default_lockfiles(specified=args.tool)


if __name__ == "__main__":
    main()
