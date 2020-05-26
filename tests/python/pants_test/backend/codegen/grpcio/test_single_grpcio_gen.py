# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

from pants.backend.codegen.grpcio.python.python_grpcio_library import PythonGrpcioLibrary
from pants_test.backend.codegen.grpcio.grpcio_test_base import GrpcioTestBase


class GrpcioMultipleGenTest(GrpcioTestBase):
    def test_single_protobuf(self):
        # given
        self.create_file(
            "src/grpcio/com/example/example.proto",
            contents=dedent(
                """
                syntax = "proto3";
                package com.example;

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
        example_target = self.make_target(
            spec="src/grpcio/com/example:example",
            target_type=PythonGrpcioLibrary,
            sources=["example.proto"],
        )

        # when
        synthetic_target = self.generate_grpcio_targets(example_target)

        # then
        self.assertEqual(1, len(synthetic_target))
        self.assertEqual(
            {
                "com/__init__.py",
                "com/example/__init__.py",
                "com/example/example_pb2_grpc.py",
                "com/example/example_pb2.py",
            },
            set(synthetic_target[0].sources_relative_to_source_root()),
        )
