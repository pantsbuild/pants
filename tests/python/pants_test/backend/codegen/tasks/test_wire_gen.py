# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.backend.codegen.tasks.wire_gen import WireGen, calculate_genfiles
from pants_test.tasks.test_base import TaskTest
from pants.util.contextutil import temporary_file


class WireGenCalculateGenfilesTestBase(TaskTest):
  @classmethod
  def task_type(cls):
    return WireGen

  def assert_files(self, lang, rel_path, contents, *expected_files):
    if isinstance(expected_files[0], list):
      expected_files = expected_files[0]

    with temporary_file() as fp:
      fp.write(contents)
      fp.close()
      self.assertEqual(set(expected_files), calculate_genfiles(fp.name, rel_path)[lang])


class WireGenCalculateJavaTest(WireGenCalculateGenfilesTestBase):

  def assert_java_files(self, rel_path, contents, *expected_files):
    self.assert_files('java', rel_path, contents, *expected_files)

  def test_plain(self):
    self.assert_java_files(
      'temperatures.proto',
      '''
        package com.pants.examples.temperature;

        /**
         * Structure for expressing temperature: 75 Fahrenheit, 12 Celsius, etc.
         * Not so useful on its own.
         */
        message Temperature {
          optional string unit = 1;
          required int64 number = 2;
        }
      ''',
      'com/pants/examples/temperature/Temperature.java')

    self.assert_java_files(
      'temperatures.proto',
      'package com.pants.examples.temperature',
      [])

  def test_custom_package(self):
    self.assert_java_files(
      'freds.proto',
      '''
        package com.twitter.ads.revenue_tables;
        option java_package = "com.example.foo.bar";

        message Fred {
          optional string name = 1;
        }
      ''',
      'com/example/foo/bar/Fred.java')

    self.assert_java_files(
      'bam_bam.proto',
      'option java_package = "com.example.baz.bip";',
      [])

    self.assert_java_files(
      'bam_bam.proto',
      '''
        option java_package="com.example.baz.bip" ;

        message BamBam {
          optional string name = 1;
        }
      ''',
      'com/example/baz/bip/BamBam.java')

    self.assert_java_files(
      'fred.proto',
      '''
        option java_package = "com.example.foo.bar";
        package com.twitter.ads.revenue_tables;

      ''',
      [])

  def test_multiple_files(self):
    self.assert_java_files(
      'jack_spratt.proto',
      '''
        package com.twitter.lean;
        option java_multiple_files = false;
      ''',
      [])

    self.assert_java_files(
      'jack_spratt_no_whitespace.proto',
      '''
        package com.twitter.lean;
        option java_multiple_files = true;
        enum Jake { FOO=1;}
        message joe_bob {}
      ''',
      'com/twitter/lean/Jake.java',
      'com/twitter/lean/joe_bob.java',
      )

    self.assert_java_files(
      'jack_spratt.proto',
      '''
        package com.twitter.lean;
        option java_multiple_files = true;

        enum Jake { FOO=1;
        }
        message joe_bob {
        }
      ''',
      'com/twitter/lean/Jake.java',
      'com/twitter/lean/joe_bob.java')

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
      'com/pants/protos/Foo.java')

    self.assert_java_files(
      'Camel-case.proto',
      '''
        package pants.preferences;
        option java_package = "com.pants.protos.preferences";
      ''',
      [])

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
      'com/pants/protos/preferences/SomeService.java',
      'com/pants/protos/preferences/Wat.java')

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
      'com/pants/protos/preferences/AnotherMessage.java',
      'com/pants/protos/preferences/SomeService.java',
      'com/pants/protos/preferences/MessageAfterService.java')
