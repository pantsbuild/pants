# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.payload import Payload
from pants.base.payload_field import DeferredSourcesField
from pants.base.target import Target
from pants_test.base_test import BaseTest
from pants_test.subsystem.subsystem_util import subsystem_instance


class TestDeferredSourcesTarget(Target):
  def __init__(self, deferred_sources_address=None, *args, **kwargs):
    payload = Payload()
    payload.add_fields({
      'def_sources': DeferredSourcesField(ref_address=deferred_sources_address),
    })
    super(TestDeferredSourcesTarget, self).__init__(payload=payload, *args, **kwargs)


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

  def test_empty_traversable_properties(self):
    target = self.make_target(':foo', Target)
    self.assertSequenceEqual([], list(target.traversable_specs))
    self.assertSequenceEqual([], list(target.traversable_dependency_specs))

  def test_deferred_sources_payload_field(self):
    foo = self.make_target(':foo', Target)
    target = self.make_target(':bar',
                              TestDeferredSourcesTarget,
                              deferred_sources_address=foo.address)
    self.assertSequenceEqual([], list(target.traversable_specs))
    self.assertSequenceEqual([':foo'], list(target.traversable_dependency_specs))

  def test_illegal_kwargs(self):
    with subsystem_instance(Target.UnknownArguments):
      with self.assertRaises(Target.UnknownArguments.Error) as cm:
        self.make_target('foo:bar', Target, foobar='barfoo')
      self.assertTrue('foobar = barfoo' in str(cm.exception))
      self.assertTrue('foo:bar' in str(cm.exception))

  def test_unknown_kwargs(self):
    options = {Target.UnknownArguments.options_scope: {'ignored': {'Target': ['foobar']}}}
    with subsystem_instance(Target.UnknownArguments, options=options):
      target = self.make_target('foo:bar', Target, foobar='barfoo')
      self.assertFalse(hasattr(target, 'foobar'))
