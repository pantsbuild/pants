# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from textwrap import dedent

from twitter.common.collections import OrderedSet

from pants.backend.codegen.register import build_file_aliases as register_codegen
from pants.backend.codegen.tasks.protobuf_gen import ProtobufGen
from pants.backend.core.register import build_file_aliases as register_core
from pants.util.dirutil import safe_mkdir
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
    return register_core().merge(register_codegen())

  def test_protos_extracted_under_build_root(self):
    """This testcase shows that you can put sources for protos outside the directory where the
    BUILD file is defined. This will be the case for .proto files that have been extracted
    under .pants.d.
    """
    # place a .proto file in a place outside of where the BUILD file is defined
    extracted_source_path = os.path.join(self.build_root, 'extracted', 'src', 'proto')
    safe_mkdir(os.path.join(extracted_source_path, 'sample-package'))
    sample_proto_path = os.path.join(extracted_source_path, 'sample-package', 'sample.proto')
    with open(sample_proto_path, 'w') as sample_proto:
      sample_proto.write(dedent("""
            package com.example;
            message sample {}
          """))
    self.add_to_build_file('sample', dedent("""
        java_protobuf_library(name='sample',
          sources=['{sample_proto_path}'],
        )""").format(sample_proto_path=sample_proto_path))
    target = self.target("sample:sample")
    context = self.context(target_roots=[target])
    task = self.create_task(context=context)
    sources_by_base = task._calculate_sources([target])
    self.assertEquals(['extracted/src/proto'], sources_by_base.keys())
    self.assertEquals(OrderedSet([sample_proto_path]), sources_by_base['extracted/src/proto'])

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
    result = task._calculate_sources([target])
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
    result = task._calculate_sources([target])
    self.assertEquals(1, len(result.keys()))
    self.assertEquals(OrderedSet(['project/src/main/proto/proto-lib/foo.proto']), result['project/src/main/proto'])
