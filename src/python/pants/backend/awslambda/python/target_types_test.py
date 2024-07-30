# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.backend.awslambda.python.target_types import PythonAWSLambda, PythonAwsLambdaRuntime
from pants.backend.awslambda.python.target_types import rules as target_type_rules
from pants.backend.python.target_types import PythonRequirementTarget, PythonSourcesGeneratorTarget
from pants.backend.python.target_types_rules import rules as python_target_types_rules
from pants.build_graph.address import Address
from pants.core.target_types import FileTarget
from pants.engine.target import InvalidFieldException
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *target_type_rules(),
            *python_target_types_rules(),
        ],
        target_types=[
            FileTarget,
            PythonAWSLambda,
            PythonRequirementTarget,
            PythonSourcesGeneratorTarget,
        ],
    )


@pytest.mark.parametrize(
    ["runtime", "expected_major", "expected_minor"],
    (
        # The available runtimes at the time of writing.
        # See https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtimes.html.
        ["python2.7", 2, 7],
        ["python3.6", 3, 6],
        ["python3.7", 3, 7],
        ["python3.8", 3, 8],
        ["python3.8", 3, 8],
        ["python3.9", 3, 9],
        ["python3.10", 3, 10],
        ["python3.11", 3, 11],
        ["python3.12", 3, 12],
    ),
)
def test_to_interpreter_version(runtime: str, expected_major: int, expected_minor: int) -> None:
    assert (expected_major, expected_minor) == PythonAwsLambdaRuntime(
        runtime, Address("", target_name="t")
    ).to_interpreter_version()


@pytest.mark.parametrize("invalid_runtime", ("python88.99", "fooobar"))
def test_runtime_validation(invalid_runtime: str) -> None:
    with pytest.raises(InvalidFieldException):
        PythonAwsLambdaRuntime(invalid_runtime, Address("", target_name="t"))
