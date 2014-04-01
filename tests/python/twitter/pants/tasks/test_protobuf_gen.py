# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import unittest

from twitter.common.contextutil import temporary_file

from pants.tasks.protobuf_gen import calculate_genfiles


class ProtobufGenCalculateGenfilesTestBase(unittest.TestCase):
  def assert_files(self, lang, rel_path, contents, *expected_files):
    with temporary_file() as fp:
      fp.write(contents)
      fp.close()
      self.assertEqual(set(expected_files), calculate_genfiles(fp.name, rel_path)[lang])


class ProtobufGenCalculateJavaTest(ProtobufGenCalculateGenfilesTestBase):

  def assert_java_files(self, rel_path, contents, *expected_files):
    self.assert_files('java', rel_path, contents, *expected_files)

  def test_plain(self):
    self.assert_java_files(
        'snake_case.proto',
        'package com.twitter.ads.revenue_tables;',
        'com/twitter/ads/revenue_tables/SnakeCase.java')

    self.assert_java_files(
        'a/b/jake.proto',
        'package com.twitter.ads.revenue_tables;',
        'com/twitter/ads/revenue_tables/Jake.java')

  def test_custom_package(self):
    self.assert_java_files(
        'fred.proto',
        '''
          package com.twitter.ads.revenue_tables;
          option java_package = "com.example.foo.bar";
        ''',
        'com/example/foo/bar/Fred.java')

    self.assert_java_files(
        'bam_bam.proto',
        'option java_package = "com.example.baz.bip";',
        'com/example/baz/bip/BamBam.java')

    self.assert_java_files(
        'bam_bam.proto',
        'option java_package="com.example.baz.bip" ;',
        'com/example/baz/bip/BamBam.java')

  def test_custom_outer(self):
    self.assert_java_files(
        'jack_spratt.proto',
        '''
          package com.twitter.lean;
          option java_outer_classname = "To";
        ''',
        'com/twitter/lean/To.java')

  def test_multiple_files(self):
    self.assert_java_files(
        'jack_spratt.proto',
        '''
          package com.twitter.lean;
          option java_multiple_files = false;
        ''',
        'com/twitter/lean/JackSpratt.java')

    self.assert_java_files(
        'jack_spratt.proto',
        '''
          package com.twitter.lean;
          option java_multiple_files = true;

          enum Jake { FOO=1; }
          message joe_bob {
          }
        ''',
        'com/twitter/lean/JackSpratt.java',
        'com/twitter/lean/Jake.java',
        'com/twitter/lean/joe_bob.java',
        'com/twitter/lean/joe_bobOrBuilder.java')
