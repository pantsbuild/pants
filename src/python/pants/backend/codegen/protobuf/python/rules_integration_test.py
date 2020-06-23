# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent
from typing import List

from pants.backend.codegen.protobuf.python.rules import GeneratePythonFromProtobufRequest
from pants.backend.codegen.protobuf.python.rules import rules as protobuf_rules
from pants.backend.codegen.protobuf.target_types import ProtobufLibrary, ProtobufSources
from pants.core.util_rules import determine_source_files
from pants.engine.addresses import Address
from pants.engine.rules import RootRule
from pants.engine.selectors import Params
from pants.engine.target import (
    GeneratedSources,
    HydratedSources,
    HydrateSourcesRequest,
    WrappedTarget,
)
from pants.testutil.external_tool_test_base import ExternalToolTestBase
from pants.testutil.option.util import create_options_bootstrapper


class ProtobufPythonIntegrationTest(ExternalToolTestBase):
    @classmethod
    def target_types(cls):
        return [ProtobufLibrary]

    @classmethod
    def rules(cls):
        return (
            *super().rules(),
            *protobuf_rules(),
            *determine_source_files.rules(),
            RootRule(GeneratePythonFromProtobufRequest),
        )

    def test_generates_python(self) -> None:
        # This tests a few things:
        #  * We generate the correct file names.
        #  * Protobuf files can import other protobuf files, and those can import others
        #    (transitive dependencies). We'll only generate the requested target, though.
        #  * We can handle multiple source roots, which need to be stripped in the final output.

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

        def assert_files_generated(spec: str, *, expected_files: List[str]) -> None:
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
                            "--backend-packages2=pants.backend.codegen.protobuf.python",
                            "--source-root-patterns=src/protobuf",
                            "--source-root-patterns=tests/protobuf",
                        ]
                    ),
                ),
            )
            assert set(generated_sources.snapshot.files) == set(expected_files)

        assert_files_generated(
            "src/protobuf/dir1", expected_files=["dir1/f_pb2.py", "dir1/f2_pb2.py"]
        )
        assert_files_generated("src/protobuf/dir2", expected_files=["dir2/f_pb2.py"])
        assert_files_generated(
            "tests/protobuf/test_protos", expected_files=["test_protos/f_pb2.py"]
        )
