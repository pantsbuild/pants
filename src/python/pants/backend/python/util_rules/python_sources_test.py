# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent
from typing import Iterable, List, Optional, Type

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
from pants.testutil.external_tool_test_base import ExternalToolTestBase
from pants.testutil.option_util import create_options_bootstrapper
from pants.testutil.rule_runner import QueryRule


class PythonTarget(Target):
    alias = "python_target"
    core_fields = (PythonSources,)


class NonPythonTarget(Target):
    alias = "non_python_target"
    core_fields = (Sources,)


class PythonSourceFilesTest(ExternalToolTestBase):
    @classmethod
    def rules(cls):
        return (
            *super().rules(),
            *python_sources_rules(),
            *protobuf_rules(),
            QueryRule(PythonSourceFiles, (PythonSourceFilesRequest,)),
            QueryRule(StrippedPythonSourceFiles, (PythonSourceFilesRequest,)),
        )

    @classmethod
    def target_types(cls):
        return [PythonTarget, NonPythonTarget, ProtobufLibrary]

    def create_target(
        self, *, parent_directory: str, files: List[str], target_cls: Type[Target] = PythonTarget
    ) -> Target:
        self.create_files(parent_directory, files=files)
        address = Address(spec_path=parent_directory, target_name="target")
        return target_cls({Sources.alias: files}, address=address)

    def get_stripped_sources(
        self,
        targets: Iterable[Target],
        *,
        include_resources: bool = True,
        include_files: bool = False,
        source_roots: Optional[List[str]] = None,
        extra_args: Optional[List[str]] = None,
    ) -> StrippedPythonSourceFiles:
        return self.request(
            StrippedPythonSourceFiles,
            [
                PythonSourceFilesRequest(
                    targets, include_resources=include_resources, include_files=include_files
                ),
                create_options_bootstrapper(
                    args=[
                        "--backend-packages=pants.backend.python",
                        f"--source-root-patterns={source_roots or ['src/python']}",
                        *(extra_args or []),
                    ]
                ),
            ],
        )

    def get_unstripped_sources(
        self,
        targets: Iterable[Target],
        *,
        include_resources: bool = True,
        include_files: bool = False,
        source_roots: Optional[List[str]] = None,
        extra_args: Optional[List[str]] = None,
    ) -> PythonSourceFiles:
        return self.request(
            PythonSourceFiles,
            [
                PythonSourceFilesRequest(
                    targets, include_resources=include_resources, include_files=include_files
                ),
                create_options_bootstrapper(
                    args=[
                        "--backend-packages=pants.backend.python",
                        f"--source-root-patterns={source_roots or ['src/python']}",
                        *(extra_args or []),
                    ]
                ),
            ],
        )

    def test_filters_out_irrelevant_targets(self) -> None:
        targets = [
            self.create_target(
                parent_directory="src/python", files=["p.py"], target_cls=PythonTarget
            ),
            self.create_target(parent_directory="src/python", files=["f.txt"], target_cls=Files),
            self.create_target(
                parent_directory="src/python", files=["r.txt"], target_cls=Resources
            ),
            self.create_target(
                parent_directory="src/python", files=["j.java"], target_cls=NonPythonTarget
            ),
        ]

        def assert_stripped(
            *,
            include_resources: bool,
            include_files: bool,
            expected: List[str],
        ) -> None:
            result = self.get_stripped_sources(
                targets, include_resources=include_resources, include_files=include_files
            )
            assert result.stripped_source_files.snapshot.files == tuple(expected)

        def assert_unstripped(
            *, include_resources: bool, include_files: bool, expected: List[str]
        ) -> None:
            result = self.get_unstripped_sources(
                targets, include_resources=include_resources, include_files=include_files
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

    def test_top_level_source_root(self) -> None:
        targets = [self.create_target(parent_directory="", files=["f1.py", "f2.py"])]

        stripped_result = self.get_stripped_sources(targets, source_roots=["/"])
        assert stripped_result.stripped_source_files.snapshot.files == ("f1.py", "f2.py")

        unstripped_result = self.get_unstripped_sources(targets, source_roots=["/"])
        assert unstripped_result.source_files.snapshot.files == ("f1.py", "f2.py")
        assert unstripped_result.source_roots == (".",)

    def test_files_not_used_for_source_roots(self) -> None:
        targets = [
            self.create_target(parent_directory="src/py", files=["f.py"], target_cls=PythonTarget),
            self.create_target(parent_directory="src/files", files=["f.txt"], target_cls=Files),
        ]
        assert self.get_unstripped_sources(
            targets, include_files=True, source_roots=["src/py", "src/files"]
        ).source_roots == ("src/py",)

    def test_python_protobuf(self) -> None:
        self.create_file(
            "src/protobuf/dir/f.proto",
            dedent(
                """\
                syntax = "proto2";

                package dir;
                """
            ),
        )
        self.add_to_build_file("src/protobuf/dir", "protobuf_library()")
        targets = [ProtobufLibrary({}, address=Address("src/protobuf/dir"))]
        backend_args = ["--backend-packages=pants.backend.codegen.protobuf.python"]

        stripped_result = self.get_stripped_sources(
            targets, source_roots=["src/protobuf"], extra_args=backend_args
        )
        assert stripped_result.stripped_source_files.snapshot.files == ("dir/f_pb2.py",)

        unstripped_result = self.get_unstripped_sources(
            targets, source_roots=["src/protobuf"], extra_args=backend_args
        )
        assert unstripped_result.source_files.snapshot.files == ("src/protobuf/dir/f_pb2.py",)
        assert unstripped_result.source_roots == ("src/protobuf",)
