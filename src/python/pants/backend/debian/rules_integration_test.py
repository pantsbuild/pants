# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import os
import subprocess
from textwrap import dedent

import pytest

from pants.backend.debian.rules import rules as debian_rules, DebianPackageFieldSet
from pants.backend.debian.target_types import DebianPackage
from pants.backend.python import target_types_rules
from pants.build_graph.address import Address
from pants.core.goals.package import BuiltPackage
from pants.core.util_rules import source_files
from pants.core.util_rules.source_files import SourceFilesRequest, SourceFiles
from pants.engine.rules import QueryRule
from pants.engine.target import Target
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *debian_rules(),
            *source_files.rules(),
            *target_types_rules.rules(),
            QueryRule(SourceFiles, (SourceFilesRequest,)),
            QueryRule(BuiltPackage, (DebianPackageFieldSet,)),
        ],
        target_types=[DebianPackage],
    )


def build_package(rule_runner: RuleRunner, binary_target: Target) -> BuiltPackage:
    field_set = DebianPackageFieldSet.create(binary_target)
    result = rule_runner.request(BuiltPackage, [field_set])
    rule_runner.write_digest(result.digest)
    return result


def test_create_debian_package(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {"BUILD": dedent(
            """
            debian_package(
                name='sample-debian-package',
                description='Useful tools installed as a Debian package.',
                packages=[],                                
                sources=['project/**/*'],
            )
            """
        ),
         "project/DEBIAN/control": dedent(
            """
            Package: sample-debian-package
            Version: 1.0
            Architecture: amd64
            Essential: no
            Section: dev
            Priority: optional
            Depends: python3, python3-distutils
            Maintainer: me@company.com
            Description: A sample Debian package built with Pants.
            """
        ),
         "project/opt/company/platform.conf": dedent(
            """
            Some configuration.
            """
         )
        }
    )

    binary_tgt = rule_runner.get_target(Address("", target_name="sample-debian-package"))
    built_package = build_package(rule_runner, binary_tgt)
    assert len(built_package.artifacts) == 1
    assert built_package.artifacts[0].relpath == "sample-debian-package.deb"

    # list the contents of a Debian package to see that a file was included
    result = subprocess.run(["dpkg", "-c", os.path.join(rule_runner.build_root, "sample-debian-package.deb")],
                            stdout=subprocess.PIPE)
    assert result.returncode == 0
    assert b"opt/company/platform.conf" in result.stdout
    return
