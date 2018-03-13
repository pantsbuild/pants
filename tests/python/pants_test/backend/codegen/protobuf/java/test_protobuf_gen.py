# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from textwrap import dedent

from twitter.common.collections import OrderedSet

from pants.backend.codegen.protobuf.java.protobuf_gen import ProtobufGen
from pants.backend.codegen.protobuf.java.register import build_file_aliases as register_codegen
from pants.backend.jvm.register import build_file_aliases as register_jvm
from pants.build_graph.register import build_file_aliases as register_core
from pants_test.tasks.task_test_base import TaskTestBase


class ProtobufGenTest(TaskTestBase):

  def setUp(self):
    super(ProtobufGenTest, self).setUp()
    self.set_options(pants_bootstrapdir='~/.cache/pants',
                     max_subprocess_args=100,
                     pants_support_fetch_timeout_secs=1,
                     pants_support_baseurls=['http://example.com/dummy_base_url'])

  @classmethod
  def task_type(cls):
    return ProtobufGen

  @property
  def alias_groups(self):
    return register_core().merge(register_jvm()).merge(register_codegen())

  def test_default_javadeps(self):
    self.create_file(relpath='test_proto/test.proto', contents=dedent("""
      package com.example.test_proto;
      enum Foo { foo=1;}
      message Bar {}
    """))

    self.add_to_build_file('test_proto', dedent("""
      java_protobuf_library(name='proto',
        sources=['test.proto'],
        dependencies=[]
      )
    """))
    self.add_to_build_file('3rdparty', dedent("""
      target(name='protobuf-java')
    """))
    context = self.context(target_roots=[self.target('test_proto:proto')])
    task = self.create_task(context)
    javadeps = task.javadeps
    self.assertEquals(len(javadeps), 1)
    self.assertEquals('protobuf-java', javadeps.pop().name)

  def test_calculate_sources(self):
    self.add_to_build_file('proto-lib', dedent("""
      java_protobuf_library(name='proto-target',
        sources=['foo.proto'],
      )
      """))
    target = self.target('proto-lib:proto-target')
    context = self.context(target_roots=[target])
    task = self.create_task(context)
    result = task._calculate_sources(target)
    self.assertEquals(1, len(result.keys()))
    self.assertEquals(OrderedSet(['proto-lib/foo.proto']), result['proto-lib'])

  def test_calculate_sources_with_source_root(self):
    self.add_to_build_file('project/src/main/proto/proto-lib', dedent("""
      java_protobuf_library(name='proto-target',
        sources=['foo.proto'],
      )
      """))
    target = self.target('project/src/main/proto/proto-lib:proto-target')
    context = self.context(target_roots=[target])
    task = self.create_task(context)
    result = task._calculate_sources(target)
    self.assertEquals(1, len(result.keys()))
    self.assertEquals(OrderedSet(['project/src/main/proto/proto-lib/foo.proto']),
                      result['project/src/main/proto'])
