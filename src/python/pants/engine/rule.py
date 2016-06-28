# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from abc import abstractmethod, abstractproperty

from pants.util.meta import AbstractClass


class Rule(AbstractClass):
  """This abstract class represents rules and their common properties.

   The idea is that the scheduler can lean on this abstraction to figure out how to create nodes
   from the tasks or intrinsics it supports.

   Rules are horn clauses where the output_product_type is the left hand side and the input selects
   are the right hand side (If you squint at them a bit)."""

  @abstractmethod
  def as_node(self, subject, product_type, variants):
    pass

  @abstractproperty
  def output_product_type(self):
    """The left hand side type of the horn clause this rule represents."""

  @abstractproperty
  def input_selects(self):
    """The input types for the right hand side expression of this rule."""
