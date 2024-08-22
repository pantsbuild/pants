# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from textwrap import dedent

import pytest

from pants.backend.makeself import subsystem
from pants.backend.makeself import system_binaries as makeself_system_binaries
from pants.backend.makeself.goals import package, run
from pants.backend.makeself.goals.package import (
    BuiltMakeselfArchiveArtifact,
    MakeselfArchiveFieldSet,
)
from pants.backend.makeself.subsystem import RunMakeselfArchive
from pants.backend.makeself.target_types import MakeselfArchiveTarget
from pants.backend.shell import register
from pants.core.goals.package import BuiltPackage
from pants.core.target_types import FilesGeneratorTarget, FileTarget
from pants.core.target_types import rules as core_target_types_rules
from pants.core.util_rules import system_binaries
from pants.engine.addresses import Address
from pants.engine.fs import DigestContents, FileContent
from pants.engine.process import ProcessResult
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        target_types=[
            MakeselfArchiveTarget,
            FileTarget,
            FilesGeneratorTarget,
            *register.target_types(),
        ],
        rules=[
            *subsystem.rules(),
            *package.rules(),
            *run.rules(),
            *system_binaries.rules(),
            *register.rules(),
            *makeself_system_binaries.rules(),
            *core_target_types_rules(),
            QueryRule(BuiltPackage, [MakeselfArchiveFieldSet]),
            QueryRule(ProcessResult, [RunMakeselfArchive]),
        ],
    )
    rule_runner.set_options(args=[], env_inherit=PYTHON_BOOTSTRAP_ENV)
    return rule_runner


def test_simple_archive(rule_runner: RuleRunner) -> None:
    binary_name = "archive"

    rule_runner.write_files(
        {
            "files/BUILD": dedent(
                f"""
                files(sources=["*.txt"])
                makeself_archive(
                    name="{binary_name}",
                    args=["--notemp"],
                    files=["files/README.txt"],
                )
                """
            ),
            "files/README.txt": "TEST",
        }
    )

    target = rule_runner.get_target(Address("files", target_name=binary_name))
    field_set = MakeselfArchiveFieldSet.create(target)

    package = rule_runner.request(BuiltPackage, [field_set])

    assert len(package.artifacts) == 1, field_set
    assert isinstance(package.artifacts[0], BuiltMakeselfArchiveArtifact)
    relpath = f"files/{binary_name}.run"
    assert package.artifacts[0].relpath == relpath

    result = rule_runner.request(
        ProcessResult,
        [
            RunMakeselfArchive(
                exe=relpath,
                extra_args=("--quiet",),
                description="Run built subsystem archive",
                input_digest=package.digest,
                output_directory="_out",
            )
        ],
    )
    assert result.stdout == b""
    contents = rule_runner.request(DigestContents, [result.output_digest])
    assert contents == DigestContents([FileContent(path="_out/files/README.txt", content=b"TEST")])


def test_inline_script(rule_runner: RuleRunner) -> None:
    binary_name = "archive"

    rule_runner.write_files(
        {
            "src/shell/BUILD": dedent(
                f"""
                makeself_archive(
                    name="{binary_name}",
                    startup_script=["echo", "test"],
                )
                """
            ),
        }
    )

    target = rule_runner.get_target(Address("src/shell", target_name=binary_name))
    field_set = MakeselfArchiveFieldSet.create(target)

    package = rule_runner.request(BuiltPackage, [field_set])

    assert len(package.artifacts) == 1, field_set
    assert isinstance(package.artifacts[0], BuiltMakeselfArchiveArtifact)
    relpath = f"src.shell/{binary_name}.run"
    assert package.artifacts[0].relpath == relpath

    result = rule_runner.request(
        ProcessResult,
        [
            RunMakeselfArchive(
                exe=relpath,
                extra_args=("--quiet",),
                description="Run built subsystem archive",
                input_digest=package.digest,
            )
        ],
    )
    assert result.stdout == b"test\n"


def test_same_directory(rule_runner: RuleRunner) -> None:
    binary_name = "archive"

    rule_runner.write_files(
        {
            "src/shell/BUILD": dedent(
                f"""
                shell_sources(name="src")
                makeself_archive(
                    name="{binary_name}",
                    startup_script=["src/shell/run.sh"],
                    files=[":src"],
                )
                """
            ),
            "src/shell/run.sh": dedent(
                """
                #!/bin/bash
                echo test
                """
            ),
        }
    )
    rule_runner.chmod("src/shell/run.sh", 0o777)

    target = rule_runner.get_target(Address("src/shell", target_name=binary_name))
    field_set = MakeselfArchiveFieldSet.create(target)

    package = rule_runner.request(BuiltPackage, [field_set])

    assert len(package.artifacts) == 1, field_set
    assert isinstance(package.artifacts[0], BuiltMakeselfArchiveArtifact)
    relpath = f"src.shell/{binary_name}.run"
    assert package.artifacts[0].relpath == relpath

    result = rule_runner.request(
        ProcessResult,
        [
            RunMakeselfArchive(
                exe=relpath,
                extra_args=("--quiet",),
                description="Run built subsystem archive",
                input_digest=package.digest,
            )
        ],
    )
    assert result.stdout == b"test\n"


def test_different_directory(rule_runner: RuleRunner) -> None:
    binary_name = "archive"

    rule_runner.write_files(
        {
            "src/shell/BUILD": "shell_sources()",
            "src/shell/run.sh": dedent(
                """
                #!/bin/bash
                echo test
                """
            ),
            "project/BUILD": dedent(
                f"""
                makeself_archive(
                    name="{binary_name}",
                    startup_script=["src/shell/run.sh"],
                    files=["src/shell/run.sh"],
                )
                """
            ),
        }
    )
    rule_runner.chmod("src/shell/run.sh", 0o777)

    target = rule_runner.get_target(Address("project", target_name=binary_name))
    field_set = MakeselfArchiveFieldSet.create(target)

    package = rule_runner.request(BuiltPackage, [field_set])

    assert len(package.artifacts) == 1, field_set
    assert isinstance(package.artifacts[0], BuiltMakeselfArchiveArtifact)
    relpath = f"project/{binary_name}.run"
    assert package.artifacts[0].relpath == relpath

    result = rule_runner.request(
        ProcessResult,
        [
            RunMakeselfArchive(
                exe=relpath,
                extra_args=("--quiet",),
                description="Run built subsystem archive",
                input_digest=package.digest,
            )
        ],
    )
    assert result.stdout == b"test\n"


def test_multiple_scripts(rule_runner: RuleRunner) -> None:
    binary_name = "archive"

    rule_runner.write_files(
        {
            "src/shell/BUILD": dedent(
                f"""
                shell_sources(name="src")
                makeself_archive(
                    name="{binary_name}",
                    startup_script=["src/shell/run.sh"],
                    files=[":src"],
                )
                """
            ),
            "src/shell/hello.sh": dedent(
                """
                #!/bin/bash
                printf hello
                """
            ),
            "src/shell/world.sh": dedent(
                """
                #!/bin/bash
                printf world
                """
            ),
            "src/shell/run.sh": dedent(
                """
                #!/bin/bash
                src/shell/hello.sh
                src/shell/world.sh
                """
            ),
        }
    )
    rule_runner.chmod("src/shell/run.sh", 0o777)
    rule_runner.chmod("src/shell/hello.sh", 0o777)
    rule_runner.chmod("src/shell/world.sh", 0o777)

    target = rule_runner.get_target(Address("src/shell", target_name=binary_name))
    field_set = MakeselfArchiveFieldSet.create(target)

    package = rule_runner.request(BuiltPackage, [field_set])

    assert len(package.artifacts) == 1, field_set
    assert isinstance(package.artifacts[0], BuiltMakeselfArchiveArtifact)
    relpath = f"src.shell/{binary_name}.run"
    assert package.artifacts[0].relpath == relpath

    result = rule_runner.request(
        ProcessResult,
        [
            RunMakeselfArchive(
                exe=relpath,
                extra_args=("--quiet",),
                description="Run built subsystem archive",
                input_digest=package.digest,
            )
        ],
    )
    assert result.stdout == b"helloworld"
