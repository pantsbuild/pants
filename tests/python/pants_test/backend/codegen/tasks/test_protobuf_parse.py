# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from contextlib import contextmanager
import unittest2 as unittest
import os

from pants.backend.codegen.tasks.protobuf_parse import (ProtobufParse, TYPE_PARSER, camelcase, get_outer_class_name,
                                                        update_type_list)
from pants.util.contextutil import temporary_dir


class ProtobufGenCalculateJavaTest(unittest.TestCase):

  @contextmanager
  def test_parse_for_wire(self):
    with temporary_dir() as workdir:
      with open(os.path.join(workdir, "temperatures.proto"), 'w') as fd:
        fd.write(
          '''
            package com.pants.examples.temperature;
            message Temperature {
              optional string unit = 1;
              required int64 number = 2;
            }
          '''
        )
        fd.close()
        proto_parser_wire =  ProtobufParse('wire', fd.name, 'temperatures.proto')
        proto_parser_wire.parse()
        self.assertEqual('com.pants.examples.temperature', proto_parser_wire.package)
        self.assertEqual(set(['Temperature']), proto_parser_wire.types)

  @contextmanager
  def test_parse_for_wire(self):
    with temporary_dir() as workdir:
      with open(os.path.join(workdir, "distances.proto"), 'w') as fd:
        fd.write(
          '''
            package com.pants.examples.distance;
            message Distance {
              optional string unit = 1;
              required int64 number = 2;
            }
          '''
        )
        fd.close()
        proto_parser_protoc =  ProtobufParse('protoc', fd.name, 'distances.proto')
        proto_parser_protoc.parse()
        self.assertEqual('com.pants.examples.distance', proto_parser_protoc.package)
        self.assertEqual(set([]), proto_parser_protoc.types)
        self.assertEqual('Distances', proto_parser_protoc.outer_class_name)

  def test_update_type_list(self):
    match = TYPE_PARSER.match('message Temperature {')

    expected_value = set()
    expected_value.add('Temperature')
    actual_value = set()
    update_type_list('wire', match, 0, actual_value)
    self.assertEqual(expected_value, actual_value)

    expected_value.add('TemperatureOrBuilder')
    actual_value = set()
    update_type_list('protoc', match, 0, actual_value)
    self.assertEqual(expected_value, actual_value)

  def get_outer_class_name(self, source):
    self.assertEqual('Distances', get_outer_class_name('distances.java'))

  def test_camelcase(self):
    self.assertEqual('TestingOut', camelcase('testing_out'))
