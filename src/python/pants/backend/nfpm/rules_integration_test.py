# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.nfpm.field_sets import NFPM_PACKAGE_FIELD_SET_TYPES
from pants.backend.nfpm.rules import rules as nfpm_rules
from pants.backend.nfpm.target_types import target_types as nfpm_target_types
from pants.backend.nfpm.target_types_rules import rules as nfpm_target_types_rules
from pants.core.goals.package import BuiltPackage
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        target_types=[
            *nfpm_target_types(),
        ],
        rules=[
            *nfpm_target_types_rules(),
            *nfpm_rules(),
            *(
                QueryRule(BuiltPackage, [field_set_type])
                for field_set_type in NFPM_PACKAGE_FIELD_SET_TYPES
            ),
        ],
    )
    return rule_runner


def test_generate_package(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """
                nfpm_apk_package(
                    name="pkg",
                    package_name="pkg",
                    version="3.2.1",
                )
                """
            ),
        }
    )
