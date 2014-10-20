# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from textwrap import dedent

from pants.backend.codegen.targets.java_wire_library import JavaWireLibrary
from pants.base.address import SyntheticAddress
from pants_test.base_test import BaseTest


class JavaWireLibraryTest(BaseTest):

  def setUp(self):
    super(JavaWireLibraryTest, self).setUp()
    self.build_file_parser._build_configuration.register_target_alias('java_wire_library', JavaWireLibrary)
    self.add_to_build_file('BUILD', dedent('''
      java_wire_library(name='foo',
        sources=[],
      )'''))
    self.build_graph.inject_spec_closure('//:foo')
    self.target = self.build_graph.get_target(SyntheticAddress.parse('//:foo'))

  def test_empty(self):
    self.assertIsInstance(self.target, JavaWireLibrary)
    traversable_specs = [seq for seq in self.target.traversable_specs]
    self.assertSequenceEqual([], traversable_specs)

  def test_fields(self):
      assert self.target.payload.get_field('service_writer') is not None
      assert self.target.payload.get_field('service_writer_options') is not None
      assert self.target.payload.get_field('roots') is not None

  def test_label_fields(self):
      self.assertTrue(self.target.has_label('codegen'))
      self.assertTrue(self.target.has_label('exportable'))
