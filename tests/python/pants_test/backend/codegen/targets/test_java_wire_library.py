# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.codegen.targets.java_wire_library import JavaWireLibrary
from pants.base.exceptions import TargetDefinitionException
from pants_test.base_test import BaseTest


class JavaWireLibraryTest(BaseTest):

  def setUp(self):
    super(JavaWireLibraryTest, self).setUp()

  def test_fields(self):
    target = self.make_target('//:foo', JavaWireLibrary,
                              registry_class='com.squareup.Registry',
                              roots=['foo', 'bar'],
                              enum_options=['one', 'two', 'three'],
                              service_writer='com.squareup.wire.RetrofitServiceWriter')
    self.assertEqual('com.squareup.Registry', target.payload.get_field_value('registry_class'))
    self.assertEqual(['foo', 'bar'], target.payload.get_field_value('roots'))
    self.assertEqual(['one', 'two', 'three'], target.payload.get_field_value('enum_options'))
    self.assertFalse(target.payload.get_field_value('no_options'))
    self.assertEqual('com.squareup.wire.RetrofitServiceWriter',
                     target.payload.get_field_value('service_writer'))
    self.assertEqual([], target.payload.get_field_value('service_writer_options'))
    self.assertIsNone(target.payload.get_field_value('service_factory'))
    self.assertEqual([], target.payload.get_field_value('service_factory_options'))

  def test_label_fields(self):
    target = self.make_target('//:foo', JavaWireLibrary)
    self.assertTrue(target.has_label('codegen'))
    self.assertTrue(target.has_label('exportable'))

  def test_wire_service_options(self):
    target = self.make_target('//:wire_service_options', JavaWireLibrary,
                              service_writer='com.squareup.wire.RetrofitServiceWriter',
                              service_writer_options=['foo', 'bar', 'baz'])
    self.assertEquals(['foo', 'bar', 'baz'], target.payload.service_writer_options)

  def test_wire_factory_options(self):
    target = self.make_target('opts:factory_opts_test', JavaWireLibrary,
                              service_factory='com.squareup.wire.java.SimpleServiceFactory',
                              service_factory_options=['arg1', 'arg2'])
    self.assertIsNone(target.payload.get_field_value('service_writer'))
    self.assertEqual([], target.payload.get_field_value('service_writer_options'))
    self.assertEqual('com.squareup.wire.java.SimpleServiceFactory',
                     target.payload.get_field_value('service_factory'))
    self.assertEquals(['arg1', 'arg2'], target.payload.service_factory_options)

  def test_invalid_service_opts(self):
    with self.assertRaisesRegexp(TargetDefinitionException,
                                 r'Specify only one of "service_writer".*or "service_factory"'):
      self.make_target('invalid:both', JavaWireLibrary,
                       service_writer='com.squareup.wire.RetrofitServiceWriter',
                       service_factory='com.squareup.wire.SimpleServiceFactory')

  def test_invalid_service_writer_opts(self):
    with self.assertRaisesRegexp(TargetDefinitionException,
                                 r'service_writer_options requires setting service_writer'):
      self.make_target('invalid:service_writer_opts', JavaWireLibrary,
                       service_writer_options=['one', 'two'])

  def test_invalid_service_factory_opts(self):
    with self.assertRaisesRegexp(TargetDefinitionException,
                                 r'service_factory_options requires setting service_factory'):
      self.make_target('invalid:service_factory_opts', JavaWireLibrary,
                       service_factory_options=['one', 'two'])
