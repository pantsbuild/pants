# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent
from typing import Optional

import pytest

from pants.backend.awslambda.python.target_types import (
    InjectPythonLambdaHandlerDependency,
    PythonAWSLambda,
    PythonAwsLambdaDependencies,
    PythonAwsLambdaHandlerField,
    PythonAwsLambdaRuntime,
    ResolvedPythonAwsHandler,
    ResolvePythonAwsHandlerRequest,
)
from pants.backend.awslambda.python.target_types import rules as target_type_rules
from pants.backend.python.target_types import PythonLibrary, PythonRequirementLibrary
from pants.build_graph.address import Address
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.target import InjectedDependencies, InvalidFieldException
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *target_type_rules(),
            QueryRule(ResolvedPythonAwsHandler, [ResolvePythonAwsHandlerRequest]),
            QueryRule(InjectedDependencies, [InjectPythonLambdaHandlerDependency]),
        ],
        target_types=[PythonAWSLambda, PythonRequirementLibrary, PythonLibrary],
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
def test_to_interpreter_version(runtime, expected_major, expected_minor):
    assert (expected_major, expected_minor) == PythonAwsLambdaRuntime(
        runtime, address=Address("", target_name="t")
    ).to_interpreter_version()


@pytest.mark.parametrize(["invalid_runtime"], (["python88.99"], ["fooobar"]))
def test_runtime_validation(invalid_runtime):
    with pytest.raises(InvalidFieldException):
        PythonAwsLambdaRuntime(invalid_runtime, address=Address("", target_name="t"))


@pytest.mark.parametrize(["invalid_handler"], (["path.to.lambda"], ["lambda.py"]))
def test_handler_validation(invalid_handler):
    with pytest.raises(InvalidFieldException):
        PythonAwsLambdaHandlerField(invalid_handler, address=Address("", target_name="t"))


def test_resolve_handler(rule_runner: RuleRunner) -> None:
    def assert_resolved(handler: str, *, expected: str) -> None:
        addr = Address("src/python/project")
        rule_runner.create_file("src/python/project/lambda.py")
        rule_runner.create_file("src/python/project/f2.py")
        field = PythonAwsLambdaHandlerField(handler, address=addr)
        result = rule_runner.request(
            ResolvedPythonAwsHandler, [ResolvePythonAwsHandlerRequest(field)]
        )
        assert result.val == expected

    assert_resolved("path.to.lambda:func", expected="path.to.lambda:func")
    assert_resolved("lambda.py:func", expected="project.lambda:func")

    with pytest.raises(ExecutionError):
        assert_resolved("doesnt_exist.py:func", expected="doesnt matter")
    # Resolving >1 file is an error.
    with pytest.raises(ExecutionError):
        assert_resolved("*.py:func", expected="doesnt matter")


def test_inject_handler_dependency(rule_runner: RuleRunner) -> None:
    rule_runner.add_to_build_file(
        "",
        dedent(
            """\
            python_requirement_library(
                name='ansicolors',
                requirements=['ansicolors'],
                module_mapping={'ansicolors': ['colors']},
            )
            """
        ),
    )
    rule_runner.create_files("project", ["app.py", "self.py"])
    rule_runner.add_to_build_file(
        "project",
        dedent(
            """\
            python_library(sources=['app.py'])
            python_awslambda(name='first_party', handler='project.app:func', runtime='python3.7')
            python_awslambda(name='first_party_shorthand', handler='app.py:func', runtime='python3.7')
            python_awslambda(name='third_party', handler='colors:func', runtime='python3.7')
            python_awslambda(name='unrecognized', handler='who_knows.module:func', runtime='python3.7')
            python_awslambda(
                name='self', sources=['self.py'], handler='project.self:func', runtime='python3.7'
            )
            """
        ),
    )

    def assert_injected(address: Address, *, expected: Optional[Address]) -> None:
        tgt = rule_runner.get_target(address)
        injected = rule_runner.request(
            InjectedDependencies,
            [InjectPythonLambdaHandlerDependency(tgt[PythonAwsLambdaDependencies])],
        )
        assert injected == InjectedDependencies([expected] if expected else [])

    assert_injected(
        Address("project", target_name="first_party"),
        expected=Address("project", relative_file_path="app.py"),
    )
    assert_injected(
        Address("project", target_name="first_party_shorthand"),
        expected=Address("project", relative_file_path="app.py"),
    )
    assert_injected(
        Address("project", target_name="third_party"),
        expected=Address("", target_name="ansicolors"),
    )
    assert_injected(Address("project", target_name="unrecognized"), expected=None)
    assert_injected(
        Address("project", target_name="self", relative_file_path="self.py"), expected=None
    )

    # Test that we can turn off the injection.
    rule_runner.set_options(["--no-python-infer-entry-points"])
    assert_injected(Address("project", target_name="first_party"), expected=None)
