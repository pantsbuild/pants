# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from textwrap import dedent
from typing import List, Optional

import pytest

from pants.backend.awslambda.python.target_types import rules as target_type_rules
from pants.backend.python.target_types import (
    PythonRequirementTarget,
    PythonResolveField,
    PythonSourcesGeneratorTarget,
)
from pants.backend.python.target_types_rules import rules as python_target_types_rules
from pants.backend.python.util_rules.faas import (
    InferPythonFaaSHandlerDependency,
    KnownRuntimeCompletePlatformRequest,
    PythonFaaSDependencies,
    PythonFaaSHandlerField,
    PythonFaaSHandlerInferenceFieldSet,
    PythonFaaSKnownRuntime,
    PythonFaaSRuntimeField,
    ResolvedPythonFaaSHandler,
    ResolvePythonFaaSHandlerRequest,
)
from pants.backend.python.util_rules.pex import CompletePlatforms, PexPlatforms
from pants.build_graph.address import Address
from pants.core.target_types import FileTarget
from pants.engine.target import InferredDependencies, InvalidFieldException, Target
from pants.testutil.rule_runner import QueryRule, RuleRunner, engine_error
from pants.util.strutil import softwrap


class MockFaaS(Target):
    alias = "mock_faas"
    core_fields = (PythonFaaSDependencies, PythonFaaSHandlerField, PythonResolveField)


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *target_type_rules(),
            *python_target_types_rules(),
            QueryRule(ResolvedPythonFaaSHandler, [ResolvePythonFaaSHandlerRequest]),
            QueryRule(InferredDependencies, [InferPythonFaaSHandlerDependency]),
            QueryRule(CompletePlatforms, [KnownRuntimeCompletePlatformRequest]),
        ],
        target_types=[
            FileTarget,
            MockFaaS,
            PythonRequirementTarget,
            PythonSourcesGeneratorTarget,
        ],
    )


@pytest.mark.parametrize("invalid_handler", ("path.to.lambda", "lambda.py"))
def test_handler_validation(invalid_handler: str) -> None:
    with pytest.raises(InvalidFieldException):
        PythonFaaSHandlerField(invalid_handler, Address("", target_name="t"))


@pytest.mark.parametrize(
    ["handler", "expected"],
    (("path.to.module:func", []), ("lambda.py:func", ["project/dir/lambda.py"])),
)
def test_handler_filespec(handler: str, expected: List[str]) -> None:
    field = PythonFaaSHandlerField(handler, Address("project/dir"))
    assert field.filespec == {"includes": expected}


def test_resolve_handler(rule_runner: RuleRunner) -> None:
    def assert_resolved(
        handler: str, *, expected_module: str, expected_func: str, is_file: bool
    ) -> None:
        addr = Address("src/python/project")
        rule_runner.write_files(
            {"src/python/project/lambda.py": "", "src/python/project/f2.py": ""}
        )
        field = PythonFaaSHandlerField(handler, addr)
        result = rule_runner.request(
            ResolvedPythonFaaSHandler, [ResolvePythonFaaSHandlerRequest(field)]
        )
        assert result.module == expected_module
        assert result.func == expected_func
        assert result.file_name_used == is_file

    assert_resolved(
        "path.to.lambda:func", expected_module="path.to.lambda", expected_func="func", is_file=False
    )
    assert_resolved(
        "lambda.py:func", expected_module="project.lambda", expected_func="func", is_file=True
    )

    with engine_error(contains="Unmatched glob"):
        assert_resolved(
            "doesnt_exist.py:func", expected_module="doesnt matter", expected_func="", is_file=True
        )
    # Resolving >1 file is an error.
    with engine_error(InvalidFieldException):
        assert_resolved(
            "*.py:func", expected_module="doesnt matter", expected_func="", is_file=True
        )


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
                mock_faas(name='first_party', handler='project.app:func')
                mock_faas(name='first_party_shorthand', handler='app.py:func')
                mock_faas(name='third_party', handler='colors:func')
                mock_faas(name='unrecognized', handler='who_knows.module:func')

                python_sources(name="dep1", sources=["ambiguous.py"])
                python_sources(name="dep2", sources=["ambiguous.py"])
                mock_faas(
                    name="ambiguous",
                    handler='ambiguous.py:func',
                )
                mock_faas(
                    name="disambiguated",
                    handler='ambiguous.py:func',
                    dependencies=["!./ambiguous.py:dep2"],
                )

                python_sources(
                    name="ambiguous_in_another_root", sources=["ambiguous_in_another_root.py"]
                )
                mock_faas(
                    name="another_root__file_used",
                    handler="ambiguous_in_another_root.py:func",
                )
                mock_faas(
                    name="another_root__module_used",
                    handler="project.ambiguous_in_another_root:func",
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
            [InferPythonFaaSHandlerDependency(PythonFaaSHandlerInferenceFieldSet.create(tgt))],
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
        softwrap(
            """
            project:ambiguous has the field `handler='ambiguous.py:func'`, which maps to the Python
            module `project.ambiguous`
            """
        )
        in caplog.text
    )
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
    # `python_aws_lambda_function`.
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
        softwrap(
            """
            ['project/ambiguous_in_another_root.py:ambiguous_in_another_root',
            'src/py/project/ambiguous_in_another_root.py']
            """
        )
        in caplog.text
    )

    # Test that we can turn off the inference.
    rule_runner.set_options(["--no-python-infer-entry-points"])
    assert_inferred(Address("project", target_name="first_party"), expected=None)


class TestRuntimeField(PythonFaaSRuntimeField):
    known_runtimes = (
        PythonFaaSKnownRuntime(12, 34, tag="12-34-tag"),
        PythonFaaSKnownRuntime(56, 78, tag="56-78-tag"),
    )
    known_runtimes_docker_repo = ""

    def to_interpreter_version(self) -> None | tuple[int, int]:
        if self.value is None:
            return None

        first, second = self.value.split(".")
        return int(first), int(second)


@pytest.mark.parametrize(
    ("value", "expected_platforms", "expected_file_name"),
    [
        pytest.param(None, [], (None), id="empty"),
        pytest.param("12.34", [], ("complete_platform_12-34-tag.json"), id="known 12.34"),
        pytest.param("56.78", [], ("complete_platform_56-78-tag.json"), id="known 56.78"),
        pytest.param("98.76", ["linux_x86_64-cp-9876-cp9876"], (None), id="known 56.78"),
    ],
)
def test_runtime_to_platform_args(
    value: str | None, expected_platforms: list[str], expected_file_name: None | str
) -> None:
    expected_request = KnownRuntimeCompletePlatformRequest(
        module="pants.backend.python.util_rules", file_name=expected_file_name
    )

    address = Address("path", target_name="target")
    field = TestRuntimeField(value, address)

    platforms, request = field.to_platform_args()

    assert platforms == PexPlatforms(expected_platforms)
    assert request == expected_request


@pytest.mark.parametrize(
    "file_name",
    [None, "complete_platform_faas-test.json"],
)
def test_known_runtime_complete_platform_rule(
    file_name: None | str, rule_runner: RuleRunner
) -> None:
    request = KnownRuntimeCompletePlatformRequest(
        module="pants.backend.python.util_rules", file_name=file_name
    )

    cp = rule_runner.request(CompletePlatforms, [request])

    if file_name is None:
        assert cp == CompletePlatforms()
    else:
        assert cp == CompletePlatforms([file_name])
