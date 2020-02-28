# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

from pants.backend.codegen.protobuf.java.protobuf_gen import ProtobufGen
from pants.backend.codegen.protobuf.java.register import build_file_aliases as register_codegen
from pants.backend.jvm.register import build_file_aliases as register_jvm
from pants.build_graph.register import build_file_aliases as register_core
from pants.testutil.task_test_base import TaskTestBase
from pants.util.ordered_set import OrderedSet


class ProtobufGenTest(TaskTestBase):
    def setUp(self):
        super().setUp()
        self.set_options(
            pants_bootstrapdir="~/.cache/pants",
            max_subprocess_args=100,
            binaries_fetch_timeout_secs=1,
            binaries_baseurls=["http://example.com/dummy_base_url"],
        )

    @classmethod
    def task_type(cls):
        return ProtobufGen

    @classmethod
    def alias_groups(cls):
        return register_core().merge(register_jvm()).merge(register_codegen())

    def test_default_javadeps(self):
        self.create_file(
            relpath="test_proto/test.proto",
            contents=dedent(
                """
                package com.example.test_proto;
                enum Foo { foo=1;}
                message Bar {}
                """
            ),
        )

        self.add_to_build_file(
            "test_proto",
            dedent(
                """
                java_protobuf_library(name='proto',
                  sources=['test.proto'],
                  dependencies=[]
                )
                """
            ),
        )
        self.add_to_build_file(
            "3rdparty",
            dedent(
                """
                target(name='protobuf-java')
                """
            ),
        )
        context = self.context(target_roots=[self.target("test_proto:proto")])
        task = self.create_task(context)
        javadeps = task.javadeps
        self.assertEqual(len(javadeps), 1)
        self.assertEqual("protobuf-java", javadeps.pop().name)

    def test_calculate_sources(self):
        self.create_file(relpath="proto-lib/foo.proto", contents="")
        self.add_to_build_file(
            "proto-lib",
            dedent(
                """
                java_protobuf_library(name='proto-target',
                  sources=['foo.proto'],
                )
                """
            ),
        )
        target = self.target("proto-lib:proto-target")
        context = self.context(target_roots=[target])
        task = self.create_task(context)
        result = task._calculate_sources(target)
        self.assertEqual(1, len(result.keys()))
        self.assertEqual(OrderedSet(["proto-lib/foo.proto"]), result["proto-lib"])

    def test_calculate_sources_with_source_root(self):
        self.create_file(relpath="project/src/main/proto/proto-lib/foo.proto", contents="")
        self.add_to_build_file(
            "project/src/main/proto/proto-lib",
            dedent(
                """
                java_protobuf_library(name='proto-target',
                  sources=['foo.proto'],
                )
                """
            ),
        )
        target = self.target("project/src/main/proto/proto-lib:proto-target")
        context = self.context(target_roots=[target])
        task = self.create_task(context)
        result = task._calculate_sources(target)
        self.assertEqual(1, len(result.keys()))
        self.assertEqual(
            OrderedSet(["project/src/main/proto/proto-lib/foo.proto"]),
            result["project/src/main/proto"],
        )
