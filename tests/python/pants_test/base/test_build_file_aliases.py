# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pants.base.build_file_aliases import BuildFileAliases
from pants.base.target import Target


class BuildFileAliasesTest(unittest.TestCase):
  def test_create(self):
    self.assertEqual(BuildFileAliases(targets={},
                                      objects={},
                                      context_aware_object_factories={},
                                      anonymous_targets=set()),
                     BuildFileAliases.create())

    targets = {'jake': Target}
    self.assertEqual(BuildFileAliases(targets=targets,
                                      objects={},
                                      context_aware_object_factories={},
                                      anonymous_targets=set()),
                     BuildFileAliases.create(targets=targets))

    objects = {'jane': 42}
    self.assertEqual(BuildFileAliases(targets={},
                                      objects=objects,
                                      context_aware_object_factories={},
                                      anonymous_targets=set()),
                     BuildFileAliases.create(objects=objects))

    factories = {'jim': lambda ctx: 'bob'}
    self.assertEqual(BuildFileAliases(targets={},
                                      objects={},
                                      context_aware_object_factories=factories,
                                      anonymous_targets=set()),
                     BuildFileAliases.create(context_aware_object_factories=factories))

    anonymous_targets = {Target}
    self.assertEqual(BuildFileAliases(targets={},
                                      objects={},
                                      context_aware_object_factories={},
                                      anonymous_targets=anonymous_targets),
                     BuildFileAliases.create(anonymous_targets=anonymous_targets))

    self.assertEqual(BuildFileAliases(targets=targets,
                                      objects=objects,
                                      context_aware_object_factories={},
                                      anonymous_targets=set()),
                     BuildFileAliases.create(targets=targets, objects=objects))

    self.assertEqual(BuildFileAliases(targets=targets,
                                      objects={},
                                      context_aware_object_factories=factories,
                                      anonymous_targets=set()),
                     BuildFileAliases.create(targets=targets,
                                             context_aware_object_factories=factories))

    self.assertEqual(BuildFileAliases(targets={},
                                      objects=objects,
                                      context_aware_object_factories=factories,
                                      anonymous_targets=set()),
                     BuildFileAliases.create(objects=objects,
                                             context_aware_object_factories=factories))

    self.assertEqual(BuildFileAliases(targets=targets,
                                      objects=objects,
                                      context_aware_object_factories=factories,
                                      anonymous_targets=set()),
                     BuildFileAliases.create(targets=targets,
                                             objects=objects,
                                             context_aware_object_factories=factories))

  def test_curry_context(self):
    def curry_me(ctx, bob):
      """original doc"""
      return ctx, bob

    curried = BuildFileAliases.curry_context(curry_me)
    func = curried(42)

    self.assertEqual('original doc', curried.__doc__)
    self.assertTrue('curry_me' in curried.__name__,
                    'Unhelpful __name__: ' + curried.__name__)
    self.assertEqual((42, 'fred'), func('fred'))

  def test_merge(self):
    e_factory = lambda ctx: 'e'
    f_factory = lambda ctx: 'f'

    first = BuildFileAliases(targets={'a': Target},
                             objects={'d': 2},
                             context_aware_object_factories={'e': e_factory},
                             anonymous_targets=set())

    second = BuildFileAliases(targets={},
                              objects={'c': 1, 'd': 42},
                              context_aware_object_factories={'f': f_factory},
                              anonymous_targets=set())

    expected = BuildFileAliases(
        # nothing to merge
        targets={'a': Target},
        # second overrides first
        objects={'c': 1, 'd': 42},
        # combine
        context_aware_object_factories={'e': e_factory, 'f': f_factory},
        # empty
        anonymous_targets=set())
    self.assertEqual(expected, first.merge(second))
