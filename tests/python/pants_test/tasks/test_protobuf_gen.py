# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
from textwrap import dedent
import unittest2 as unittest

from pants.backend.codegen.tasks.protobuf_gen import calculate_genfiles, _same_contents
from pants.base.validation import assert_list
from pants.util.contextutil import temporary_dir, temporary_file


class ProtobufGenCalculateGenfilesTestBase(unittest.TestCase):
  def assert_files(self, lang, rel_path, contents, expected_files):
    assert_list(expected_files)

    with temporary_file() as fp:
      fp.write(contents)
      fp.close()
      self.assertEqual(set(expected_files), calculate_genfiles(fp.name, rel_path)[lang])


class ProtobufGenCalculateJavaTest(ProtobufGenCalculateGenfilesTestBase):

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
