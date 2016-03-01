# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest

from pants.build_graph.address import Address
from pants.build_graph.build_file_aliases import BuildFileAliases, TargetMacro
from pants.build_graph.mutable_build_graph import MutableBuildGraph
from pants.build_graph.target import Target


class BuildFileAliasesTest(unittest.TestCase):

  class RedTarget(Target):
    pass

  class BlueTarget(Target):
    pass

  def setUp(self):
    self.target_macro_factory = TargetMacro.Factory.wrap(
      lambda ctx: ctx.create_object(self.BlueTarget,
                                    type_alias='jill',
                                    name=os.path.basename(ctx.rel_path)),
      self.BlueTarget, self.RedTarget)

  def test_create(self):
    self.assertEqual(BuildFileAliases(targets={},
                                      objects={},
                                      context_aware_object_factories={}),
                     BuildFileAliases())

    targets = {'jake': Target, 'jill': self.target_macro_factory}
    self.assertEqual(BuildFileAliases(targets=targets,
                                      objects={},
                                      context_aware_object_factories={}),
                     BuildFileAliases(targets=targets))

    objects = {'jane': 42}
    self.assertEqual(BuildFileAliases(targets={},
                                      objects=objects,
                                      context_aware_object_factories={}),
                     BuildFileAliases(objects=objects))

    factories = {'jim': lambda ctx: 'bob'}
    self.assertEqual(BuildFileAliases(targets={},
                                      objects={},
                                      context_aware_object_factories=factories),
                     BuildFileAliases(context_aware_object_factories=factories))

    self.assertEqual(BuildFileAliases(targets=targets,
                                      objects=objects,
                                      context_aware_object_factories={}),
                     BuildFileAliases(targets=targets, objects=objects))

    self.assertEqual(BuildFileAliases(targets=targets,
                                      objects={},
                                      context_aware_object_factories=factories),
                     BuildFileAliases(targets=targets,
                                      context_aware_object_factories=factories))

    self.assertEqual(BuildFileAliases(targets={},
                                      objects=objects,
                                      context_aware_object_factories=factories),
                     BuildFileAliases(objects=objects,
                                      context_aware_object_factories=factories))

    self.assertEqual(BuildFileAliases(targets=targets,
                                      objects=objects,
                                      context_aware_object_factories=factories),
                     BuildFileAliases(targets=targets,
                                      objects=objects,
                                      context_aware_object_factories=factories))

  def test_create_bad_targets(self):
    with self.assertRaises(TypeError):
      BuildFileAliases(targets={'fred': object()})

    target = Target('fred', Address.parse('a:b'), MutableBuildGraph(address_mapper=None))
    with self.assertRaises(TypeError):
      BuildFileAliases(targets={'fred': target})

  def test_create_bad_objects(self):
    with self.assertRaises(TypeError):
      BuildFileAliases(objects={'jane': Target})

    with self.assertRaises(TypeError):
      BuildFileAliases(objects={'jane': self.target_macro_factory})

  def test_bad_context_aware_object_factories(self):
    with self.assertRaises(TypeError):
      BuildFileAliases(context_aware_object_factories={'george': 1})

  def test_merge(self):
    e_factory = lambda ctx: 'e'
    f_factory = lambda ctx: 'f'

    first = BuildFileAliases(targets={'a': Target},
                             objects={'d': 2},
                             context_aware_object_factories={'e': e_factory})

    second = BuildFileAliases(targets={'b': self.target_macro_factory},
                              objects={'c': 1, 'd': 42},
                              context_aware_object_factories={'f': f_factory})

    expected = BuildFileAliases(
        # nothing to merge
        targets={'a': Target, 'b': self.target_macro_factory},
        # second overrides first
        objects={'c': 1, 'd': 42},
        # combine
        context_aware_object_factories={'e': e_factory, 'f': f_factory})
    self.assertEqual(expected, first.merge(second))

  def test_target_types(self):
    aliases = BuildFileAliases(targets={'jake': Target, 'jill': self.target_macro_factory})
    self.assertEqual({'jake': Target}, aliases.target_types)

  def test_target_macro_factories(self):
    aliases = BuildFileAliases(targets={'jake': Target, 'jill': self.target_macro_factory})
    self.assertEqual({'jill': self.target_macro_factory}, aliases.target_macro_factories)

  def test_target_types_by_alias(self):
    aliases = BuildFileAliases(targets={'jake': Target, 'jill': self.target_macro_factory})
    self.assertEqual({'jake': {Target}, 'jill': {self.BlueTarget, self.RedTarget}},
                     aliases.target_types_by_alias)
