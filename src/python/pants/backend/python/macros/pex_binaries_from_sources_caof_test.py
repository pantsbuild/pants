# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

import pytest

from pants.backend.python.macros.pex_binaries_from_sources_caof import PexBinariesFromSourcesCAOF
from pants.backend.python.target_types import PexBinary, PythonRequirementsFile, PythonRequirementTarget
from pants.engine.addresses import Address
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.target import AllTargets, InvalidFieldException
from pants.testutil.rule_runner import RuleRunner

@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        target_types=[PexBinary],
        context_aware_object_factories={"pex_binaries_from_sources": PexBinariesFromSourcesCAOF},
    )

def test_pex_binaries_from_sources(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                    pex_binaries_from_sources(
                        sources=[
                            "main1.py",
                            "main2.py",
                            "main3.py",
                        ],
                        overrides = {
                            "main2.py": {
                                "tags": ["overridden"],
                                "entry_point": "_main2.py",
                                "name": "ThePexBinaryFormerlyKnownAsMain2",
                            }
                        }
                    )
                """
            ),
        }
    )

    targets = rule_runner.request(AllTargets, [])
    assert set(targets) == {
        PexBinary({"entry_point": "main1.py"}, Address("", target_name="main1")),
        PexBinary(
            {
                "entry_point": "_main2.py",
                "tags": ["overridden"],
            },
            Address("", target_name="ThePexBinaryFormerlyKnownAsMain2")
        ),
        PexBinary({"entry_point": "main3.py"}, Address("", target_name="main3")),
    }

def test_invalid_overrides(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                    pex_binaries_from_sources(
                        sources=[],
                        overrides = {"invalid1": {}, "invalid2": {}}
                    )
                """
            ),
        }
    )

    with pytest.raises(ExecutionError) as exc_info:
        rule_runner.request(AllTargets, [])

    assert "'invalid1, invalid2'" in exc_info.value.wrapped_exceptions[0].args[0]
