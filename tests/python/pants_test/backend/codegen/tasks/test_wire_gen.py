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

  def assert_files(self, lang, rel_path, contents, service_writer, *expected_files):
    if isinstance(expected_files[0], list):
      expected_files = expected_files[0]

    with temporary_file() as fp:
      fp.write(contents)
      fp.close()
      self.assertEqual(set(expected_files), calculate_genfiles(fp.name, rel_path, service_writer)[lang])


class WireGenCalculateJavaTest(WireGenCalculateGenfilesTestBase):

  def assert_java_files(self, rel_path, contents, service_writer, *expected_files):
    self.assert_files('java', rel_path, contents, service_writer, *expected_files)

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
      None,
      'com/pants/examples/temperature/Temperature.java')

    self.assert_java_files(
      'temperatures.proto',
      'package com.pants.examples.temperature',
      None,
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
      None,
      'com/example/foo/bar/Fred.java')

    self.assert_java_files(
      'bam_bam.proto',
      'option java_package = "com.example.baz.bip";',
      None,
      [])

    self.assert_java_files(
      'bam_bam.proto',
      '''
        option java_package="com.example.baz.bip" ;

        message BamBam {
          optional string name = 1;
        }
      ''',
      None,
      'com/example/baz/bip/BamBam.java')

    self.assert_java_files(
      'fred.proto',
      '''
        option java_package = "com.example.foo.bar";
        package com.twitter.ads.revenue_tables;

      ''',
      None,
      [])

  def test_service_writer(self):
    self.assert_java_files(
      'pants.proto',
      '''
        package pants.preferences;
        option java_multiple_files = true;
        option java_package = "com.pants.protos.preferences";
        service SomeService {
          rpc SomeRpc();
          rpc AnotherRpc() {
          }
          rpc AndAnother() {}
        }
      ''',
      'com.squareup.wire.SimpleServiceWriter',
      'com/pants/protos/preferences/SomeService.java',)
