# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

from pants.backend.codegen.grpcio.python.python_grpcio_library import PythonGrpcioLibrary
from pants_test.backend.codegen.grpcio.grpcio_test_base import GrpcioTestBase


class GrpcioGenTest(GrpcioTestBase):
    def test_multiple_dependent_protobufs(self):
        # given
        self.create_file(
            "src/grpcio/com/foo/foo_example.proto",
            contents=dedent(
                """
                syntax = "proto3";
                package com.foo;

                service FooService {
                    rpc Foo(FooRequest) returns (FooReply) {}
                }
                message FooRequest {
                    string foo = 1;
                }
                message FooReply {
                    string bar = 1;
                }
                """
            ),
        )
        self.create_file(
            "src/grpcio/com/bar/bar_example.proto",
            contents=dedent(
                """
                syntax = "proto3";
                package com.bar;

                import "com/foo/foo_example.proto";

                service BarService {
                    rpc Bar(BarRequest) returns (BarReply) {}
                }
                message BarRequest {
                    com.foo.FooRequest foo_request = 1;
                }
                message BarReply {
                    com.foo.FooReply foo_reply = 1;
                }
                """
            ),
        )
        foo_target = self.make_target(
            spec="src/grpcio/com/foo:example",
            target_type=PythonGrpcioLibrary,
            sources=["foo_example.proto"],
        )
        bar_target = self.make_target(
            spec="src/grpcio/com/bar:example",
            target_type=PythonGrpcioLibrary,
            sources=["bar_example.proto"],
            dependencies=[foo_target],
        )

        # when
        synthetic_target = self.generate_grpcio_targets(bar_target)

        # then
        self.assertIsNotNone(synthetic_target)
        self.assertEqual(2, len(synthetic_target))
        self.assertEqual(
            {
                "com/__init__.py",
                "com/foo/__init__.py",
                "com/foo/foo_example_pb2_grpc.py",
                "com/foo/foo_example_pb2.py",
            },
            set(synthetic_target[0].sources_relative_to_source_root()),
        )
        self.assertEqual(
            {
                "com/__init__.py",
                "com/bar/__init__.py",
                "com/bar/bar_example_pb2_grpc.py",
                "com/bar/bar_example_pb2.py",
            },
            set(synthetic_target[1].sources_relative_to_source_root()),
        )
