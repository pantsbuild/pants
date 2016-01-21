# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.base.payload import Payload, PayloadFieldAlreadyDefinedError, PayloadFrozenError
from pants.base.payload_field import PrimitiveField
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.source.wrapped_globs import Globs
from pants_test.base_test import BaseTest


class PayloadTest(BaseTest):

  @property
  def alias_groups(self):
    return BuildFileAliases(
      targets={
        # TODO: Use a dummy task type here, instead of depending on the jvm backend.
        'java_library': JavaLibrary,
      },
      context_aware_object_factories={
        'globs': Globs,
      },
    )

  def test_freeze(self):
    payload = Payload()
    payload.add_field('foo', PrimitiveField())
    payload.freeze()
    with self.assertRaises(PayloadFrozenError):
      payload.add_field('bar', PrimitiveField())

  def test_field_duplication(self):
    payload = Payload()
    payload.add_field('foo', PrimitiveField())
    payload.freeze()
    with self.assertRaises(PayloadFieldAlreadyDefinedError):
      payload.add_field('foo', PrimitiveField())

  def test_fingerprint(self):
    payload = Payload()
    payload.add_field('foo', PrimitiveField())
    fingerprint1 = payload.fingerprint()
    self.assertEqual(fingerprint1, payload.fingerprint())
    payload.add_field('bar', PrimitiveField())
    fingerprint2 = payload.fingerprint()
    self.assertNotEqual(fingerprint1, fingerprint2)
    self.assertEqual(fingerprint2, payload.fingerprint())
    payload.freeze()
    self.assertEqual(fingerprint2, payload.fingerprint())

  def test_partial_fingerprint(self):
    payload = Payload()
    payload.add_field('foo', PrimitiveField())
    fingerprint1 = payload.fingerprint()
    self.assertEqual(fingerprint1, payload.fingerprint(field_keys=('foo',)))
    payload.add_field('bar', PrimitiveField())
    fingerprint2 = payload.fingerprint()
    self.assertEqual(fingerprint1, payload.fingerprint(field_keys=('foo',)))
    self.assertNotEqual(fingerprint2, payload.fingerprint(field_keys=('foo',)))
    self.assertNotEqual(fingerprint2, payload.fingerprint(field_keys=('bar',)))
    self.assertEqual(fingerprint2, payload.fingerprint(field_keys=('bar', 'foo')))

  def test_none(self):
    payload = Payload()
    payload.add_field('foo', None)
    payload2 = Payload()
    payload2.add_field('foo', PrimitiveField(None))
    self.assertNotEqual(payload.fingerprint(), payload2.fingerprint())

  def test_no_nested_globs(self):
    # nesting no longer allowed
    self.add_to_build_file('z/BUILD', 'java_library(name="z", sources=[globs("*")])')
    with self.assertRaises(ValueError):
      self.context().scan()

  def test_flat_globs_list(self):
    # flattened allowed
    self.add_to_build_file('y/BUILD', 'java_library(name="y", sources=globs("*"))')
    self.context().scan()

  def test_single_source(self):
    self.add_to_build_file('y/BUILD', 'java_library(name="y", sources=["Source.scala"])')
    self.context().scan()

  def test_missing_payload_field(self):
    payload = Payload()
    payload.add_field('foo', PrimitiveField('test-value'))
    payload.add_field('bar', PrimitiveField(None))
    self.assertEquals('test-value', payload.foo);
    self.assertEquals('test-value', payload.get_field('foo').value)
    self.assertEquals('test-value', payload.get_field_value('foo'))
    self.assertEquals(None, payload.bar);
    self.assertEquals(None, payload.get_field('bar').value)
    self.assertEquals(None, payload.get_field_value('bar'))
    self.assertEquals(None, payload.get_field('bar', default='nothing').value)
    self.assertEquals(None, payload.get_field_value('bar', default='nothing'))
    with self.assertRaises(KeyError):
      self.assertEquals(None, payload.field_doesnt_exist)
    self.assertEquals(None, payload.get_field('field_doesnt_exist'))
    self.assertEquals(None, payload.get_field_value('field_doesnt_exist'))
    self.assertEquals('nothing', payload.get_field('field_doesnt_exist', default='nothing'))
    self.assertEquals('nothing', payload.get_field_value('field_doesnt_exist', default='nothing'))
