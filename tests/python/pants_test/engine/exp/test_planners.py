# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest
from collections import namedtuple

from pants.engine.exp.scheduler import PartiallyConsumedInputsError, Planners, Select


class PlannersTest(unittest.TestCase):

  def planners(self, *planners):
    """Generates a Planners object for synthetic planners defined using only their product reqs.

    Takes a dict mapping addresses to subjects, and a series of Planner.product_types, and
    generates a TaskPlanner per entry.
    """
    def mk_planners():
      for idx, product_types in enumerate(planners):
        name = b'Planner{}'.format(idx)
        cls = type(name, (object,), {'goal_name': name, 'product_types': product_types})
        yield cls()
    return Planners(list(mk_planners()))

  def products_for(self, planners, subject, root_products):
    product_graph = planners.product_graph(None, [subject], root_products)
    return product_graph.products_for(subject)

  def assert_products_for(self, planners, expected_products, subject, root_products):
    self.assertEquals(expected_products, self.products_for(planners, subject, root_products))

  def test_produced_types_transitive(self):
    class A(object): pass
    class B(object): pass
    class C(object): pass
    class D(object): pass

    ps = self.planners({A: [[Select(Select.Subject(), B)]]},
                       {B: [[Select(Select.Subject(), C)]]})

    # Product A can be produced given either A, B, or C.
    self.assert_products_for(ps, {A}, A(), [A, D])
    self.assert_products_for(ps, {A, B}, B(), [A, D])
    self.assert_products_for(ps, {A, B, C}, C(), [A, D])
    # D can only be produced if it is already present.
    self.assert_products_for(ps, {D}, D(), [A, D])

  def test_produced_types_partially_consumed(self):
    class A(object): pass
    class B(object): pass
    class C(object): pass
    class D(object): pass
    class E(object): pass

    # Represents two alternatives for generating a product B using a product C, both of
    # which require an additional product (E and D, respectively).
    ps = self.planners({A: [[Select(Select.Subject(), B)]]},
                       {B: [[Select(Select.Subject(), C), Select(Select.Subject(), D)]]},
                       {B: [[Select(Select.Subject(), C), Select(Select.Subject(), E)]]})

    # Should receive a PartiallyConsumedInputs error, because no Planner can (recursively)
    # consume C to produce A.
    with self.assertRaises(PartiallyConsumedInputsError):
      self.products_for(ps, C(), [A])
