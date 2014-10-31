# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from contextlib import contextmanager
import unittest2 as unittest
import os
import pytest

from pants.backend.codegen.tasks.protobuf_parse import (MESSAGE_PARSER, ProtobufParse,
                                                        camelcase, get_outer_class_name,
                                                        update_type_list)
from pants.util.contextutil import temporary_dir


class ProtobufGenCalculateJavaTest(unittest.TestCase):

  def test_parse_for_wire(self):
    with temporary_dir() as workdir:
      with open(os.path.join(workdir, self._get_filename()), 'w') as fd:
        fd.write(self._get_file_content())
        fd.close()

        proto_parser_wire =  ProtobufParse(fd.name, self._get_filename())
        proto_parser_wire.parse()
        self.assertEqual('com.pants.examples.temperature', proto_parser_wire.package)
        self.assertEqual(set(), proto_parser_wire.enums)
        self.assertEqual(set(['Temperature']), proto_parser_wire.messages)
        self.assertEqual(set(), proto_parser_wire.services)
        self.assertEqual('Temperatures', proto_parser_wire.outer_class_name)

  def test_whitespace(self):
    with temporary_dir() as workdir:
      filename = 'jack_spratt_no_whitespace.proto'
      with open(os.path.join(workdir, filename), 'w') as fd:
        fd.write(
          '''
            package com.twitter.lean;
            option java_multiple_files = true;
            enum Jake { FOO=1;}
            message joe_bob {}
          '''
        )
        fd.close()
        proto_parse_no_whitespace =  ProtobufParse(fd.name, filename)
        proto_parse_no_whitespace.parse()
        self.assertEqual('com.twitter.lean', proto_parse_no_whitespace.package)
        self.assertEqual(set(['Jake']), proto_parse_no_whitespace.enums)
        self.assertEqual(set(['joe_bob']), proto_parse_no_whitespace.messages)
        self.assertEqual(set(), proto_parse_no_whitespace.services)
        self.assertEqual('JackSprattNoWhitespace', proto_parse_no_whitespace.outer_class_name)

      filename = 'jack_spratt.proto'
      with open(os.path.join(workdir, filename), 'w') as fd:
        fd.write(
          '''
            package com.twitter.lean;
            option java_multiple_files = true;

            enum Jake { FOO=1;
            }
            message joe_bob {
            }
          '''
        )
        fd.close()
        proto_parse_with_whitespace =  ProtobufParse(fd.name, filename)
        proto_parse_with_whitespace.parse()
        self.assertEqual('com.twitter.lean', proto_parse_with_whitespace.package)
        self.assertEqual(set(['Jake']), proto_parse_with_whitespace.enums)
        self.assertEqual(set(['joe_bob']), proto_parse_with_whitespace.messages)
        self.assertEqual('JackSpratt',proto_parse_with_whitespace.outer_class_name)

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

  def _get_file_content(self):
    return \
      '''
        package com.pants.examples.temperature;
        message Temperature {
          optional string unit = 1;
          required int64 number = 2;
        }
      '''

  def _get_filename(self):
    return 'temperatures.proto'


# TODO(Eric Ayers) This test won't pass because the .proto parse is not reliable.
#  https://github.com/pantsbuild/pants/issues/96
@pytest.mark.xfail
def test_inner_class_no_newline(self):
  with temporary_dir() as workdir:
    filename = 'inner_class_no_newline.proto'
    with open(os.path.join(workdir, filename), 'w') as fd:
      fd.write(
        '''
          package com.pants.protos;
          option java_multiple_files = true;
          message Foo {
             enum Bar { BAZ = 0; }
          }
        '''
      )
      fd.close()
      proto_parse =  ProtobufParse(fd.name, filename)
      proto_parse.parse()
      self.assertEqual('com.pants.protos', proto_parse.package)
      self.assertEqual(set(['Bar']), proto_parse.enums)
      self.assertEqual(set(['Foo']), proto_parse.messages)
      self.assertEqual(set(), proto_parse.services)
      self.assertEqual('InnerClassNoNewline', proto_parse.outer_class_name)

@pytest.mark.xfail
def test_no_newline_at_all1(self):
  with temporary_dir() as workdir:
    filename = 'no_newline_at_all1.proto'
    with open(os.path.join(workdir, filename), 'w') as fd:
      fd.write('package com.pants.protos; option java_multiple_files = true; message Foo {'
               + ' enum Bar { BAZ = 0; } } message FooBar { }')
      fd.close()
      proto_parse =  ProtobufParse(fd.name, filename)
      proto_parse.parse()
      self.assertEqual('com.pants.protos', proto_parse.package)
      self.assertEqual(set(['Bar']), proto_parse.enums)
      self.assertEqual(set(['Foo', 'FooBar']), proto_parse.messages)
      self.assertEqual(set(), proto_parse.services)
      self.assertEqual('NoNewlineAtAll1', proto_parse.outer_class_name)

@pytest.mark.xfail
def test_no_newline_at_all2(self):
  with temporary_dir() as workdir:
    filename = 'no_newline_at_all2.proto'
    with open(os.path.join(workdir, filename), 'w') as fd:
      fd.write('package com.pants.protos; message Foo {'
               + 'enum Bar { BAZ = 0; } } message FooBar { }')
      fd.close()
      proto_parse =  ProtobufParse(fd.name, filename)
      proto_parse.parse()
      self.assertEqual('com.pants.protos', proto_parse.package)
      self.assertEqual(set(['Bar']), proto_parse.enums)
      self.assertEqual(set(['Foo', 'FooBar']), proto_parse.messages)
      self.assertEqual(set(), proto_parse.services)
      self.assertEqual('NoNewlineAtAll2', proto_parse.outer_class_name)

@pytest.mark.xfail
def test_no_newline_at_all3(self):
  with temporary_dir() as workdir:
    filename = 'no_newline_at_all3.proto'
    with open(os.path.join(workdir, filename), 'w') as fd:
      fd.write('package com.pants.protos; option java_package = "com.example.foo.bar"; message Foo { }')
      fd.close()
      proto_parse =  ProtobufParse(fd.name, filename)
      proto_parse.parse()
      self.assertEqual('com.example.foo.bar', proto_parse.package)
      self.assertEqual(set(), proto_parse.enums)
      self.assertEqual(set(['Foo',]), proto_parse.messages)
      self.assertEqual(set(), proto_parse.services)
      self.assertEqual('NoNewlineAtAll3', proto_parse.outer_class_name)


@pytest.mark.xfail
def test_crazy_whitespace(self):
  with temporary_dir() as workdir:
    filename = 'crazy_whitespace.proto'
    with open(os.path.join(workdir, filename), 'w') as fd:
      fd.write(
        '''
          package
             com.pants.protos; option
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
        ''',
      )
      fd.close()
      proto_parse =  ProtobufParse(fd.name, filename)
      proto_parse.parse()
      self.assertEqual('com.example.foo.bar', proto_parse.package)
      self.assertEqual(set(['Bar']), proto_parse.enums)
      self.assertEqual(set(['Foo', 'FooBar']), proto_parse.messages)
      self.assertEqual(set(), proto_parse.services)
      self.assertEqual('CrazyWhitespace', proto_parse.outer_class_name)
