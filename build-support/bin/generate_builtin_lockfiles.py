# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import argparse
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from textwrap import dedent
from typing import Generic, Sequence, Type, TypeVar, cast

from pants.backend.cc.lint.clangformat.subsystem import ClangFormat
from pants.backend.codegen.avro.java.subsystem import AvroSubsystem
from pants.backend.codegen.protobuf.java.subsystem import JavaProtobufGrpcSubsystem
from pants.backend.codegen.protobuf.python.python_protobuf_subsystem import (
    PythonProtobufGrpclibPlugin,
    PythonProtobufMypyPlugin,
)
from pants.backend.codegen.protobuf.scala.subsystem import ScalaPBSubsystem
from pants.backend.codegen.thrift.scrooge.subsystem import ScroogeSubsystem
from pants.backend.docker.subsystems.dockerfile_parser import DockerfileParser
from pants.backend.helm.subsystems.k8s_parser import HelmKubeParserSubsystem
from pants.backend.helm.subsystems.post_renderer import HelmPostRendererSubsystem
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
from pants.backend.python.subsystems.pytest import PyTest
from pants.backend.python.subsystems.python_tool_base import PythonToolRequirementsBase
from pants.backend.python.subsystems.setuptools import Setuptools
from pants.backend.python.subsystems.setuptools_scm import SetuptoolsSCM
from pants.backend.python.subsystems.twine import TwineSubsystem
from pants.backend.python.typecheck.mypy.subsystem import MyPy
from pants.backend.python.typecheck.pytype.subsystem import Pytype
from pants.backend.scala.lint.scalafmt.subsystem import ScalafmtSubsystem
from pants.backend.scala.subsystems.scalatest import Scalatest
from pants.backend.terraform.dependency_inference import TerraformHcl2Parser
from pants.backend.tools.semgrep.subsystem import SemgrepSubsystem
from pants.backend.tools.yamllint.subsystem import Yamllint
from pants.base.build_environment import get_buildroot
from pants.jvm.resolve.jvm_tool import JvmToolBase
from pants.jvm.shading.jarjar import JarJar
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import touch

logger = logging.getLogger(__name__)


default_python_interpreter_constraints = "CPython>=3.7,<4"


ToolBaseT = TypeVar("ToolBaseT")


@dataclass
class Tool(Generic[ToolBaseT]):
    cls: Type[ToolBaseT]
    backend: str

    @property
    def name(self) -> str:
        return cast(str, self.cls.options_scope)  # type: ignore[attr-defined]

    @property
    def resolve(self) -> str:
        return self.name

    @property
    def lockfile_name(self) -> str:
        return f"{self.name}.lock"


@dataclass
class PythonTool(Tool[PythonToolRequirementsBase]):
    ...


@dataclass
class JvmTool(Tool[JvmToolBase]):
    ...


all_python_tools = tuple(
    sorted(
        [
            PythonTool(
                AddTrailingComma, "pants.backend.experimental.python.lint.add_trailing_comma"
            ),
            PythonTool(Autoflake, "pants.backend.python.lint.autoflake"),
            PythonTool(Bandit, "pants.backend.python.lint.bandit"),
            PythonTool(Black, "pants.backend.python.lint.black"),
            PythonTool(ClangFormat, "pants.backend.experimental.cc.lint.clangformat"),
            PythonTool(CoverageSubsystem, "pants.backend.python"),
            PythonTool(DebugPy, "pants.backend.python"),
            PythonTool(Docformatter, "pants.backend.python.lint.docformatter"),
            PythonTool(DockerfileParser, "pants.backend.docker"),
            PythonTool(Flake8, "pants.backend.python.lint.flake8"),
            PythonTool(HelmKubeParserSubsystem, "pants.backend.experimental.helm"),
            PythonTool(HelmPostRendererSubsystem, "pants.backend.experimental.helm"),
            PythonTool(IPython, "pants.backend.python"),
            PythonTool(Isort, "pants.backend.python.lint.isort"),
            PythonTool(MyPy, "pants.backend.python.typecheck.mypy"),
            PythonTool(Pydocstyle, "pants.backend.python.lint.pydocstyle"),
            PythonTool(PyTest, "pants.backend.python"),
            PythonTool(PyUpgrade, "pants.backend.python.lint.pyupgrade"),
            PythonTool(Pylint, "pants.backend.python.lint.pylint"),
            PythonTool(PythonProtobufMypyPlugin, "pants.backend.codegen.protobuf.python"),
            PythonTool(PythonProtobufGrpclibPlugin, "pants.backend.codegen.protobuf.python"),
            PythonTool(Pytype, "pants.backend.experimental.python.typecheck.pytype"),
            PythonTool(PyOxidizer, "pants.backend.experimental.python.packaging.pyoxidizer"),
            PythonTool(Ruff, "pants.backend.python.lint.ruff"),
            PythonTool(SemgrepSubsystem, "pants.backend.experimental.tools.semgrep"),
            PythonTool(Setuptools, "pants.backend.python"),
            PythonTool(SetuptoolsSCM, "pants.backend.python"),
            PythonTool(TerraformHcl2Parser, "pants.backend.experimental.terraform"),
            PythonTool(TwineSubsystem, "pants.backend.python"),
            PythonTool(Yamllint, "pants.backend.experimental.tools.yamllint"),
            PythonTool(Yapf, "pants.backend.python.lint.yapf"),
        ],
        key=lambda tool: tool.name,
    )
)


all_jvm_tools = tuple(
    sorted(
        [
            JvmTool(AvroSubsystem, "pants.backend.experimental.codegen.avro.java"),
            JvmTool(
                GoogleJavaFormatSubsystem, "pants.backend.experimental.java.lint.google_java_format"
            ),
            JvmTool(JUnit, "pants.backend.experimental.java"),
            JvmTool(JarJar, "pants.backend.experimental.java"),
            JvmTool(JavaProtobufGrpcSubsystem, "pants.backend.experimental.codegen.protobuf.java"),
            JvmTool(KtlintSubsystem, "pants.backend.experimental.kotlin.lint.ktlint"),
            JvmTool(ScalaPBSubsystem, "pants.backend.experimental.codegen.protobuf.scala"),
            JvmTool(ScalafmtSubsystem, "pants.backend.experimental.scala.lint.scalafmt"),
            JvmTool(Scalatest, "pants.backend.experimental.scala"),
            JvmTool(ScroogeSubsystem, "pants.backend.experimental.codegen.thrift.scrooge.scala"),
        ],
        key=lambda tool: tool.name,
    )
)


name_to_tool = {tool.name: tool for tool in (all_python_tools + all_jvm_tools)}


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate the tool lockfiles that we distribute with Pants.",
    )
    parser.add_argument(
        "tool",
        nargs="*",
        metavar="tool",
        # A quirk of argparse is that an empty list must be provided as one of the choices
        # to allow an empty list when nargs="*".
        choices=sorted(name_to_tool.keys()) + [[]],
        help="Regenerate this builtin tool lockfile",
    )
    parser.add_argument(
        "--all-python", action="store_true", help="Regenerate all builtin Python tool lockfiles."
    )
    parser.add_argument(
        "--all-jvm", action="store_true", help="Regenerate all builtin JVM tool lockfiles."
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Show Pants commands that would be run."
    )
    parser.add_argument(
        "-d",
        "--debug",
        action="store_const",
        dest="loglevel",
        const=logging.DEBUG,
        default=logging.INFO,
    )
    return parser


def generate_python_tool_lockfiles(tools: Sequence[PythonTool], dry_run: bool) -> None:
    def req_file(_tool: PythonTool) -> str:
        return f"{_tool.name}-requirements.txt"

    # Generate the builtin lockfiles via temporary named resolves in a tmp repo.
    # This is to completely disassociate the generation of builtin lockfiles from
    # the consumption of lockfiles in the Pants repo.
    with temporary_dir() as tmp_buildroot:
        for tool in tools:
            with open(os.path.join(tmp_buildroot, req_file(tool)), "w") as reqs_file:
                for req_str in tool.cls.default_requirements:
                    reqs_file.write(req_str)
                    reqs_file.write("\n")
        with open(os.path.join(tmp_buildroot, "BUILD"), "w") as build_file:
            for tool in tools:
                build_file.write(
                    dedent(
                        f"""\
                        python_requirements(
                            name="{tool.name}_reqs",
                            source="{req_file(tool)}",
                            resolve="{tool.resolve}",
                        )

                        """
                    )
                )
        resolves = {tool.resolve: tool.lockfile_name for tool in tools}
        resolves_to_ics = {tool.resolve: tool.cls.default_interpreter_constraints for tool in tools}
        for file in resolves.values():
            touch(os.path.join(tmp_buildroot, file))  # Prevent "Unmatched glob" warning.
        python_args = [
            # Regardless of the backend the tool is defined in, we need the Python backend
            # for the Python resolves mechanism to work.
            "--backend-packages=pants.backend.python",
            "--python-pip-version=latest",
            f"--python-interpreter-constraints=['{default_python_interpreter_constraints}']",
            "--python-enable-resolves",
            # Unset any existing resolve names in the Pants repo, and set to just our temporary ones.
            f"--python-resolves={resolves}",
            f"--python-resolves-to-interpreter-constraints={resolves_to_ics}",
            # Blank these out in case the Pants repo sets them using resolve names that we've unset.
            "--python-resolves-to-constraints-file={}",
            "--python-resolves-to-no-binary={}",
            "--python-resolves-to-only-binary={}",
        ]
        generate(tmp_buildroot, tools, python_args, dry_run)


def generate_jvm_tool_lockfiles(tools: Sequence[JvmTool], dry_run: bool) -> None:
    # Generate the builtin lockfiles via temporary named resolves in a tmp repo.
    # This is to completely disassociate the generation of builtin lockfiles from
    # the consumption of lockfiles in the Pants repo.
    with temporary_dir() as tmp_buildroot:
        jvm_args = []
        for tool in tools:
            jvm_args.extend(
                [
                    f"--{tool.name}-version={tool.cls.default_version}",
                    f"--{tool.name}-artifacts={tool.cls.default_artifacts}",
                    f"--{tool.name}-lockfile={tool.lockfile_name}",
                ]
            )
        generate(tmp_buildroot, tools, jvm_args, dry_run)


def generate(buildroot: str, tools: Sequence[Tool], args: Sequence[str], dry_run: bool) -> None:
    pants_repo_root = get_buildroot()
    touch(os.path.join(buildroot, "pants.toml"))
    backends = sorted({tool.backend for tool in tools})
    custom_cmd = "./pants run build-support/bin/generate_builtin_lockfiles.py"
    args = [
        os.path.join(pants_repo_root, "pants"),
        "--concurrent",
        "--anonymous-telemetry-enabled=false",
        f"--backend-packages={backends}",
        *args,
        f"--generate-lockfiles-custom-command={custom_cmd}",
        "generate-lockfiles",
        *[f"--resolve={tool.resolve}" for tool in tools],
    ]

    if dry_run:
        logger.info("Would run: " + " ".join(args))
        return

    logger.debug("Running: " + " ".join(args))
    subprocess.run(args, cwd=buildroot, check=True)

    # Copy the generated lockfiles from the tmp repo to the Pants repo.
    for tool in tools:
        lockfile_pkg, lockfile_filename = tool.cls.default_lockfile_resource
        lockfile_dest = os.path.join(
            "src",
            "python",
            lockfile_pkg.replace(".", os.path.sep),
            lockfile_filename,
        )
        shutil.copy(os.path.join(buildroot, tool.lockfile_name), lockfile_dest)


def main() -> None:
    parser = create_parser()
    args = parser.parse_args()
    logging.basicConfig(
        level=args.loglevel,
        format="%(asctime)s.%(msecs)02d [%(levelname)s] %(message)s",
        datefmt="%I:%M:%S",
    )

    python_tools = []
    jvm_tools = []
    for name in args.tool:
        tool = name_to_tool[name]
        if isinstance(tool, PythonTool):
            python_tools.append(tool)
        elif isinstance(tool, JvmTool):
            jvm_tools.append(tool)
        else:
            raise ValueError(f"Tool {name} has unknown type.")
    if args.all_python:
        python_tools.extend(all_python_tools)
    if args.all_jvm:
        jvm_tools.extend(all_jvm_tools)
    if not python_tools and not jvm_tools:
        raise ValueError(
            "Must specify at least one tool, either via positional args, "
            "or via the --all-python/--all-jvm flags."
        )
    if python_tools:
        generate_python_tool_lockfiles(python_tools, args.dry_run)
    if jvm_tools:
        generate_jvm_tool_lockfiles(jvm_tools, args.dry_run)


if __name__ == "__main__":
    main()
