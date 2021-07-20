# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent
from typing import List, Optional

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
def test_to_interpreter_version(runtime: str, expected_major: int, expected_minor: int) -> None:
    assert (expected_major, expected_minor) == PythonAwsLambdaRuntime(
        runtime, Address("", target_name="t")
    ).to_interpreter_version()


@pytest.mark.parametrize("invalid_runtime", ("python88.99", "fooobar"))
def test_runtime_validation(invalid_runtime: str) -> None:
    with pytest.raises(InvalidFieldException):
        PythonAwsLambdaRuntime(invalid_runtime, Address("", target_name="t"))


@pytest.mark.parametrize("invalid_handler", ("path.to.lambda", "lambda.py"))
def test_handler_validation(invalid_handler: str) -> None:
    with pytest.raises(InvalidFieldException):
        PythonAwsLambdaHandlerField(invalid_handler, Address("", target_name="t"))


@pytest.mark.parametrize(
    ["handler", "expected"],
    (("path.to.module:func", []), ("lambda.py:func", ["project/dir/lambda.py"])),
)
def test_handler_filespec(handler: str, expected: List[str]) -> None:
    field = PythonAwsLambdaHandlerField(handler, Address("project/dir"))
    assert field.filespec == {"includes": expected}


def test_resolve_handler(rule_runner: RuleRunner) -> None:
    def assert_resolved(handler: str, *, expected: str, is_file: bool) -> None:
        addr = Address("src/python/project")
        rule_runner.write_files(
            {"src/python/project/lambda.py": "", "src/python/project/f2.py": ""}
        )
        field = PythonAwsLambdaHandlerField(handler, addr)
        result = rule_runner.request(
            ResolvedPythonAwsHandler, [ResolvePythonAwsHandlerRequest(field)]
        )
        assert result.val == expected
        assert result.file_name_used == is_file

    assert_resolved("path.to.lambda:func", expected="path.to.lambda:func", is_file=False)
    assert_resolved("lambda.py:func", expected="project.lambda:func", is_file=True)

    with pytest.raises(ExecutionError):
        assert_resolved("doesnt_exist.py:func", expected="doesnt matter", is_file=True)
    # Resolving >1 file is an error.
    with pytest.raises(ExecutionError):
        assert_resolved("*.py:func", expected="doesnt matter", is_file=True)


def test_inject_handler_dependency(rule_runner: RuleRunner, caplog) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                python_requirement_library(
                    name='ansicolors',
                    requirements=['ansicolors'],
                    module_mapping={'ansicolors': ['colors']},
                )
                """
            ),
            "project/app.py": "",
            "project/ambiguous.py": "",
            "project/ambiguous_in_another_root.py": "",
            "project/BUILD": dedent(
                """\
                python_library(sources=['app.py'])
                python_awslambda(name='first_party', handler='project.app:func', runtime='python3.7')
                python_awslambda(name='first_party_shorthand', handler='app.py:func', runtime='python3.7')
                python_awslambda(name='third_party', handler='colors:func', runtime='python3.7')
                python_awslambda(name='unrecognized', handler='who_knows.module:func', runtime='python3.7')

                python_library(name="dep1", sources=["ambiguous.py"])
                python_library(name="dep2", sources=["ambiguous.py"])
                python_awslambda(
                    name="ambiguous",
                    handler='ambiguous.py:func',
                    runtime='python3.7',
                )
                python_awslambda(
                    name="disambiguated",
                    handler='ambiguous.py:func',
                    runtime='python3.7',
                    dependencies=["!./ambiguous.py:dep2"],
                )

                python_library(
                    name="ambiguous_in_another_root", sources=["ambiguous_in_another_root.py"]
                )
                python_awslambda(
                    name="another_root__file_used",
                    handler="ambiguous_in_another_root.py:func",
                    runtime="python3.7",
                )
                python_awslambda(
                    name="another_root__module_used",
                    handler="project.ambiguous_in_another_root:func",
                    runtime="python3.7",
                )
                """
            ),
            "src/py/project/ambiguous_in_another_root.py": "",
            "src/py/project/BUILD.py": "python_library()",
        }
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

    # Warn if there's ambiguity, meaning we cannot infer.
    caplog.clear()
    assert_injected(Address("project", target_name="ambiguous"), expected=None)
    assert len(caplog.records) == 1
    assert (
        "project:ambiguous has the field `handler='ambiguous.py:func'`, which maps to the Python "
        "module `project.ambiguous`"
    ) in caplog.text
    assert "['project/ambiguous.py:dep1', 'project/ambiguous.py:dep2']" in caplog.text

    # Test that ignores can disambiguate an otherwise ambiguous handler. Ensure we don't log a
    # warning about ambiguity.
    caplog.clear()
    assert_injected(
        Address("project", target_name="disambiguated"),
        expected=Address("project", target_name="dep1", relative_file_path="ambiguous.py"),
    )
    assert not caplog.records

    # Test that using a file path results in ignoring all targets which are not an ancestor. We can
    # do this because we know the file name must be in the current directory or subdir of the
    # `python_awslambda`.
    assert_injected(
        Address("project", target_name="another_root__file_used"),
        expected=Address(
            "project",
            target_name="ambiguous_in_another_root",
            relative_file_path="ambiguous_in_another_root.py",
        ),
    )
    caplog.clear()
    assert_injected(Address("project", target_name="another_root__module_used"), expected=None)
    assert len(caplog.records) == 1
    assert (
        "['project/ambiguous_in_another_root.py:ambiguous_in_another_root', 'src/py/project/"
        "ambiguous_in_another_root.py']"
    ) in caplog.text

    # Test that we can turn off the injection.
    rule_runner.set_options(["--no-python-infer-entry-points"])
    assert_injected(Address("project", target_name="first_party"), expected=None)
