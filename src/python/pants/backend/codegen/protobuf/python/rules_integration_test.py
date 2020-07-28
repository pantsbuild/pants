# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent
from typing import List

from pants.backend.codegen.protobuf.python.rules import GeneratePythonFromProtobufRequest
from pants.backend.codegen.protobuf.python.rules import rules as protobuf_rules
from pants.backend.codegen.protobuf.target_types import ProtobufLibrary, ProtobufSources
from pants.core.util_rules import archive, determine_source_files, external_tool
from pants.engine.addresses import Address
from pants.engine.rules import RootRule
from pants.engine.selectors import Params
from pants.engine.target import (
    GeneratedSources,
    HydratedSources,
    HydrateSourcesRequest,
    WrappedTarget,
)
from pants.testutil.option.util import create_options_bootstrapper
from pants.testutil.test_base import TestBase


class ProtobufPythonIntegrationTest(TestBase):
    @classmethod
    def target_types(cls):
        return [ProtobufLibrary]

    @classmethod
    def rules(cls):
        return (
            *super().rules(),
            *protobuf_rules(),
            *archive.rules(),
            *determine_source_files.rules(),
            *external_tool.rules(),
            RootRule(GeneratePythonFromProtobufRequest),
        )

    def assert_files_generated(
        self, spec: str, *, expected_files: List[str], source_roots: List[str]
    ) -> None:
        tgt = self.request_single_product(WrappedTarget, Address.parse(spec)).target
        protocol_sources = self.request_single_product(
            HydratedSources,
            Params(HydrateSourcesRequest(tgt[ProtobufSources]), create_options_bootstrapper()),
        )
        generated_sources = self.request_single_product(
            GeneratedSources,
            Params(
                GeneratePythonFromProtobufRequest(protocol_sources.snapshot, tgt),
                create_options_bootstrapper(
                    args=[
                        "--backend-packages=pants.backend.codegen.protobuf.python",
                        f"--source-root-patterns={repr(source_roots)}",
                    ]
                ),
            ),
        )
        assert set(generated_sources.snapshot.files) == set(expected_files)

    def test_generates_python(self) -> None:
        # This tests a few things:
        #  * We generate the correct file names.
        #  * Protobuf files can import other protobuf files, and those can import others
        #    (transitive dependencies). We'll only generate the requested target, though.
        #  * We can handle multiple source roots, which need to be preserved in the final output.

        self.create_file(
            "src/protobuf/dir1/f.proto",
            dedent(
                """\
                syntax = "proto2";

                package dir1;

                message Person {
                  required string name = 1;
                  required int32 id = 2;
                  optional string email = 3;
                }
                """
            ),
        )
        self.create_file(
            "src/protobuf/dir1/f2.proto",
            dedent(
                """\
                syntax = "proto2";

                package dir1;
                """
            ),
        )
        self.add_to_build_file("src/protobuf/dir1", "protobuf_library()")

        self.create_file(
            "src/protobuf/dir2/f.proto",
            dedent(
                """\
                syntax = "proto2";

                package dir2;

                import "dir1/f.proto";
                """
            ),
        )
        self.add_to_build_file(
            "src/protobuf/dir2", "protobuf_library(dependencies=['src/protobuf/dir1'])"
        )

        # Test another source root.
        self.create_file(
            "tests/protobuf/test_protos/f.proto",
            dedent(
                """\
                syntax = "proto2";

                package test_protos;

                import "dir2/f.proto";
                """
            ),
        )
        self.add_to_build_file(
            "tests/protobuf/test_protos", "protobuf_library(dependencies=['src/protobuf/dir2'])"
        )

        source_roots = ["/src/protobuf", "/tests/protobuf"]
        self.assert_files_generated(
            "src/protobuf/dir1",
            source_roots=source_roots,
            expected_files=["src/protobuf/dir1/f_pb2.py", "src/protobuf/dir1/f2_pb2.py"],
        )
        self.assert_files_generated(
            "src/protobuf/dir2",
            source_roots=source_roots,
            expected_files=["src/protobuf/dir2/f_pb2.py"],
        )
        self.assert_files_generated(
            "tests/protobuf/test_protos",
            source_roots=source_roots,
            expected_files=["tests/protobuf/test_protos/f_pb2.py"],
        )

    def test_top_level_source_root(self) -> None:
        self.create_file(
            "protos/f.proto",
            dedent(
                """\
                syntax = "proto2";

                package protos;
                """
            ),
        )
        self.add_to_build_file("protos", "protobuf_library()")
        self.assert_files_generated(
            "protos", source_roots=["/"], expected_files=["protos/f_pb2.py"]
        )
