# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest
from textwrap import dedent

from pants.engine.addressable import Exactly
from pants.engine.rules import NodeBuilder, Rule, RulesetValidator
from pants.engine.selectors import Select
from pants_test.engine.examples.planners import Goal


class AGoal(Goal):

  @classmethod
  def products(cls):
    return [A]


class A(object):

  def __repr__(self):
    return 'A()'


class B(object):

  def __repr__(self):
    return 'B()'


def noop(*args):
  pass


class SubA(A):

  def __repr__(self):
    return 'SubA()'


class IntrinsicProvider(object):
  def __init__(self, intrinsics):
    self.intrinsics = intrinsics

  def as_intrinsics(self):
    return self.intrinsics


class BoringRule(Rule):
  input_selectors = tuple()

  def __init__(self, product_type):
    self._output_product_type = product_type

  @property
  def output_product_type(self):
    return self._output_product_type

  def as_node(self, subject, variants):
    raise Exception('do not expect to be constructed')

  def __repr__(self):
    return '{}({})'.format(type(self).__name__, self.output_product_type.__name__)


class NodeBuilderTest(unittest.TestCase):
  def test_creation_fails_with_bad_declaration_type(self):
    with self.assertRaises(TypeError) as cm:
      NodeBuilder.create([A()])
    self.assertEquals("Unexpected rule type: <class 'pants_test.engine.test_rules.A'>."
                      " Rules either extend Rule, or are 3 elem tuples.",
      str(cm.exception))

  def test_creation_fails_with_intrinsic_that_overwrites_another_intrinsic(self):
    a_provider = IntrinsicProvider({(A, A): BoringRule(A)})
    with self.assertRaises(ValueError):
      NodeBuilder.create([BoringRule(A)], intrinsic_providers=(a_provider, a_provider))


class RulesetValidatorTest(unittest.TestCase):
  def test_ruleset_with_missing_product_type(self):
    rules = [(A, (Select(B),), noop)]
    validator = RulesetValidator(NodeBuilder.create(rules),
      goal_to_product=dict(),
      root_subject_types=tuple())
    with self.assertRaises(ValueError) as cm:
      validator.validate()

    self.assertEquals(dedent("""
                                Found 1 rules with errors:
                                  (A, (Select(B),), noop)
                                    There is no producer of Select(B)
                             """).strip(),
      str(cm.exception))

  def test_ruleset_with_rule_with_two_missing_selects(self):
    rules = [(A, (Select(B), Select(B)), noop)]
    validator = RulesetValidator(NodeBuilder.create(rules),
      goal_to_product=dict(),
      root_subject_types=tuple())
    with self.assertRaises(ValueError) as cm:
      validator.validate()

    self.assertEquals(dedent("""
                                Found 1 rules with errors:
                                  (A, (Select(B), Select(B)), noop)
                                    There is no producer of Select(B)
                                    There is no producer of Select(B)
                             """).strip(),
      str(cm.exception))

  def test_ruleset_with_with_selector_only_provided_as_root_subject(self):

    validator = RulesetValidator(NodeBuilder.create([(A, (Select(B),), noop)]),
      goal_to_product=dict(),
      root_subject_types=(B,))

    validator.validate()

  def test_ruleset_with_superclass_of_selected_type_produced_fails(self):

    rules = [
      (A, (Select(B),), noop),
      (B, (Select(SubA),), noop)
    ]
    validator = RulesetValidator(NodeBuilder.create(rules),
      goal_to_product=dict(),
      root_subject_types=tuple())

    with self.assertRaises(ValueError) as cm:
      validator.validate()
    self.assertEquals(dedent("""
                                Found 1 rules with errors:
                                  (B, (Select(SubA),), noop)
                                    There is no producer of Select(SubA)
                             """).strip(), str(cm.exception))

  def test_ruleset_with_goal_not_produced(self):
    rules = [
      (B, (Select(SubA),), noop)
    ]

    validator = RulesetValidator(NodeBuilder.create(rules),
      goal_to_product={'goal-name': AGoal},
      root_subject_types=tuple())
    with self.assertRaises(ValueError) as cm:
      validator.validate()

    self.assertEquals("no task for product used by goal \"goal-name\": <class 'pants_test.engine.test_rules.AGoal'>",
                      str(cm.exception))

  def test_ruleset_with_explicit_type_constraint(self):
    rules = [
      (Exactly(A), (Select(B),), noop),
      (B, (Select(A),), noop)
    ]
    validator = RulesetValidator(NodeBuilder.create(rules),
      goal_to_product=dict(),
      root_subject_types=tuple())

    validator.validate()
