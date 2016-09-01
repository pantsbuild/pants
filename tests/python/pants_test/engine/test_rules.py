# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pants.engine.rules import NodeBuilder, RulesetValidator
from pants.engine.selectors import Select
from pants_test.engine.examples.planners import Goal


class AGoal(Goal):

  @classmethod
  def products(cls):
    return [A]


class A(object):
  pass


class B(object):
  pass


def noop(*args):
  pass


class SubA(A):
  pass


class RulesetValidatorTest(unittest.TestCase):
  def test_ruleset_with_missing_product_type(self):
    validator = RulesetValidator(NodeBuilder.create([(A, (Select(B),), noop)]),
      goal_to_product=dict(),
      root_subject_types=tuple())
    with self.assertRaises(ValueError):
      validator.validate()

  def test_ruleset_with_with_selector_only_provided_as_root_subject(self):

    validator = RulesetValidator(NodeBuilder.create([(A, (Select(B),), noop)]),
      goal_to_product=dict(),
      root_subject_types=(B,))

    validator.validate()

  def test_ruleset_with_superclass_of_selected_type_produced(self):

    rules = [
      (A, (Select(B),), noop),
      (B, (Select(SubA),), noop)
    ]
    validator = RulesetValidator(NodeBuilder.create(rules),
      goal_to_product=dict(),
      root_subject_types=tuple())

    validator.validate()

  def test_ruleset_with_goal_not_produced(self):

    rules = [
      (B, (Select(SubA),), noop)
    ]
    validator = RulesetValidator(NodeBuilder.create(rules),
      goal_to_product={'goal-name': AGoal},
      root_subject_types=tuple())
    with self.assertRaises(ValueError):
      validator.validate()
