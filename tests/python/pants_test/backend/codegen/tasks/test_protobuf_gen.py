# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from collections import OrderedDict
from textwrap import dedent

from twitter.common.collections import OrderedSet

from pants.backend.codegen.register import build_file_aliases as register_codegen
from pants.backend.codegen.targets.java_protobuf_library import JavaProtobufLibrary
from pants.backend.codegen.tasks.protobuf_gen import (ProtobufGen, _same_contents,
                                                      check_duplicate_conflicting_protos)
from pants.backend.core.register import build_file_aliases as register_core
from pants.base.source_root import SourceRoot
from pants.base.validation import assert_list
from pants.util.contextutil import temporary_file
from pants.util.dirutil import safe_mkdir
from pants_test.task_test_base import TaskTestBase


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

  def assert_files(self, task, lang, rel_path, contents, expected_files):
    assert_list(expected_files)
    with temporary_file() as fp:
      fp.write(contents)
      fp.close()
      self.assertEqual(set(expected_files), task.calculate_genfiles(fp.name, rel_path)[lang])

  def assert_java_files(self, task, rel_path, contents, expected_files):
    self.assert_files(task, 'java', rel_path, contents, expected_files)

  def test_plain(self):
    task = self.create_task(self.context())
    self.assert_java_files(
      task,
      'snake_case.proto',
      'package com.twitter.ads.revenue_tables;',
      ['com/twitter/ads/revenue_tables/SnakeCase.java'])

    self.assert_java_files(
      task,
      'a/b/jake.proto',
      'package com.twitter.ads.revenue_tables;',
      ['com/twitter/ads/revenue_tables/Jake.java'])

  def test_custom_package(self):
    task = self.create_task(self.context())
    self.assert_java_files(
      task,
      'fred.proto',
      '''
        package com.twitter.ads.revenue_tables;
        option java_package = "com.example.foo.bar";
      ''',
      ['com/example/foo/bar/Fred.java'])

    self.assert_java_files(
      task,
      'bam_bam.proto',
      'option java_package = "com.example.baz.bip";',
      ['com/example/baz/bip/BamBam.java'])

    self.assert_java_files(
      task,
      'bam_bam.proto',
      'option java_package="com.example.baz.bip" ;',
      ['com/example/baz/bip/BamBam.java'])

    self.assert_java_files(
      task,
      'fred.proto',
      '''
        option java_package = "com.example.foo.bar";
        package com.twitter.ads.revenue_tables;

      ''',
      ['com/example/foo/bar/Fred.java'])

  def test_custom_outer(self):
    task = self.create_task(self.context())
    self.assert_java_files(
      task,
      'jack_spratt.proto',
      '''
        package com.twitter.lean;
        option java_outer_classname = "To";
      ''',
      ['com/twitter/lean/To.java'])

  def test_multiple_files(self):
    task = self.create_task(self.context())
    self.assert_java_files(
      task,
      'jack_spratt.proto',
      '''
        package com.twitter.lean;
        option java_multiple_files = false;
      ''',
      ['com/twitter/lean/JackSpratt.java'])

    self.assert_java_files(
      task,
      'jack_spratt_no_whitespace.proto',
      '''
        package com.twitter.lean;
        option java_multiple_files = true;
        enum Jake { FOO=1;}
        message joe_bob {}
      ''',
      ['com/twitter/lean/Jake.java',
       'com/twitter/lean/joe_bob.java',
       'com/twitter/lean/joe_bobOrBuilder.java',
       'com/twitter/lean/JackSprattNoWhitespace.java'])

    self.assert_java_files(
      task,
      'inner_class.proto',
      '''
        package com.pants.protos;
        option java_multiple_files = true;
        message Foo {
          enum Bar {
            BAZ = 0;
          }
        }
      ''',
      ['com/pants/protos/InnerClass.java',
       'com/pants/protos/Foo.java',
       'com/pants/protos/FooOrBuilder.java'])

    self.assert_java_files(
      task,
      'Camel-case.proto',
      '''
        package pants.preferences;
        option java_package = "com.pants.protos.preferences";
      ''',
      ['com/pants/protos/preferences/CamelCase.java'])

    self.assert_java_files(
      task,
      'curly_braces.proto',
      '''
        package pants.preferences;
        option java_package = "com.pants.protos.preferences";
        option java_multiple_files = true;
        message Wat { message Inner { option meh = true; }
          option Inner field = 1;
        }
        service SomeService { rpc AndAnother() {} }
      ''',
      ['com/pants/protos/preferences/CurlyBraces.java',
       'com/pants/protos/preferences/SomeService.java',
       'com/pants/protos/preferences/Wat.java',
       'com/pants/protos/preferences/WatOrBuilder.java'])

    self.assert_java_files(
      task,
      'pants.proto',
      '''
        package pants.preferences;
        option java_multiple_files = true;
        option java_package = "com.pants.protos.preferences";
        message AnotherMessage {
          BAZ = 0;
        }

        service SomeService {
          rpc SomeRpc();
          rpc AnotherRpc() {
          }
          rpc AndAnother() {}
        }

        message MessageAfterService {
          MEH = 0;
        }
      ''',
      ['com/pants/protos/preferences/Pants.java',
       'com/pants/protos/preferences/AnotherMessage.java',
       'com/pants/protos/preferences/AnotherMessageOrBuilder.java',
       'com/pants/protos/preferences/SomeService.java',
       'com/pants/protos/preferences/MessageAfterService.java',
       'com/pants/protos/preferences/MessageAfterServiceOrBuilder.java'])

  def test_same_contents(self):
    dup1 = self.create_file('src/dup1.proto', dedent('''
            package com.twitter.lean;
            option java_multiple_files = true;
            enum Jake { FOO=1;}
            message joe_bob {}
          '''))
    dup2 = self.create_file('src/dup2.proto', dedent('''
            package com.twitter.lean;
            option java_multiple_files = true;
            enum Jake { FOO=1;}
            message joe_bob {}
          '''))
    self.assertTrue(_same_contents(dup1, dup2))

  def test_not_same_contents(self):
    dup1 = self.create_file('src/dup1.proto', dedent('''
            package com.twitter.lean;
            option java_multiple_files = true;
            enum Jake { FOO=1;}
            message joe_bob {}
          '''))
    dup2 = self.create_file('src/dup2.proto', dedent('''
            package com.twitter.lean;
            message joe_bob {}
          '''))
    self.assertFalse(_same_contents(dup1, dup2))

  def test_protos_extracted_under_build_root(self):
    """This testcase shows that you can put sources for protos outside the directory where the
    BUILD file is defined. This will be the case for .proto files that have been extracted
    under .pants.d.
    """
    # place a .proto file in a place outside of where the BUILD file is defined
    extracted_source_path = os.path.join(self.build_root, 'extracted-source')
    SourceRoot.register(extracted_source_path, JavaProtobufLibrary)
    safe_mkdir(os.path.join(extracted_source_path, 'sample-package'))
    sample_proto_path = os.path.join(extracted_source_path, 'sample-package', 'sample.proto')
    with open(sample_proto_path, 'w') as sample_proto:
      sample_proto.write(dedent('''
            package com.example;
            message sample {}
          '''))
    self.add_to_build_file('sample', dedent('''
        java_protobuf_library(name='sample',
          sources=['{sample_proto_path}'],
        )''').format(sample_proto_path=sample_proto_path))
    target = self.target("sample:sample")
    context = self.context(target_roots=[target])
    task = self.create_task(context=context)
    sources_by_base = task._calculate_sources([target])
    self.assertEquals(['extracted-source'], sources_by_base.keys())
    self.assertEquals(OrderedSet([sample_proto_path]), sources_by_base['extracted-source'])

  def test_default_javadeps(self):
    self.create_file(relpath='test_proto/test.proto', contents=dedent('''
      package com.example.test_proto;
      enum Foo { foo=1;}
      message Bar {}
    '''))

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
    self.add_to_build_file('proto-lib', dedent('''
      java_protobuf_library(name='proto-target',
        sources=['foo.proto'],
      )
      '''))
    target = self.target('proto-lib:proto-target')
    context = self.context(target_roots=[target])
    task = self.create_task(context)
    result = task._calculate_sources([target])
    self.assertEquals(1, len(result.keys()))
    self.assertEquals(OrderedSet(['proto-lib/foo.proto']), result['proto-lib'])

  def test_calculate_sources_with_source_root(self):
    SourceRoot.register('project/src/main/proto')
    self.add_to_build_file('project/src/main/proto/proto-lib', dedent('''
      java_protobuf_library(name='proto-target',
        sources=['foo.proto'],
      )
      '''))
    target = self.target('project/src/main/proto/proto-lib:proto-target')
    context = self.context(target_roots=[target])
    task = self.create_task(context)
    result = task._calculate_sources([target])
    self.assertEquals(1, len(result.keys()))
    self.assertEquals(OrderedSet(['project/src/main/proto/proto-lib/foo.proto']), result['project/src/main/proto'])

  class MockLogger:
    def __init__(self):
      self._warn = []
      self._error = []

    def warn(self, msg):
      self._warn.append(msg)

    def error(self, msg):
      self._error.append(msg)

  def test_check_duplicate_conflicting_protos_warn(self):
    file1 = self.create_file('src1/foo.proto', dedent('''
      package com.example.test_proto;
      message Foo{}
    '''))

    # Create an identical .proto file in a different directory
    file2 = self.create_file('src2/foo.proto', dedent('''
      package com.example.test_proto;
      message Foo{}
    '''))

    task = self.create_task(self.context())
    test_logger = self.MockLogger()
    sources_by_base = OrderedDict()
    sources_by_base[os.path.join(self.build_root, 'src1')] = [file1]
    sources_by_base[os.path.join(self.build_root, 'src2')] = [file2]

    check_duplicate_conflicting_protos(task, sources_by_base, [file1, file2], test_logger)

    self.assertEquals(4, len(test_logger._warn))
    self.assertRegexpMatches(test_logger._warn[0], '^Proto duplication detected.*\n.*src1/foo.proto\n.*src2/foo.proto')
    self.assertRegexpMatches(test_logger._warn[1], 'Arbitrarily favoring proto 1')
    self.assertRegexpMatches(test_logger._warn[2], '^Proto duplication detected.*\n.*src1/foo.proto\n.*src2/foo.proto')
    self.assertRegexpMatches(test_logger._warn[3], 'Arbitrarily favoring proto 1')

    self.assertEquals([], test_logger._error)

  def test_check_duplicate_conflicting_protos_error(self):
    file1 = self.create_file('src1/foo.proto', dedent('''
        package com.example.test_proto;
        message Foo{value=1;}
      '''))

    # Create an  .proto file in a different directory that has a different definition
    file2 = self.create_file('src2/foo.proto', dedent('''
        package com.example.test_proto;
        message Foo{}
      '''))

    task = self.create_task(self.context())
    test_logger = self.MockLogger()
    sources_by_base = OrderedDict()
    sources_by_base[os.path.join(self.build_root, 'src1')] = [file1]
    sources_by_base[os.path.join(self.build_root, 'src2')] = [file2]

    check_duplicate_conflicting_protos(task, sources_by_base, [file1, file2], test_logger)

    self.assertEquals(2, len(test_logger._warn))

    self.assertRegexpMatches(test_logger._warn[0], 'Arbitrarily favoring proto 1')
    self.assertRegexpMatches(test_logger._warn[1], 'Arbitrarily favoring proto 1')
    self.assertEquals(2, len(test_logger._error))
    self.assertRegexpMatches(test_logger._error[0], '^Proto conflict detected.*\n.*src1/foo.proto\n.*src2/foo.proto')
    self.assertRegexpMatches(test_logger._error[1], '^Proto conflict detected.*\n.*src1/foo.proto\n.*src2/foo.proto')
