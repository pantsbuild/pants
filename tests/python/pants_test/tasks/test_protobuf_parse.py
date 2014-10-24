# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import unittest2 as unittest

from pants.backend.codegen.tasks.protobuf_parse import ProtobufParse
from pants.backend.codegen.tasks.protobuf_parse import TYPE_PARSER


class ProtobufGenCalculateJavaTest(unittest.TestCase):

  def setUp(self):
    self.proto_parser_wire = ProtobufParse(
      'wire',
      '/Users/arp/src/pants/examples/src/wire/com/pants/examples/temperature/temperatures.proto',
      'examples/src/wire/com/pants/examples/temperature/temperatures.proto')

    self.proto_parser_protoc = ProtobufParse(
      'protoc',
      '/Users/arp/src/pants/examples/src/protobuf/com/pants/examples/distance/distances.proto',
      'examples/src/protobuf/com/pants/examples/distance/distances.proto')

  def test_parse(self):
    self.proto_parser_wire.parse()
    self.assertEqual('com.pants.examples.temperature', self.proto_parser_wire.package)
    self.assertEqual(set(['Temperature']), self.proto_parser_wire.types)

    self.proto_parser_protoc.parse()
    self.assertEqual('com.pants.examples.distance', self.proto_parser_protoc.package)
    self.assertEqual(set([]), self.proto_parser_protoc.types)
    self.assertEqual('Distances', self.proto_parser_protoc.outer_class_name)

  def test_update_type_list(self):
    match = TYPE_PARSER.match('message Temperature {')

    expected_value = set()
    expected_value.add('Temperature')
    actual_value = set()
    self.proto_parser_wire.update_type_list(match, 0, actual_value)
    self.assertEqual(expected_value, actual_value)

    expected_value.add('TemperatureOrBuilder')
    actual_value = set()
    self.proto_parser_protoc.update_type_list(match, 0, actual_value)
    self.assertEqual(expected_value, actual_value)

  def get_outer_class_name(self, source):
    self.assertEqual('Distances', self.proto_parser_wire.get_outer_class_name('distances.java'))

  def test_camelcase(self):
    self.assertEqual('TestingOut', self.proto_parser_wire.camelcase('testing_out'))
