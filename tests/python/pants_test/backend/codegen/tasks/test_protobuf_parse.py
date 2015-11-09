# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest
from textwrap import dedent
from unittest.case import expectedFailure

from pants.backend.codegen.tasks.protobuf_parse import (MESSAGE_PARSER, ProtobufParse, camelcase,
                                                        get_outer_class_name, update_type_list)
from pants.util.contextutil import temporary_dir


class ProtobufParseTest(unittest.TestCase):

  def test_parse_for(self):
    with temporary_dir() as workdir:
      filename = 'temperatures.proto'
      with open(os.path.join(workdir, filename), 'w') as fd:
        fd.write(dedent('''
            package org.pantsbuild.example.temperature;
            message Temperature {
              optional string unit = 1;
              required int64 number = 2;
            }
          '''))
        fd.close()

        proto_parser = ProtobufParse(fd.name, filename)
        proto_parser.parse()
        self.assertEqual('org.pantsbuild.example.temperature', proto_parser.package)
        self.assertEqual(set(), proto_parser.enums)
        self.assertEqual(set(['Temperature']), proto_parser.messages)
        self.assertEqual(set(), proto_parser.services)
        self.assertEqual('Temperatures', proto_parser.outer_class_name)

  def test_whitespace(self):
    with temporary_dir() as workdir:
      filename = 'jack_spratt_no_whitespace.proto'
      with open(os.path.join(workdir, filename), 'w') as fd:
        fd.write(dedent('''
            package com.twitter.lean;
            option java_multiple_files = true;
            enum Jake { FOO=1;}
            message joe_bob {}
          '''))
        fd.close()
        proto_parse_no_whitespace = ProtobufParse(fd.name, filename)
        proto_parse_no_whitespace.parse()
        self.assertEqual('com.twitter.lean', proto_parse_no_whitespace.package)
        self.assertEqual(set(['Jake']), proto_parse_no_whitespace.enums)
        self.assertEqual(set(['joe_bob']), proto_parse_no_whitespace.messages)
        self.assertEqual(set(), proto_parse_no_whitespace.services)
        self.assertEqual('JackSprattNoWhitespace', proto_parse_no_whitespace.outer_class_name)

      filename = 'jack_spratt.proto'
      with open(os.path.join(workdir, filename), 'w') as fd:
        fd.write(dedent('''
            package com.twitter.lean;
            option java_multiple_files = true;

            enum Jake { FOO=1;
            }
            message joe_bob {
            }
          '''))
        fd.close()
        proto_parse_with_whitespace = ProtobufParse(fd.name, filename)
        proto_parse_with_whitespace.parse()
        self.assertEqual('com.twitter.lean', proto_parse_with_whitespace.package)
        self.assertEqual(set(['Jake']), proto_parse_with_whitespace.enums)
        self.assertEqual(set(['joe_bob']), proto_parse_with_whitespace.messages)
        self.assertEqual('JackSpratt', proto_parse_with_whitespace.outer_class_name)

  def test_update_type_list(self):
    match = MESSAGE_PARSER.match('message Temperature {')

    expected_value = set()
    expected_value.add('Temperature')
    actual_value = set()
    update_type_list(match, 0, actual_value)
    self.assertEqual(expected_value, actual_value)

  def get_outer_class_name(self, source):
    self.assertEqual('Distances', get_outer_class_name('distances.java'))

  def test_camelcase(self):
    self.assertEqual('TestingOut', camelcase('testing_out'))

  def test_filename(self):
    with temporary_dir() as workdir:
      filename = 'foobar/testfile.proto'
      os.makedirs(os.path.join(workdir, 'foobar'))
      with open(os.path.join(workdir, filename), 'w') as fd:
        fd.write(dedent('''
            package org.pantsbuild.protos;
            message Foo {
               optional string name = 1;
            }
          '''))
        fd.close()
        proto_parse = ProtobufParse(fd.name, filename)
        self.assertEquals('testfile', proto_parse.filename)

  def test_extend(self):
    with temporary_dir() as workdir:
      filename = 'testextend.proto'
      with open(os.path.join(workdir, filename), 'w') as fd:
        fd.write(dedent('''
            package org.pantsbuild.protos;
            extend Foo {
              optional int32 bar = 126;
            }
          '''))
        fd.close()
        proto_parse = ProtobufParse(fd.name, filename)
        proto_parse.parse()
        self.assertEqual(set(['Foo']), proto_parse.extends)

  # TODO(Eric Ayers) The following tests won't pass because the .proto parse is not reliable.
  #  https://github.com/pantsbuild/pants/issues/96
  @expectedFailure
  def test_inner_class_no_newline(self):
    with temporary_dir() as workdir:
      filename = 'inner_class_no_newline.proto'
      with open(os.path.join(workdir, filename), 'w') as fd:
        fd.write(dedent('''
            package org.pantsbuild.protos;
            option java_multiple_files = true;
            message Foo {
               enum Bar { BAZ = 0; }
            }
          '''))
        fd.close()
        proto_parse = ProtobufParse(fd.name, filename)
        proto_parse.parse()
        self.assertEqual('org.pantsbuild.protos', proto_parse.package)
        self.assertEqual(set(['Bar']), proto_parse.enums)
        self.assertEqual(set(['Foo']), proto_parse.messages)
        self.assertEqual(set(), proto_parse.services)
        self.assertEqual('InnerClassNoNewline', proto_parse.outer_class_name)

  @expectedFailure
  def test_no_newline_at_all1(self):
    with temporary_dir() as workdir:
      filename = 'no_newline_at_all1.proto'
      with open(os.path.join(workdir, filename), 'w') as fd:
        fd.write('package org.pantsbuild.protos; option java_multiple_files = true; message Foo {'
                 + ' enum Bar { BAZ = 0; } } message FooBar { }')
        fd.close()
        proto_parse = ProtobufParse(fd.name, filename)
        proto_parse.parse()
        self.assertEqual('org.pantsbuild.protos', proto_parse.package)
        self.assertEqual(set(['Bar']), proto_parse.enums)
        self.assertEqual(set(['Foo', 'FooBar']), proto_parse.messages)
        self.assertEqual(set(), proto_parse.services)
        self.assertEqual('NoNewlineAtAll1', proto_parse.outer_class_name)

  @expectedFailure
  def test_no_newline_at_all2(self):
    with temporary_dir() as workdir:
      filename = 'no_newline_at_all2.proto'
      with open(os.path.join(workdir, filename), 'w') as fd:
        fd.write('package org.pantsbuild.protos; message Foo {'
                 + 'enum Bar { BAZ = 0; } } message FooBar { }')
        fd.close()
        proto_parse = ProtobufParse(fd.name, filename)
        proto_parse.parse()
        self.assertEqual('org.pantsbuild.protos', proto_parse.package)
        self.assertEqual(set(['Bar']), proto_parse.enums)
        self.assertEqual(set(['Foo', 'FooBar']), proto_parse.messages)
        self.assertEqual(set(), proto_parse.services)
        self.assertEqual('NoNewlineAtAll2', proto_parse.outer_class_name)

  @expectedFailure
  def test_no_newline_at_all3(self):
    with temporary_dir() as workdir:
      filename = 'no_newline_at_all3.proto'
      with open(os.path.join(workdir, filename), 'w') as fd:
        fd.write('package org.pantsbuild.protos; option java_package = "com.example.foo.bar"; message Foo { }')
        fd.close()
        proto_parse = ProtobufParse(fd.name, filename)
        proto_parse.parse()
        self.assertEqual('com.example.foo.bar', proto_parse.package)
        self.assertEqual(set(), proto_parse.enums)
        self.assertEqual(set(['Foo', ]), proto_parse.messages)
        self.assertEqual(set(), proto_parse.services)
        self.assertEqual('NoNewlineAtAll3', proto_parse.outer_class_name)

  @expectedFailure
  def test_crazy_whitespace(self):
    with temporary_dir() as workdir:
      filename = 'crazy_whitespace.proto'
      with open(os.path.join(workdir, filename), 'w') as fd:
        fd.write(dedent('''
            package
               org.pantsbuild.protos; option
                   java_multiple_files
                   = true; option java_package =
                   "com.example.foo.bar"; message
            Foo
            {
            enum
            Bar {
            BAZ = 0; } } message
            FooBar
            { }
          '''))
        fd.close()
        proto_parse = ProtobufParse(fd.name, filename)
        proto_parse.parse()
        self.assertEqual('com.example.foo.bar', proto_parse.package)
        self.assertEqual(set(['Bar']), proto_parse.enums)
        self.assertEqual(set(['Foo', 'FooBar']), proto_parse.messages)
        self.assertEqual(set(), proto_parse.services)
        self.assertEqual('CrazyWhitespace', proto_parse.outer_class_name)
