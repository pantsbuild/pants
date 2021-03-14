# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent
from typing import Iterable, List, Type

import pytest

from pants.backend.codegen.protobuf.python import additional_fields
from pants.backend.codegen.protobuf.python.rules import rules as protobuf_rules
from pants.backend.codegen.protobuf.target_types import ProtobufLibrary
from pants.backend.python.target_types import PythonSources
from pants.backend.python.util_rules.python_sources import (
    PythonSourceFiles,
    PythonSourceFilesRequest,
    StrippedPythonSourceFiles,
)
from pants.backend.python.util_rules.python_sources import rules as python_sources_rules
from pants.core.target_types import Files, Resources
from pants.engine.addresses import Address
from pants.engine.target import Sources, Target
from pants.testutil.rule_runner import QueryRule, RuleRunner


class PythonTarget(Target):
    alias = "python_target"
    core_fields = (PythonSources,)


class NonPythonTarget(Target):
    alias = "non_python_target"
    core_fields = (Sources,)


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *python_sources_rules(),
            *additional_fields.rules(),
            *protobuf_rules(),
            QueryRule(PythonSourceFiles, [PythonSourceFilesRequest]),
            QueryRule(StrippedPythonSourceFiles, [PythonSourceFilesRequest]),
        ],
        target_types=[PythonTarget, NonPythonTarget, ProtobufLibrary],
    )


def create_target(
    rule_runner: RuleRunner,
    *,
    parent_directory: str,
    files: List[str],
    target_cls: Type[Target] = PythonTarget,
) -> Target:
    rule_runner.create_files(parent_directory, files=files)
    address = Address(spec_path=parent_directory, target_name="target")
    return target_cls({Sources.alias: files}, address=address)


def get_stripped_sources(
    rule_runner: RuleRunner,
    targets: Iterable[Target],
    *,
    include_resources: bool = True,
    include_files: bool = False,
    source_roots: list[str] | None = None,
    extra_args: list[str] | None = None,
) -> StrippedPythonSourceFiles:
    rule_runner.set_options(
        [
            "--backend-packages=pants.backend.python",
            f"--source-root-patterns={source_roots or ['src/python']}",
            *(extra_args or []),
        ]
    )
    return rule_runner.request(
        StrippedPythonSourceFiles,
        [
            PythonSourceFilesRequest(
                targets, include_resources=include_resources, include_files=include_files
            )
        ],
    )


def get_unstripped_sources(
    rule_runner: RuleRunner,
    targets: Iterable[Target],
    *,
    include_resources: bool = True,
    include_files: bool = False,
    source_roots: list[str] | None = None,
    extra_args: list[str] | None = None,
) -> PythonSourceFiles:
    rule_runner.set_options(
        [
            "--backend-packages=pants.backend.python",
            f"--source-root-patterns={source_roots or ['src/python']}",
            *(extra_args or []),
        ]
    )
    return rule_runner.request(
        PythonSourceFiles,
        [
            PythonSourceFilesRequest(
                targets, include_resources=include_resources, include_files=include_files
            )
        ],
    )


def test_filters_out_irrelevant_targets(rule_runner: RuleRunner) -> None:
    targets = [
        create_target(
            rule_runner, parent_directory="src/python", files=["p.py"], target_cls=PythonTarget
        ),
        create_target(
            rule_runner, parent_directory="src/python", files=["f.txt"], target_cls=Files
        ),
        create_target(
            rule_runner, parent_directory="src/python", files=["r.txt"], target_cls=Resources
        ),
        create_target(
            rule_runner, parent_directory="src/python", files=["j.java"], target_cls=NonPythonTarget
        ),
    ]

    def assert_stripped(
        *,
        include_resources: bool,
        include_files: bool,
        expected: List[str],
    ) -> None:
        result = get_stripped_sources(
            rule_runner, targets, include_resources=include_resources, include_files=include_files
        )
        assert result.stripped_source_files.snapshot.files == tuple(expected)

    def assert_unstripped(
        *, include_resources: bool, include_files: bool, expected: List[str]
    ) -> None:
        result = get_unstripped_sources(
            rule_runner, targets, include_resources=include_resources, include_files=include_files
        )
        assert result.source_files.snapshot.files == tuple(expected)
        assert result.source_roots == ("src/python",)

    assert_stripped(
        include_resources=True,
        include_files=True,
        expected=["p.py", "r.txt", "src/python/f.txt"],
    )
    assert_unstripped(
        include_resources=True,
        include_files=True,
        expected=["src/python/f.txt", "src/python/p.py", "src/python/r.txt"],
    )

    assert_stripped(include_resources=True, include_files=False, expected=["p.py", "r.txt"])
    assert_unstripped(
        include_resources=True,
        include_files=False,
        expected=["src/python/p.py", "src/python/r.txt"],
    )

    assert_stripped(
        include_resources=False, include_files=True, expected=["p.py", "src/python/f.txt"]
    )
    assert_unstripped(
        include_resources=False,
        include_files=True,
        expected=["src/python/f.txt", "src/python/p.py"],
    )

    assert_stripped(include_resources=False, include_files=False, expected=["p.py"])
    assert_unstripped(
        include_resources=False,
        include_files=False,
        expected=["src/python/p.py"],
    )


def test_top_level_source_root(rule_runner: RuleRunner) -> None:
    targets = [create_target(rule_runner, parent_directory="", files=["f1.py", "f2.py"])]

    stripped_result = get_stripped_sources(rule_runner, targets, source_roots=["/"])
    assert stripped_result.stripped_source_files.snapshot.files == ("f1.py", "f2.py")

    unstripped_result = get_unstripped_sources(rule_runner, targets, source_roots=["/"])
    assert unstripped_result.source_files.snapshot.files == ("f1.py", "f2.py")
    assert unstripped_result.source_roots == (".",)


def test_files_not_used_for_source_roots(rule_runner: RuleRunner) -> None:
    targets = [
        create_target(
            rule_runner, parent_directory="src/py", files=["f.py"], target_cls=PythonTarget
        ),
        create_target(rule_runner, parent_directory="src/files", files=["f.txt"], target_cls=Files),
    ]
    assert get_unstripped_sources(
        rule_runner, targets, include_files=True, source_roots=["src/py", "src/files"]
    ).source_roots == ("src/py",)


def test_python_protobuf(rule_runner: RuleRunner) -> None:
    rule_runner.create_file(
        "src/protobuf/dir/f.proto",
        dedent(
            """\
            syntax = "proto2";

            package dir;
            """
        ),
    )
    rule_runner.create_file(
        "src/protobuf/other_dir/f.proto",
        dedent(
            """\
            syntax = "proto2";

            package other_dir;
            """
        ),
    )
    rule_runner.add_to_build_file("src/protobuf/dir", "protobuf_library()")
    rule_runner.add_to_build_file(
        "src/protobuf/other_dir", "protobuf_library(python_source_root='src/python')"
    )
    targets = [
        ProtobufLibrary({}, address=Address("src/protobuf/dir")),
        ProtobufLibrary({}, address=Address("src/protobuf/other_dir")),
    ]
    backend_args = ["--backend-packages=pants.backend.codegen.protobuf.python"]

    stripped_result = get_stripped_sources(
        rule_runner, targets, source_roots=["src/protobuf", "src/python"], extra_args=backend_args
    )
    assert stripped_result.stripped_source_files.snapshot.files == (
        "dir/f_pb2.py",
        "other_dir/f_pb2.py",
    )

    unstripped_result = get_unstripped_sources(
        rule_runner, targets, source_roots=["src/protobuf", "src/python"], extra_args=backend_args
    )
    assert unstripped_result.source_files.snapshot.files == (
        "src/protobuf/dir/f_pb2.py",
        "src/python/other_dir/f_pb2.py",
    )
    assert unstripped_result.source_roots == ("src/protobuf", "src/python")
