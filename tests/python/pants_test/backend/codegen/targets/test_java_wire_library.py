# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from textwrap import dedent

from pants.backend.codegen.targets.java_wire_library import JavaWireLibrary
from pants.base.build_file_aliases import BuildFileAliases
from pants_test.base_test import BaseTest


class JavaWireLibraryTest(BaseTest):

  @property
  def alias_groups(self):
    return BuildFileAliases.create(targets={'java_wire_library': JavaWireLibrary})

  def setUp(self):
    super(JavaWireLibraryTest, self).setUp()
    self.add_to_build_file('BUILD', dedent('''
      java_wire_library(name='foo',
        sources=[],
        service_writer='com.squareup.wire.RetrofitServiceWriter'
      )'''))
    self.foo = self.target('//:foo')

  def test_empty(self):
    self.assertIsInstance(self.foo, JavaWireLibrary)

  def test_fields(self):
    self.assertEqual('com.squareup.wire.RetrofitServiceWriter',
                     self.foo.payload.get_field_value('service_writer'))
    self.assertEqual([], self.foo.payload.get_field_value('service_writer_options'))
    self.assertEqual([], self.foo.payload.get_field_value('roots'))

  def test_label_fields(self):
    self.assertTrue(self.foo.has_label('codegen'))
    self.assertTrue(self.foo.has_label('exportable'))
