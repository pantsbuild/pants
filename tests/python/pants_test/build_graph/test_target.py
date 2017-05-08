# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os.path
from hashlib import sha1

from pants.base.exceptions import TargetDefinitionException
from pants.base.fingerprint_strategy import DefaultFingerprintStrategy
from pants.build_graph.address import Address
from pants.build_graph.target import Target
from pants_test.base_test import BaseTest
from pants_test.subsystem.subsystem_util import init_subsystem


class ImplicitSourcesTestingTarget(Target):
  default_sources_globs = '*.foo'


class ImplicitSourcesTestingTargetMulti(Target):
  default_sources_globs = ('*.foo', '*.bar')
  default_sources_exclude_globs = ('*.baz', '*.qux')


class TargetTest(BaseTest):

  def test_derived_from_chain(self):
    # add concrete target
    concrete = self.make_target('y:concrete', Target)

    # add synthetic targets
    syn_one = self.make_target('y:syn_one', Target, derived_from=concrete)
    syn_two = self.make_target('y:syn_two', Target, derived_from=syn_one)

    # validate
    self.assertEquals(list(syn_two.derived_from_chain), [syn_one, concrete])
    self.assertEquals(list(syn_one.derived_from_chain), [concrete])
    self.assertEquals(list(concrete.derived_from_chain), [])

  def test_is_synthetic(self):
    # add concrete target
    concrete = self.make_target('y:concrete', Target)

    # add synthetic targets
    syn_one = self.make_target('y:syn_one', Target, derived_from=concrete)
    syn_two = self.make_target('y:syn_two', Target, derived_from=syn_one)
    syn_three = self.make_target('y:syn_three', Target, synthetic=True)

    self.assertFalse(concrete.is_synthetic)
    self.assertTrue(syn_one.is_synthetic)
    self.assertTrue(syn_two.is_synthetic)
    self.assertTrue(syn_three.is_synthetic)

  def test_empty_traversable_properties(self):
    target = self.make_target(':foo', Target)
    self.assertSequenceEqual([], list(target.traversable_specs))
    self.assertSequenceEqual([], list(target.compute_dependency_specs(payload=target.payload)))

  def test_illegal_kwargs(self):
    init_subsystem(Target.Arguments)
    with self.assertRaises(Target.Arguments.UnknownArgumentError) as cm:
      self.make_target('foo:bar', Target, foobar='barfoo')
    self.assertTrue('foobar = barfoo' in str(cm.exception))
    self.assertTrue('foo:bar' in str(cm.exception))

  def test_unknown_kwargs(self):
    options = {Target.Arguments.options_scope: {'ignored': {'Target': ['foobar']}}}
    init_subsystem(Target.Arguments, options)
    target = self.make_target('foo:bar', Target, foobar='barfoo')
    self.assertFalse(hasattr(target, 'foobar'))

  def test_target_id_long(self):
    long_path = 'dummy'
    for i in range(1,30):
      long_path = os.path.join(long_path, 'dummy{}'.format(i))
    long_target = self.make_target('{}:foo'.format(long_path), Target)
    long_id = long_target.id
    self.assertEqual(len(long_id), 200)
    self.assertEqual(long_id,
      'dummy.dummy1.dummy2.dummy3.dummy4.dummy5.dummy6.dummy7.dummy8.dummy9.dummy10.du.'
      'c582ce0f60008b3dc8196ae9e6ff5e8c40096974.y20.dummy21.dummy22.dummy23.dummy24.dummy25.'
      'dummy26.dummy27.dummy28.dummy29.foo')

  def test_target_id_short(self):
    short_path = 'dummy'
    for i in range(1,10):
      short_path = os.path.join(short_path, 'dummy{}'.format(i))
    short_target = self.make_target('{}:foo'.format(short_path), Target)
    short_id = short_target.id
    self.assertEqual(short_id,
                     'dummy.dummy1.dummy2.dummy3.dummy4.dummy5.dummy6.dummy7.dummy8.dummy9.foo')

  def test_implicit_sources(self):
    options = {Target.Arguments.options_scope: {'implicit_sources': True}}
    init_subsystem(Target.Arguments, options)
    target = self.make_target(':a', ImplicitSourcesTestingTarget)
    # Note explicit key_arg.
    sources = target.create_sources_field(sources=None, sources_rel_path='src/foo/bar',
                                          key_arg='sources')
    self.assertEqual(sources.filespec, {'globs': ['src/foo/bar/*.foo']})

    target = self.make_target(':b', ImplicitSourcesTestingTargetMulti)
    # Note no explicit key_arg, which should behave just like key_arg='sources'.
    sources = target.create_sources_field(sources=None, sources_rel_path='src/foo/bar')
    self.assertEqual(sources.filespec, {
      'globs': ['src/foo/bar/*.foo', 'src/foo/bar/*.bar'],
      'exclude': [{'globs': ['src/foo/bar/*.baz', 'src/foo/bar/*.qux']}],
    })

    # Ensure that we don't use implicit sources when creating resources fields.
    resources = target.create_sources_field(sources=None, sources_rel_path='src/foo/bar',
                                            key_arg='resources')
    self.assertEqual(resources.filespec, {'globs': []})

  def test_implicit_sources_disabled(self):
    options = {Target.Arguments.options_scope: {'implicit_sources': False}}
    init_subsystem(Target.Arguments, options)
    target = self.make_target(':a', ImplicitSourcesTestingTarget)
    sources = target.create_sources_field(sources=None, sources_rel_path='src/foo/bar')
    self.assertEqual(sources.filespec, {'globs': []})

  def test_create_sources_field_with_string_fails(self):
    target = self.make_target(':a-target', Target)

    # No key_arg.
    with self.assertRaises(TargetDefinitionException) as cm:
      target.create_sources_field(sources='a-string', sources_rel_path='')
    self.assertIn("Expected a glob, an address or a list, but was <type \'unicode\'>",
                  str(cm.exception))

    # With key_arg.
    with self.assertRaises(TargetDefinitionException) as cm:
      target.create_sources_field(sources='a-string', sources_rel_path='', key_arg='my_cool_field')
    self.assertIn("Expected 'my_cool_field' to be a glob, an address or a list, but was <type \'unicode\'>",
                  str(cm.exception))
    #could also test address case, but looks like nothing really uses it.

  def test_max_recursion(self):
    target_a = self.make_target('a', Target)
    target_b = self.make_target('b', Target, dependencies=[target_a])
    self.make_target('c', Target, dependencies=[target_b])
    target_a.inject_dependency(Address.parse('c'))
    with self.assertRaises(Target.RecursiveDepthError):
      target_a.transitive_invalidation_hash()

  def test_transitive_invalidation_hash(self):
    target_a = self.make_target('a', Target)
    target_b = self.make_target('b', Target, dependencies=[target_a])
    target_c = self.make_target('c', Target, dependencies=[target_b])

    hasher = sha1()
    dep_hash = hasher.hexdigest()[:12]
    target_hash = target_a.invalidation_hash()
    hash_value = '{}.{}'.format(target_hash, dep_hash)
    self.assertEqual(hash_value, target_a.transitive_invalidation_hash())

    hasher = sha1()
    hasher.update(hash_value)
    dep_hash = hasher.hexdigest()[:12]
    target_hash = target_b.invalidation_hash()
    hash_value = '{}.{}'.format(target_hash, dep_hash)
    self.assertEqual(hash_value, target_b.transitive_invalidation_hash())

    hasher = sha1()
    hasher.update(hash_value)
    dep_hash = hasher.hexdigest()[:12]
    target_hash = target_c.invalidation_hash()
    hash_value = '{}.{}'.format(target_hash, dep_hash)
    self.assertEqual(hash_value, target_c.transitive_invalidation_hash())

    # Check direct invalidation.
    class TestFingerprintStrategy(DefaultFingerprintStrategy):
      def direct(self, target):
        return True

    fingerprint_strategy = TestFingerprintStrategy()
    hasher = sha1()
    hasher.update(target_b.invalidation_hash(fingerprint_strategy=fingerprint_strategy))
    dep_hash = hasher.hexdigest()[:12]
    target_hash = target_c.invalidation_hash(fingerprint_strategy=fingerprint_strategy)
    hash_value = '{}.{}'.format(target_hash, dep_hash)
    self.assertEqual(hash_value, target_c.transitive_invalidation_hash(fingerprint_strategy=fingerprint_strategy))
