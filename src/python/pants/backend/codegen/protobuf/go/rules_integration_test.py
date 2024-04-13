# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from textwrap import dedent
from typing import Iterable

import pytest

from pants.backend.codegen.protobuf import protobuf_dependency_inference, target_types
from pants.backend.codegen.protobuf.go.rules import (
    GenerateGoFromProtobufRequest,
    parse_go_package_option,
)
from pants.backend.codegen.protobuf.go.rules import rules as go_protobuf_rules
from pants.backend.codegen.protobuf.target_types import (
    ProtobufSourceField,
    ProtobufSourcesGeneratorTarget,
    ProtobufSourceTarget,
)
from pants.backend.codegen.protobuf.target_types import rules as protobuf_target_types_rules
from pants.backend.go import target_type_rules
from pants.backend.go.goals import test
from pants.backend.go.goals.test import GoTestFieldSet, GoTestRequest
from pants.backend.go.target_types import GoModTarget, GoPackageTarget
from pants.backend.go.util_rules import (
    assembly,
    build_pkg,
    build_pkg_target,
    first_party_pkg,
    go_mod,
    implicit_linker_deps,
    link,
    sdk,
    tests_analysis,
    third_party_pkg,
)
from pants.build_graph.address import Address
from pants.core.goals.test import TestResult, get_filtered_environment
from pants.core.util_rules import config_files, source_files, stripped_source_files
from pants.core.util_rules.external_tool import rules as external_tool_rules
from pants.engine.fs import Digest, DigestContents
from pants.engine.rules import QueryRule
from pants.engine.target import GeneratedSources, HydratedSources, HydrateSourcesRequest
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, RuleRunner
from pants.testutil.skip_utils import requires_go


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *config_files.rules(),
            *external_tool_rules(),
            *source_files.rules(),
            *protobuf_target_types_rules(),
            *protobuf_dependency_inference.rules(),
            *stripped_source_files.rules(),
            *go_protobuf_rules(),
            *sdk.rules(),
            *target_types.rules(),
            # Rules needed to run Go unit test.
            *test.rules(),
            *assembly.rules(),
            *build_pkg.rules(),
            *build_pkg_target.rules(),
            *first_party_pkg.rules(),
            *go_mod.rules(),
            *link.rules(),
            *implicit_linker_deps.rules(),
            *sdk.rules(),
            *target_type_rules.rules(),
            *tests_analysis.rules(),
            *third_party_pkg.rules(),
            get_filtered_environment,
            QueryRule(HydratedSources, [HydrateSourcesRequest]),
            QueryRule(GeneratedSources, [GenerateGoFromProtobufRequest]),
            QueryRule(DigestContents, (Digest,)),
            QueryRule(TestResult, (GoTestRequest.Batch,)),
        ],
        target_types=[
            GoModTarget,
            GoPackageTarget,
            ProtobufSourceTarget,
            ProtobufSourcesGeneratorTarget,
        ],
    )
    rule_runner.set_options(
        [],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )
    return rule_runner


def assert_files_generated(
    rule_runner: RuleRunner,
    address: Address,
    *,
    expected_files: list[str],
    source_roots: list[str],
    extra_args: Iterable[str] = (),
) -> None:
    args = [f"--source-root-patterns={repr(source_roots)}", *extra_args]
    rule_runner.set_options(args, env_inherit=PYTHON_BOOTSTRAP_ENV)
    tgt = rule_runner.get_target(address)
    protocol_sources = rule_runner.request(
        HydratedSources, [HydrateSourcesRequest(tgt[ProtobufSourceField])]
    )
    generated_sources = rule_runner.request(
        GeneratedSources, [GenerateGoFromProtobufRequest(protocol_sources.snapshot, tgt)]
    )
    assert set(generated_sources.snapshot.files) == set(expected_files)


def test_extracts_go_package() -> None:
    import_path = parse_go_package_option(b"""option go_package = "example.com/dir1";""")
    assert import_path == "example.com/dir1"


@requires_go
def test_generates_go(rule_runner: RuleRunner) -> None:
    # This tests a few things:
    #  * We generate the correct file names.
    #  * Protobuf files can import other protobuf files, and those can import others
    #    (transitive dependencies). We'll only generate the requested target, though.
    #  * We can handle multiple source roots, which need to be preserved in the final output.
    rule_runner.write_files(
        {
            "src/protobuf/dir1/f.proto": dedent(
                """\
                syntax = "proto3";

                option go_package = "example.com/dir1";

                package dir1;

                message Person {
                  string name = 1;
                  int32 id = 2;
                  string email = 3;
                }
                """
            ),
            "src/protobuf/dir1/f2.proto": dedent(
                """\
                syntax = "proto3";

                option go_package = "example.com/dir1";

                package dir1;

                message Place {
                  string town = 1;
                  string country = 2;
                }
                """
            ),
            "src/protobuf/dir1/BUILD": dedent(
                """\
                protobuf_sources()
                """
            ),
            "src/protobuf/dir2/f.proto": dedent(
                """\
                syntax = "proto3";

                option go_package = "example.com/dir2";

                package dir2;

                import "dir1/f.proto";

                message Employee {
                  dir1.Person self = 1;
                  dir1.Person manager = 2;
                }
                """
            ),
            "src/protobuf/dir2/BUILD": "protobuf_sources()",
            # Test another source root.
            "tests/protobuf/test_protos/f.proto": dedent(
                """\
                syntax = "proto3";

                option go_package = "example.com/test_protos";

                package test_protos;

                import "dir2/f.proto";
                """
            ),
            "tests/protobuf/test_protos/BUILD": ("protobuf_sources()"),
            "src/go/people/BUILD": dedent(
                """\
                go_mod(name="mod")
                go_package(name="pkg")
                """
            ),
            "src/go/people/go.mod": dedent(
                """\
                module example.com/people
                require google.golang.org/protobuf v1.27.1
                """
            ),
            "src/go/people/go.sum": dedent(
                """\
                github.com/golang/protobuf v1.5.0 h1:LUVKkCeviFUMKqHa4tXIIij/lbhnMbP7Fn5wKdKkRh4=
                github.com/golang/protobuf v1.5.0/go.mod h1:FsONVRAS9T7sI+LIUmWTfcYkHO4aIWwzhcaSAoJOfIk=
                github.com/google/go-cmp v0.5.5 h1:Khx7svrCpmxxtHBq5j2mp/xVjsi8hQMfNLvJFAlrGgU=
                github.com/google/go-cmp v0.5.5/go.mod h1:v8dTdLbMG2kIc/vJvl+f65V22dbkXbowE6jgT/gNBxE=
                golang.org/x/xerrors v0.0.0-20191204190536-9bdfabe68543 h1:E7g+9GITq07hpfrRu66IVDexMakfv52eLZ2CXBWiKr4=
                golang.org/x/xerrors v0.0.0-20191204190536-9bdfabe68543/go.mod h1:I/5z698sn9Ka8TeJc9MKroUUfqBBauWjQqLJ2OPfmY0=
                google.golang.org/protobuf v1.26.0-rc.1/go.mod h1:jlhhOSvTdKEhbULTjvd4ARK9grFBp09yW+WbY/TyQbw=
                google.golang.org/protobuf v1.27.1 h1:SnqbnDw1V7RiZcXPx5MEeqPv2s79L9i7BJUlG/+RurQ=
                google.golang.org/protobuf v1.27.1/go.mod h1:9q0QmTI4eRPtz6boOQmLYwt+qCgq0jsYwAQnmE0givc=
                """
            ),
            "src/go/people/proto_test.go": dedent(
                """\
                package people
                import (
                  "testing"
                  pb_dir1 "example.com/dir1"
                  pb_dir2 "example.com/dir2"
                )
                func TestProtoGen(t *testing.T) {
                  person := pb_dir1.Person{
                    Name: "name",
                    Id: 1,
                    Email: "name@example.com",
                  }
                  if person.Name != "name" {
                    t.Fail()
                  }
                  place := pb_dir1.Place{
                    Town: "Any Town",
                    Country: "Some Country",
                  }
                  if place.Town != "Any Town" {
                    t.Fail()
                  }
                  employee := pb_dir2.Employee{
                    Self: &pb_dir1.Person{
                      Name: "self",
                      Id: 1,
                      Email: "self@example.com",
                    },
                    Manager: &pb_dir1.Person{
                      Name: "manager",
                      Id: 2,
                      Email: "manager@example.com",
                    },
                  }
                  if employee.Self.Name != "self" {
                    t.Fail()
                  }
                }
                """
            ),
        }
    )

    def assert_gen(addr: Address, expected: Iterable[str]) -> None:
        assert_files_generated(
            rule_runner,
            addr,
            source_roots=["src/python", "/src/protobuf", "/tests/protobuf"],
            expected_files=list(expected),
        )

    assert_gen(
        Address("src/protobuf/dir1", relative_file_path="f.proto"),
        ("src/protobuf/dir1/f.pb.go",),
    )
    assert_gen(
        Address("src/protobuf/dir1", relative_file_path="f2.proto"),
        ("src/protobuf/dir1/f2.pb.go",),
    )
    assert_gen(
        Address("src/protobuf/dir2", relative_file_path="f.proto"),
        ("src/protobuf/dir2/f.pb.go",),
    )
    assert_gen(
        Address("tests/protobuf/test_protos", relative_file_path="f.proto"),
        ("tests/protobuf/test_protos/f.pb.go",),
    )

    rule_runner.set_options(
        ["--go-test-args=-v"],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )
    tgt = rule_runner.get_target(Address("src/go/people", target_name="pkg"))
    result = rule_runner.request(
        TestResult, [GoTestRequest.Batch("", (GoTestFieldSet.create(tgt),), None)]
    )
    assert result.exit_code == 0
    assert b"PASS: TestProtoGen" in result.stdout_bytes


@requires_go
def test_generates_go_grpc(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "protos/BUILD": "protobuf_sources(grpc=True)",
            "protos/service.proto": dedent(
                """\
            syntax = "proto3";

            option go_package = "example.com/protos";

            package service;

            message TestMessage {
              string foo = 1;
            }

            service TestService {
              rpc noStreaming (TestMessage) returns (TestMessage);
              rpc clientStreaming (stream TestMessage) returns (TestMessage);
              rpc serverStreaming (TestMessage) returns (stream TestMessage);
              rpc bothStreaming (stream TestMessage) returns (stream TestMessage);
            }
            """
            ),
        }
    )
    assert_files_generated(
        rule_runner,
        Address("protos", relative_file_path="service.proto"),
        source_roots=["/"],
        expected_files=[
            "protos/service.pb.go",
            "protos/service_grpc.pb.go",
        ],
    )
