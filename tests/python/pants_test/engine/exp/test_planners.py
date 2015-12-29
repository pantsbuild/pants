# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest
from collections import namedtuple

from pants.engine.exp.scheduler import PartiallyConsumedInputsError, Planners


class PlannersTest(unittest.TestCase):

  def planners(self, *planners):
    """Generates a Planners object for synthetic planners defined using only their product reqs.

    Takes a series of Planner.product_types, and generates a TaskPlanner per entry.
    """
    def mk_planners():
      for idx, product_types in enumerate(planners):
        name = b'Planner{}'.format(idx)
        cls = type(name, (object,), {'goal_name': name, 'product_types': product_types})
        yield cls()
    return Planners(list(mk_planners()))

  def test_produced_types(self):
    class A(object): pass
    class B(object): pass
    class C(object): pass
    class D(object): pass

    ps = self.planners({A: [[B]]},
                       {B: [[C]]})

    # Product A can be produced given either A, B, or C.
    self.assertEquals([A], ps.produced_types_for_subject(subject=A(),
                                                         output_product_types=[A, D]))
    self.assertEquals([A], ps.produced_types_for_subject(subject=B(),
                                                         output_product_types=[A, D]))
    self.assertEquals([A], ps.produced_types_for_subject(subject=C(),
                                                         output_product_types=[A, D]))
    # D can only be produced if it is already present.
    self.assertEquals([D], ps.produced_types_for_subject(subject=D(),
                                                         output_product_types=[A, D]))

  def test_produced_types_partially_consumed(self):
    class A(object): pass
    class B(object): pass
    class C(object): pass
    class D(object): pass
    class E(object): pass

    # Represents two alternatives for generating a product B using a product C, both of
    # which require an additional product (E and D, respectively).
    ps = self.planners({A: [[B]]},
                       {B: [[C, D]]},
                       {B: [[C, E]]})

    # Should receive a PartiallyConsumedInputs error, because no Planner can (recursively)
    # consume C to product A.
    with self.assertRaises(PartiallyConsumedInputsError):
      ps.produced_types_for_subject(subject=C(),
                                    output_product_types=[A])
