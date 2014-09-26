# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.backend.core.wrapped_globs import Globs
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.base.build_file_aliases import BuildFileAliases
from pants.base.exceptions import TargetDefinitionException
from pants.base.payload import Payload, PayloadFieldAlreadyDefinedError, PayloadFrozenError
from pants.base.payload_field import PrimitiveField
from pants_test.base_test import BaseTest


class PayloadTest(BaseTest):
  @property
  def alias_groups(self):
    return BuildFileAliases.create(
      targets={
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
    with self.assertRaises(TargetDefinitionException):
      self.context().scan(self.build_root)

  def test_flat_globs_list(self):
    # flattened allowed
    self.add_to_build_file('y/BUILD', 'java_library(name="y", sources=globs("*"))')
    self.context().scan(self.build_root)

  def test_single_source(self):
    self.add_to_build_file('y/BUILD', 'java_library(name="y", sources=["Source.scala"])')
    self.context().scan(self.build_root)
