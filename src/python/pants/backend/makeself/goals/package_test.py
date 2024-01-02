# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from textwrap import dedent

import pytest

from pants.backend.makeself import makeself
from pants.backend.makeself.goals import package, run
from pants.backend.makeself.goals.package import (
    BuiltMakeselfArchiveArtifact,
    MakeselfArchiveFieldSet,
)
from pants.backend.makeself.makeself import RunMakeselfArchive
from pants.backend.makeself.target_types import MakeselfArchiveTarget
from pants.backend.shell import register
from pants.core.goals.package import BuiltPackage
from pants.core.util_rules import system_binaries
from pants.engine.addresses import Address
from pants.engine.process import ProcessResult
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        target_types=[
            MakeselfArchiveTarget,
            *register.target_types(),
        ],
        rules=[
            *makeself.rules(),
            *package.rules(),
            *run.rules(),
            *system_binaries.rules(),
            *register.rules(),
            QueryRule(BuiltPackage, [MakeselfArchiveFieldSet]),
            QueryRule(ProcessResult, [RunMakeselfArchive]),
        ],
    )
    rule_runner.set_options(args=[], env_inherit=PYTHON_BOOTSTRAP_ENV)
    return rule_runner


def test_makeself_package_same_directory(rule_runner: RuleRunner) -> None:
    binary_name = "archive"

    rule_runner.write_files(
        {
            "src/shell/BUILD": dedent(
                f"""
                shell_sources()
                makeself_archive(name='{binary_name}', startup_script='src/shell/run.sh')
                """
            ),
            "src/shell/run.sh": "echo test",
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
                description="Run built makeself archive",
                input_digest=package.digest,
            )
        ],
    )
    assert result.stdout == b"test\n"


def test_makeself_package_different_path(rule_runner: RuleRunner) -> None:
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
                makeself_archive(name='{binary_name}', startup_script='src/shell/run.sh')
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
                description="Run built makeself archive",
                input_digest=package.digest,
            )
        ],
    )
    assert result.stdout == b"test\n"
