# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import re
from textwrap import dedent

import pytest

from pants.backend.awslambda.python.target_types import PythonAWSLambda, PythonAwsLambdaRuntime
from pants.backend.awslambda.python.target_types import rules as target_type_rules
from pants.backend.python.target_types import PythonRequirementTarget, PythonSourcesGeneratorTarget
from pants.backend.python.target_types_rules import rules as python_target_types_rules
from pants.backend.python.util_rules.faas import PythonFaaSCompletePlatforms
from pants.build_graph.address import Address
from pants.core.target_types import FileTarget
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.target import InvalidFieldException
from pants.testutil.rule_runner import RuleRunner
from pants.util.strutil import softwrap


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


def test_at_least_one_target_platform(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "project/app.py": "",
            "project/platform-py37.json": "",
            "project/BUILD": dedent(
                """\
                python_aws_lambda_function(
                    name='runtime',
                    handler='project.app:func',
                    runtime='python3.7',
                )
                file(name="python37", source="platform-py37.json")
                python_aws_lambda_function(
                    name='complete_platforms',
                    handler='project.app:func',
                    complete_platforms=[':python37'],
                )
                python_aws_lambda_function(
                    name='both',
                    handler='project.app:func',
                    runtime='python3.7',
                    complete_platforms=[':python37'],
                )
                python_aws_lambda_function(
                    name='neither',
                    handler='project.app:func',
                )
                """
            ),
        }
    )

    runtime = rule_runner.get_target(Address("project", target_name="runtime"))
    assert "python3.7" == runtime[PythonAwsLambdaRuntime].value
    assert runtime[PythonFaaSCompletePlatforms].value is None

    complete_platforms = rule_runner.get_target(
        Address("project", target_name="complete_platforms")
    )
    assert complete_platforms[PythonAwsLambdaRuntime].value is None
    assert (":python37",) == complete_platforms[PythonFaaSCompletePlatforms].value

    both = rule_runner.get_target(Address("project", target_name="both"))
    assert "python3.7" == both[PythonAwsLambdaRuntime].value
    assert (":python37",) == both[PythonFaaSCompletePlatforms].value

    with pytest.raises(
        ExecutionError,
        match=r".*{}.*".format(
            re.escape(
                softwrap(
                    """
                    InvalidTargetException: The `python_aws_lambda_function` target project:neither must
                    specify either a `runtime` or `complete_platforms`.
                    """
                )
            )
        ),
    ):
        rule_runner.get_target(Address("project", target_name="neither"))
