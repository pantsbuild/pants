# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from textwrap import dedent

from twitter.common.collections import OrderedSet

from pants.backend.codegen.targets.java_protobuf_library import JavaProtobufLibrary
from pants.backend.codegen.tasks.protobuf_gen import ProtobufGen, _same_contents, calculate_genfiles
from pants.backend.core.targets.dependencies import Dependencies
from pants.base.build_file_aliases import BuildFileAliases
from pants.base.source_root import SourceRoot
from pants.base.validation import assert_list
from pants.util.contextutil import temporary_dir, temporary_file
from pants.util.dirutil import safe_mkdir, safe_rmtree
from pants_test.tasks.test_base import TaskTest


class ProtobufGenTest(TaskTest):
  @classmethod
  def task_type(cls):
    return ProtobufGen

  @property
  def alias_groups(self):
    return BuildFileAliases.create(targets={
      'java_protobuf_library': JavaProtobufLibrary,
      'target': Dependencies},
    )


  def setUp(self):
    super(ProtobufGenTest, self).setUp()
    self.task_outdir =  os.path.join(self.build_root, 'gen', 'protoc', 'gen-java')


  def tearDown(self):
    super(ProtobufGenTest, self).tearDown()
    safe_rmtree(self.task_outdir)

  def assert_files(self, lang, rel_path, contents, expected_files):
    assert_list(expected_files)

    with temporary_file() as fp:
      fp.write(contents)
      fp.close()
      self.assertEqual(set(expected_files), calculate_genfiles(fp.name, rel_path)[lang])

  def assert_java_files(self, rel_path, contents, expected_files):
    self.assert_files('java', rel_path, contents, expected_files)

  def test_plain(self):
    self.assert_java_files(
        'snake_case.proto',
        'package com.twitter.ads.revenue_tables;',
        ['com/twitter/ads/revenue_tables/SnakeCase.java'])

    self.assert_java_files(
        'a/b/jake.proto',
        'package com.twitter.ads.revenue_tables;',
        ['com/twitter/ads/revenue_tables/Jake.java'])

  def test_custom_package(self):
    self.assert_java_files(
        'fred.proto',
        '''
          package com.twitter.ads.revenue_tables;
          option java_package = "com.example.foo.bar";
        ''',
        ['com/example/foo/bar/Fred.java'])

    self.assert_java_files(
        'bam_bam.proto',
        'option java_package = "com.example.baz.bip";',
        ['com/example/baz/bip/BamBam.java'])

    self.assert_java_files(
        'bam_bam.proto',
        'option java_package="com.example.baz.bip" ;',
        ['com/example/baz/bip/BamBam.java'])

    self.assert_java_files(
      'fred.proto',
      '''
        option java_package = "com.example.foo.bar";
        package com.twitter.ads.revenue_tables;

      ''',
      ['com/example/foo/bar/Fred.java'])

  def test_custom_outer(self):
    self.assert_java_files(
        'jack_spratt.proto',
        '''
          package com.twitter.lean;
          option java_outer_classname = "To";
        ''',
        ['com/twitter/lean/To.java'])

  def test_multiple_files(self):
    self.assert_java_files(
        'jack_spratt.proto',
        '''
          package com.twitter.lean;
          option java_multiple_files = false;
        ''',
        ['com/twitter/lean/JackSpratt.java'])

    self.assert_java_files(
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
      'Camel-case.proto',
      '''
        package pants.preferences;
        option java_package = "com.pants.protos.preferences";
      ''',
      ['com/pants/protos/preferences/CamelCase.java'])

    self.assert_java_files(
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
    with temporary_dir() as workdir:
      with open(os.path.join(workdir, 'dup1.proto'), 'w') as dup1:
        dup1.write(dedent('''
            package com.twitter.lean;
            option java_multiple_files = true;
            enum Jake { FOO=1;}
            message joe_bob {}
          '''))
      with open(os.path.join(workdir, 'dup2.proto'), 'w') as dup2:
        dup2.write(dedent('''
            package com.twitter.lean;
            option java_multiple_files = true;
            enum Jake { FOO=1;}
            message joe_bob {}
          '''))
      self.assertTrue(_same_contents(dup1.name, dup2.name))

  def test_not_same_contents(self):
    with temporary_dir() as workdir:
      with open(os.path.join(workdir, 'dup1.proto'), 'w') as dup1:
        dup1.write(dedent('''
            package com.twitter.lean;
            option java_multiple_files = true;
            enum Jake { FOO=1;}
            message joe_bob {}
          '''))
      with open(os.path.join(workdir, 'dup2.proto'), 'w') as dup2:
        dup2.write(dedent('''
            package com.twitter.lean;
            message joe_bob {}
          '''))
      self.assertFalse(_same_contents(dup1.name, dup2.name))

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
    task = self.prepare_task(build_graph=self.build_graph,
                             targets=[target],
                             build_file_parser=self.build_file_parser)
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
    task = self.prepare_task(build_graph=self.build_graph,
                             targets=[self.target('test_proto:proto')],
                             build_file_parser=self.build_file_parser)
    javadeps = task.javadeps
    self.assertEquals(len(javadeps), 1)
    self.assertEquals('protobuf-java', javadeps.pop().name)
