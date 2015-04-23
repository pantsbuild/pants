# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from textwrap import dedent

from pants.backend.core.wrapped_globs import Globs
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.base.address import BuildFileAddress, SyntheticAddress
from pants.base.build_file_aliases import BuildFileAliases
from pants.base.payload import Payload
from pants.base.payload_field import DeferredSourcesField
from pants.base.target import Target
from pants_test.base_test import BaseTest


class TestDeferredSourcesTarget(Target):
  def __init__(self, deferred_sources_address=None, *args, **kwargs):
    payload = Payload()
    payload.add_fields({
      'def_sources': DeferredSourcesField(ref_address=deferred_sources_address),
    })
    super(TestDeferredSourcesTarget, self).__init__(payload=payload, *args, **kwargs)

class TargetTest(BaseTest):
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

  def test_derived_from_chain(self):
    context = self.context()

    # add concrete target
    build_file = self.add_to_build_file('y/BUILD', dedent('''
    java_library(
      name='concrete',
      sources=['SourceA.scala'],
    )
    '''))
    concrete_address = BuildFileAddress(build_file, 'concrete')
    context.build_graph.inject_address_closure(concrete_address)
    concrete = context.build_graph.get_target(concrete_address)

    # add synthetic targets
    syn_one = context.add_new_target(SyntheticAddress('y', 'syn_one'),
                                     JavaLibrary,
                                     derived_from=concrete,
                                     sources=["SourceB.scala"])
    syn_two = context.add_new_target(SyntheticAddress('y', 'syn_two'),
                                     JavaLibrary,
                                     derived_from=syn_one,
                                     sources=["SourceC.scala"])

    # validate
    self.assertEquals(list(syn_two.derived_from_chain), [syn_one, concrete])
    self.assertEquals(list(syn_one.derived_from_chain), [concrete])
    self.assertEquals(list(concrete.derived_from_chain), [])

  def test_empty_traversable_properties(self):
    build_file = self.add_to_build_file('BUILD', dedent('''
    java_library(
      name='foo',
      sources=["foo.java"],
    )
    '''))
    self.build_graph.inject_address_closure(BuildFileAddress(build_file, 'foo'))
    target = self.build_graph.get_target(SyntheticAddress.parse('//:foo'))
    self.assertSequenceEqual([], list(target.traversable_specs))
    self.assertSequenceEqual([], list(target.traversable_dependency_specs))

  def test_deferred_sources_payload_field(self):
    target = TestDeferredSourcesTarget(name='bar', address=SyntheticAddress.parse('//:bar'),
                                       build_graph=self.build_graph,
                                       deferred_sources_address=SyntheticAddress.parse('//:foo'))
    self.assertSequenceEqual([], list(target.traversable_specs))
    self.assertSequenceEqual([':foo'], list(target.traversable_dependency_specs))

  def test_unknown_arg(self):
    Target.clear_all_parameters()
    with self.assertRaises(Target.UnknownParameter) as t:
      target = Target(name='t', address=SyntheticAddress.parse('//:t'), build_graph=self.build_graph, oops=1)
    self.assertEqual(t.exception.name, 'oops')

  def test_simple_arg(self):
    Target.clear_all_parameters()
    Target.register_parameter('x_str', str)
    Target.register_parameter('x_int', int)

    target = Target(
      name='t',
      address=SyntheticAddress.parse('//:t'),
      build_graph=self.build_graph,
      x_str='forty two',
      x_int=42
    )

    self.assertEqual(target.params['x_str'], 'forty two')
    self.assertEqual(target.params['x_int'], 42)

  def test_bad_arg(self):
    Target.clear_all_parameters()
    Target.register_parameter('x_int', int)

    with self.assertRaises(ValueError):
      target = Target(
        name='t',
        address=SyntheticAddress.parse('//:t'),
        build_graph=self.build_graph,
        x_int='forty two'
      )

  def test_multi_class(self):

    class Target_(Target):
      @classmethod
      def create(cls, name, **kwargs):
        return cls(
          name=name,
          address=SyntheticAddress.parse('//:{0}'.format(name)),
          build_graph=self.build_graph,
          **kwargs
        )

    class TargetA(Target_):
      pass

    class TargetB(Target_):
      pass

    class TargetC(TargetB):
      pass

    Target.clear_all_parameters()

    Target.register_parameter('x', int)
    TargetA.register_parameter('a', int)
    TargetB.register_parameter('b', int)

    with self.assertRaises(Target.ParamRegistrationConflict) as et:
      Target.register_parameter('x', int)
    self.assertEqual(et.exception.opponent, Target)

    with self.assertRaises(Target.ParamRegistrationConflict) as ex:
      TargetA.register_parameter('x', int)
    self.assertEqual(ex.exception.opponent, Target)

    with self.assertRaises(Target.ParamRegistrationConflict) as eb:
      TargetC.register_parameter('b', int)
    self.assertEqual(eb.exception.opponent, TargetB)

    t = Target_.create(name='x', x=42)
    self.assertEquals(t.params['x'], 42)

    with self.assertRaises(Target.UnknownParameter) as t:
      Target_.create(name='b', a=1)

    t = TargetA.create(name='a', a=2)
    self.assertEquals(t.params['a'], 2)

    t = TargetB.create(name='b', b=3)
    self.assertEquals(t.params['b'], 3)

    t = TargetC.create(name='c', b=4)
    self.assertEquals(t.params['b'], 4)

