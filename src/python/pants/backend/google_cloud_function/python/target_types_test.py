# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import re
from textwrap import dedent
from typing import List, Optional

import pytest

from pants.backend.google_cloud_function.python.target_types import (
    InferPythonCloudFunctionHandlerDependency,
    PythonCloudFunctionHandlerInferenceFieldSet,
    PythonGoogleCloudFunction,
    PythonGoogleCloudFunctionCompletePlatforms,
    PythonGoogleCloudFunctionHandlerField,
    PythonGoogleCloudFunctionRuntime,
    ResolvedPythonGoogleHandler,
    ResolvePythonGoogleHandlerRequest,
)
from pants.backend.google_cloud_function.python.target_types import rules as target_type_rules
from pants.backend.python.target_types import PythonRequirementTarget, PythonSourcesGeneratorTarget
from pants.backend.python.target_types_rules import rules as python_target_types_rules
from pants.build_graph.address import Address
from pants.core.target_types import FileTarget
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.target import InferredDependencies, InvalidFieldException
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *target_type_rules(),
            *python_target_types_rules(),
            QueryRule(ResolvedPythonGoogleHandler, [ResolvePythonGoogleHandlerRequest]),
            QueryRule(InferredDependencies, [InferPythonCloudFunctionHandlerDependency]),
        ],
        target_types=[
            FileTarget,
            PythonGoogleCloudFunction,
            PythonRequirementTarget,
            PythonSourcesGeneratorTarget,
        ],
    )


@pytest.mark.parametrize(
    ["runtime", "expected_major", "expected_minor"],
    (
        # The available runtimes at the time of writing.
        # See https://cloud.google.com/functions/docs/concepts/python-runtime.
        ["python37", 3, 7],
        ["python38", 3, 8],
        ["python39", 3, 9],
        ["python310", 3, 10],
        ["python311", 3, 11],
    ),
)
def test_to_interpreter_version(runtime: str, expected_major: int, expected_minor: int) -> None:
    assert (expected_major, expected_minor) == PythonGoogleCloudFunctionRuntime(
        runtime, Address("", target_name="t")
    ).to_interpreter_version()


@pytest.mark.parametrize("invalid_runtime", ("python88.99", "fooobar"))
def test_runtime_validation(invalid_runtime: str) -> None:
    with pytest.raises(InvalidFieldException):
        PythonGoogleCloudFunctionRuntime(invalid_runtime, Address("", target_name="t"))


@pytest.mark.parametrize("invalid_handler", ("path.to.function", "function.py"))
def test_handler_validation(invalid_handler: str) -> None:
    with pytest.raises(InvalidFieldException):
        PythonGoogleCloudFunctionHandlerField(invalid_handler, Address("", target_name="t"))


@pytest.mark.parametrize(
    ["handler", "expected"],
    (("path.to.module:func", []), ("cloud_function.py:func", ["project/dir/cloud_function.py"])),
)
def test_handler_filespec(handler: str, expected: List[str]) -> None:
    field = PythonGoogleCloudFunctionHandlerField(handler, Address("project/dir"))
    assert field.filespec == {"includes": expected}


def test_resolve_handler(rule_runner: RuleRunner) -> None:
    def assert_resolved(handler: str, *, expected: str, is_file: bool) -> None:
        addr = Address("src/python/project")
        rule_runner.write_files(
            {"src/python/project/cloud_function.py": "", "src/python/project/f2.py": ""}
        )
        field = PythonGoogleCloudFunctionHandlerField(handler, addr)
        result = rule_runner.request(
            ResolvedPythonGoogleHandler, [ResolvePythonGoogleHandlerRequest(field)]
        )
        assert result.val == expected
        assert result.file_name_used == is_file

    assert_resolved(
        "path.to.cloud_function:func", expected="path.to.cloud_function:func", is_file=False
    )
    assert_resolved("cloud_function.py:func", expected="project.cloud_function:func", is_file=True)

    with pytest.raises(ExecutionError):
        assert_resolved("doesnt_exist.py:func", expected="doesnt matter", is_file=True)
    # Resolving >1 file is an error.
    with pytest.raises(ExecutionError):
        assert_resolved("*.py:func", expected="doesnt matter", is_file=True)


def test_infer_handler_dependency(rule_runner: RuleRunner, caplog) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                python_requirement(
                    name='ansicolors',
                    requirements=['ansicolors'],
                    modules=['colors'],
                )
                """
            ),
            "project/app.py": "",
            "project/ambiguous.py": "",
            "project/ambiguous_in_another_root.py": "",
            "project/BUILD": dedent(
                """\
                python_sources(sources=['app.py'])
                python_google_cloud_function(
                    name='first_party',
                    handler='project.app:func',
                    runtime='python37',
                    type='event',
                )
                python_google_cloud_function(
                    name='first_party_shorthand',
                    handler='app.py:func',
                    runtime='python37',
                    type='event',
                )
                python_google_cloud_function(
                    name='third_party',
                    handler='colors:func',
                    runtime='python37',
                    type='event',
                )
                python_google_cloud_function(
                    name='unrecognized',
                    handler='who_knows.module:func',
                    runtime='python37',
                    type='event',
                )

                python_sources(name="dep1", sources=["ambiguous.py"])
                python_sources(name="dep2", sources=["ambiguous.py"])
                python_google_cloud_function(
                    name="ambiguous",
                    handler='ambiguous.py:func',
                    runtime='python37',
                    type='event',
                )
                python_google_cloud_function(
                    name="disambiguated",
                    handler='ambiguous.py:func',
                    runtime='python37',
                    type='event',
                    dependencies=["!./ambiguous.py:dep2"],
                )

                python_sources(
                    name="ambiguous_in_another_root", sources=["ambiguous_in_another_root.py"]
                )
                python_google_cloud_function(
                    name="another_root__file_used",
                    handler="ambiguous_in_another_root.py:func",
                    runtime="python37",
                    type="event",
                )
                python_google_cloud_function(
                    name="another_root__module_used",
                    handler="project.ambiguous_in_another_root:func",
                    runtime="python37",
                    type="event",
                )
                """
            ),
            "src/py/project/ambiguous_in_another_root.py": "",
            "src/py/project/BUILD.py": "python_sources()",
        }
    )

    def assert_inferred(address: Address, *, expected: Optional[Address]) -> None:
        tgt = rule_runner.get_target(address)
        inferred = rule_runner.request(
            InferredDependencies,
            [
                InferPythonCloudFunctionHandlerDependency(
                    PythonCloudFunctionHandlerInferenceFieldSet.create(tgt)
                )
            ],
        )
        assert inferred == InferredDependencies([expected] if expected else [])

    assert_inferred(
        Address("project", target_name="first_party"),
        expected=Address("project", relative_file_path="app.py"),
    )
    assert_inferred(
        Address("project", target_name="first_party_shorthand"),
        expected=Address("project", relative_file_path="app.py"),
    )
    assert_inferred(
        Address("project", target_name="third_party"),
        expected=Address("", target_name="ansicolors"),
    )
    assert_inferred(Address("project", target_name="unrecognized"), expected=None)

    # Warn if there's ambiguity, meaning we cannot infer.
    caplog.clear()
    assert_inferred(Address("project", target_name="ambiguous"), expected=None)
    assert len(caplog.records) == 1
    assert (
        "project:ambiguous has the field `handler='ambiguous.py:func'`, which maps to the Python "
        "module `project.ambiguous`"
    ) in caplog.text
    assert "['project/ambiguous.py:dep1', 'project/ambiguous.py:dep2']" in caplog.text

    # Test that ignores can disambiguate an otherwise ambiguous handler. Ensure we don't log a
    # warning about ambiguity.
    caplog.clear()
    assert_inferred(
        Address("project", target_name="disambiguated"),
        expected=Address("project", target_name="dep1", relative_file_path="ambiguous.py"),
    )
    assert not caplog.records

    # Test that using a file path results in ignoring all targets which are not an ancestor. We can
    # do this because we know the file name must be in the current directory or subdir of the
    # `python_google_cloud_function`.
    assert_inferred(
        Address("project", target_name="another_root__file_used"),
        expected=Address(
            "project",
            target_name="ambiguous_in_another_root",
            relative_file_path="ambiguous_in_another_root.py",
        ),
    )
    caplog.clear()
    assert_inferred(Address("project", target_name="another_root__module_used"), expected=None)
    assert len(caplog.records) == 1
    assert (
        "['project/ambiguous_in_another_root.py:ambiguous_in_another_root', 'src/py/project/"
        "ambiguous_in_another_root.py']"
    ) in caplog.text

    # Test that we can turn off the inference.
    rule_runner.set_options(["--no-python-infer-entry-points"])
    assert_inferred(Address("project", target_name="first_party"), expected=None)


def test_at_least_one_target_platform(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "project/app.py": "",
            "project/platform-py37.json": "",
            "project/BUILD": dedent(
                """\
                python_google_cloud_function(
                    name='runtime',
                    handler='project.app:func',
                    runtime='python37',
                    type='event',
                )
                file(name="python37", source="platform-py37.json")
                python_google_cloud_function(
                    name='complete_platforms',
                    handler='project.app:func',
                    complete_platforms=[':python37'],
                    type='event',
                )
                python_google_cloud_function(
                    name='both',
                    handler='project.app:func',
                    runtime='python37',
                    complete_platforms=[':python37'],
                    type='event',
                )
                python_google_cloud_function(
                    name='neither',
                    handler='project.app:func',
                    type='event',
                )
                """
            ),
        }
    )

    runtime = rule_runner.get_target(Address("project", target_name="runtime"))
    assert "python37" == runtime[PythonGoogleCloudFunctionRuntime].value
    assert runtime[PythonGoogleCloudFunctionCompletePlatforms].value is None

    complete_platforms = rule_runner.get_target(
        Address("project", target_name="complete_platforms")
    )
    assert complete_platforms[PythonGoogleCloudFunctionRuntime].value is None
    assert (":python37",) == complete_platforms[PythonGoogleCloudFunctionCompletePlatforms].value

    both = rule_runner.get_target(Address("project", target_name="both"))
    assert "python37" == both[PythonGoogleCloudFunctionRuntime].value
    assert (":python37",) == both[PythonGoogleCloudFunctionCompletePlatforms].value

    with pytest.raises(
        ExecutionError,
        match=r".*{}.*".format(
            re.escape(
                "InvalidTargetException: The `python_google_cloud_function` target project:neither "
                "must specify either a `runtime` or `complete_platforms` or both."
            )
        ),
    ):
        rule_runner.get_target(Address("project", target_name="neither"))
