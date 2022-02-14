# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from textwrap import dedent

import pytest

from pants.backend.debian.rules import package_debian_package
from pants.backend.debian.target_types import DebianPackage
from pants.backend.python import target_types_rules
from pants.core.util_rules import source_files
from pants.core.util_rules.source_files import SourceFilesRequest, SourceFiles
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *package_debian_package(),
            *source_files.rules(),
            *target_types_rules.rules(),
            QueryRule(SourceFiles, (SourceFilesRequest,)),
        ],
        target_types=[DebianPackage],
    )


def create_debian_package(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {"project/BUILD": dedent(
            """
            debian_package(
                name='my-package',
                description='Useful tools installed as Debian package.',                                
                sources=['project/files/**/*'],
            )
            """
        ),
         "project/files/DEBIAN/control": dedent(
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
         "project/files/platform.conf": dedent(
            """
            Some configuration.
            """
         )
        }
    )

    # TODO(alexey): create a Debian package
    return
