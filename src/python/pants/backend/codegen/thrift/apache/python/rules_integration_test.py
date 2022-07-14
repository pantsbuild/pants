# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.codegen.thrift.apache.python import additional_fields
from pants.backend.codegen.thrift.apache.python.rules import (
    ApacheThriftPythonDependenciesInferenceFieldSet,
    GeneratePythonFromThriftRequest,
    InferApacheThriftPythonDependencies,
)
from pants.backend.codegen.thrift.apache.python.rules import rules as apache_thrift_python_rules
from pants.backend.codegen.thrift.apache.rules import rules as apache_thrift_rules
from pants.backend.codegen.thrift.rules import rules as thrift_rules
from pants.backend.codegen.thrift.target_types import (
    ThriftSourceField,
    ThriftSourcesGeneratorTarget,
)
from pants.backend.codegen.utils import (
    AmbiguousPythonCodegenRuntimeLibrary,
    MissingPythonCodegenRuntimeLibrary,
)
from pants.backend.python.dependency_inference import module_mapper
from pants.backend.python.target_types import PythonRequirementTarget
from pants.build_graph.address import Address
from pants.core.util_rules import source_files, stripped_source_files
from pants.engine.internals import graph
from pants.engine.rules import QueryRule
from pants.engine.target import (
    GeneratedSources,
    HydratedSources,
    HydrateSourcesRequest,
    InferredDependencies,
)
from pants.source import source_root
from pants.testutil.rule_runner import RuleRunner, engine_error
from pants.testutil.skip_utils import requires_thrift


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *thrift_rules(),
            *apache_thrift_rules(),
            *apache_thrift_python_rules(),
            *source_files.rules(),
            *source_root.rules(),
            *graph.rules(),
            *stripped_source_files.rules(),
            *module_mapper.rules(),
            *additional_fields.rules(),
            QueryRule(HydratedSources, [HydrateSourcesRequest]),
            QueryRule(GeneratedSources, [GeneratePythonFromThriftRequest]),
        ],
        target_types=[ThriftSourcesGeneratorTarget, PythonRequirementTarget],
    )


def assert_files_generated(
    rule_runner: RuleRunner,
    address: Address,
    *,
    expected_files: list[str],
    source_roots: list[str],
    extra_args: list[str] | None = None,
) -> None:
    args = [
        f"--source-root-patterns={repr(source_roots)}",
        "--no-python-thrift-infer-runtime-dependency",
        *(extra_args or ()),
    ]
    rule_runner.set_options(args, env_inherit={"PATH", "PYENV_ROOT", "HOME"})
    tgt = rule_runner.get_target(address)
    thrift_sources = rule_runner.request(
        HydratedSources, [HydrateSourcesRequest(tgt[ThriftSourceField])]
    )
    generated_sources = rule_runner.request(
        GeneratedSources,
        [GeneratePythonFromThriftRequest(thrift_sources.snapshot, tgt)],
    )
    assert set(generated_sources.snapshot.files) == set(expected_files)


@requires_thrift
def test_generates_python(rule_runner: RuleRunner) -> None:
    # This tests a few things:
    #  * We generate the correct file names, keeping into account `namespace`. Note that if
    #    `namespace` is not set, then Thrift will drop all parent directories, all we do is
    #    restore the source root.
    #  * Thrift files can import other thrift files, and those can import others
    #    (transitive dependencies). We'll only generate the requested target, though.
    #  * We can handle multiple source roots, which need to be preserved in the final output.
    rule_runner.write_files(
        {
            "src/thrift/dir1/f.thrift": "",
            "src/thrift/dir1/BUILD": "thrift_sources()",
            "src/thrift/dir2/f.thrift": dedent(
                """\
                include "dir1/f.thrift"
                namespace py custom_namespace.module
                """
            ),
            "src/thrift/dir2/BUILD": "thrift_sources(dependencies=['src/thrift/dir1'])",
            # Test another source root.
            "tests/thrift/test_thrifts/f.thrift": 'include "dir2/f.thrift"',
            "tests/thrift/test_thrifts/BUILD": "thrift_sources(dependencies=['src/thrift/dir2'])",
        }
    )

    def assert_gen(addr: Address, expected: list[str]) -> None:
        assert_files_generated(
            rule_runner,
            addr,
            source_roots=["/src/thrift", "/tests/thrift"],
            expected_files=expected,
        )

    assert_gen(
        Address("src/thrift/dir1", relative_file_path="f.thrift"),
        [
            "src/thrift/__init__.py",
            "src/thrift/f/__init__.py",
            "src/thrift/f/constants.py",
            "src/thrift/f/ttypes.py",
        ],
    )
    assert_gen(
        Address("src/thrift/dir2", relative_file_path="f.thrift"),
        [
            "src/thrift/__init__.py",
            "src/thrift/custom_namespace/__init__.py",
            "src/thrift/custom_namespace/module/__init__.py",
            "src/thrift/custom_namespace/module/constants.py",
            "src/thrift/custom_namespace/module/ttypes.py",
        ],
    )
    assert_gen(
        Address("tests/thrift/test_thrifts", relative_file_path="f.thrift"),
        [
            "tests/thrift/__init__.py",
            "tests/thrift/f/__init__.py",
            "tests/thrift/f/constants.py",
            "tests/thrift/f/ttypes.py",
        ],
    )


@requires_thrift
def test_top_level_source_root(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "codegen/dir/f.thrift": "",
            "codegen/dir/f2.thrift": "namespace py custom_namespace.module",
            "codegen/dir/BUILD": "thrift_sources()",
        }
    )
    assert_files_generated(
        rule_runner,
        Address("codegen/dir", relative_file_path="f.thrift"),
        source_roots=["/"],
        expected_files=[
            "__init__.py",
            "f/__init__.py",
            "f/constants.py",
            "f/ttypes.py",
        ],
    )
    assert_files_generated(
        rule_runner,
        Address("codegen/dir", relative_file_path="f2.thrift"),
        source_roots=["/"],
        expected_files=[
            "__init__.py",
            "custom_namespace/__init__.py",
            "custom_namespace/module/__init__.py",
            "custom_namespace/module/constants.py",
            "custom_namespace/module/ttypes.py",
        ],
    )


def test_find_thrift_python_requirement(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"codegen/dir/f.thrift": "", "codegen/dir/BUILD": "thrift_sources()"})
    rule_runner.set_options(
        ["--python-resolves={'python-default': '', 'another': ''}", "--python-enable-resolves"]
    )
    thrift_tgt = rule_runner.get_target(Address("codegen/dir", relative_file_path="f.thrift"))
    request = InferApacheThriftPythonDependencies(
        ApacheThriftPythonDependenciesInferenceFieldSet.create(thrift_tgt)
    )

    # Start with no relevant requirements.
    with engine_error(MissingPythonCodegenRuntimeLibrary):
        rule_runner.request(InferredDependencies, [request])

    # If exactly one, match it.
    rule_runner.write_files({"reqs1/BUILD": "python_requirement(requirements=['thrift'])"})
    assert rule_runner.request(InferredDependencies, [request]) == InferredDependencies(
        [Address("reqs1")]
    )

    # Multiple is fine if from other resolve.
    rule_runner.write_files(
        {"another_resolve/BUILD": "python_requirement(requirements=['thrift'], resolve='another')"}
    )
    assert rule_runner.request(InferredDependencies, [request]) == InferredDependencies(
        [Address("reqs1")]
    )

    # If multiple from the same resolve, error.
    rule_runner.write_files({"reqs2/BUILD": "python_requirement(requirements=['thrift'])"})
    with engine_error(
        AmbiguousPythonCodegenRuntimeLibrary, contains="['reqs1:reqs1', 'reqs2:reqs2']"
    ):
        rule_runner.request(InferredDependencies, [request])
