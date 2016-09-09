# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
from abc import abstractmethod, abstractproperty
from os.path import dirname

from pants.base.project_tree import Dir, File, Link
from pants.build_graph.address import Address
from pants.engine.addressable import parse_variants
from pants.engine.fs import (DirectoryListing, FileContent, FileDigest, ReadLink, file_content,
                             file_digest, read_link, scan_directory)
from pants.engine.selectors import Select, SelectVariant
from pants.engine.struct import HasProducts, Variants
from pants.util.meta import AbstractClass
from pants.util.objects import datatype


logger = logging.getLogger(__name__)


def collect_item_of_type(candidate, product, variant_value):
  """Looks for has-a or is-a relationships between the given value and the requested product.

  Returns the resulting product value, or None if no match was made.

  TODO: This is reimplemented in the native SelectNode.
  """
  def items():
    # Check whether the subject is-a instance of the product.
    yield candidate
    # Else, check whether it has-a instance of the product.
    if isinstance(candidate, HasProducts):
      for subject in candidate.products:
        yield subject

  # TODO: returning only the first literal configuration of a given type/variant. Need to
  # define mergeability for products.
  for item in items():

    if not isinstance(item, product):
      continue
    if variant_value and not getattr(item, 'name', None) == variant_value:
      continue
    return item
  return None


class State(AbstractClass):
  @classmethod
  def raise_unrecognized(cls, state):
    raise ValueError('Unrecognized Node State: {}'.format(state))


class Return(datatype('Return', ['value']), State):
  """Indicates that a Node successfully returned a value."""

  @classmethod
  def _from_components(cls, components):
    return cls(components[0])

  def _to_components(self):
    return (self.value,)


class Throw(datatype('Throw', ['exc']), State):
  """Indicates that a Node should have been able to return a value, but failed."""


class Runnable(datatype('Runnable', ['func', 'args', 'cacheable']), State):
  """Indicates that the Node is ready to run with the given closure.

  The return value of the Runnable will become the final state of the Node.
  """


class TransitiveNode(datatype('TransitiveNode', ['subject', 'variants', 'selector']), Node):
  """TODO"""
  is_cacheable = False
  is_inlineable = True

  @property
  def dep_product(self):
    return self.selector.dep_product

  @property
  def product(self):
    return self.selector.product

  @property
  def field(self):
    return self.selector.field

  def _dependency_node(self, step_context, dependency):
    variants = self.variants
    if isinstance(dependency, Address):
      # If a subject has literal variants for particular dependencies, they win over all else.
      dependency, literal_variants = parse_variants(dependency)
      variants = Variants.merge(variants, literal_variants)
    return step_context.select_node(Select(self.product), subject=dependency, variants=variants)

  def _dependencies(self, step_context, dep_product):
    return getattr(dep_product, self.field or 'dependencies')

  def step(self, step_context):
    # Request the product we need in order to request dependencies.
    dep_product_node = step_context.select_node(Select(self.dep_product), self.subject, self.variants)
    dep_product_state = step_context.get(dep_product_node)
    if type(dep_product_state) in (Throw, Waiting):
      return dep_product_state
    elif type(dep_product_state) is Noop:
      return Noop('Could not compute {} to determine dependencies.', dep_product_node)
    elif type(dep_product_state) is not Return:
      State.raise_unrecognized(dep_product_state)

    # The root dependency list is available: begin requesting transitively.
    dep_values = []
    dependencies = []
    requested = set()
    requesting = deque(self._dependencies(step_context, dep_product_state.value))
    while requesting:
      dependency_value = requesting.pop()
      if dependency_value in requested:
        continue
      requested.add(dependency_value)

      # Select the Node for this dependency value.
      if type(dependency_value) is not self.dep_product.element_type:
        return Throw(TypeError('Unexpected type: {} for {}'.format(type(dependency_value), self.selector)))
      dependency = self._dependency_node(step_context, dependency_value)

      dep_state = step_context.get(dependency)
      if type(dep_state) is Waiting:
        dependencies.extend(dep_state.dependencies)
      elif type(dep_state) is Return:
        # Append the value, and recurse to request its dependencies.
        dep_values.append(dep_state.value)
        requesting.extend(self._dependencies(step_context, dep_state.value))
      elif type(dep_state) is Noop:
        return Throw(ValueError('No source of transitive dependency {}: {}'.format(dependency, dep_state)))
      elif type(dep_state) is Throw:
        return dep_state
      else:
        raise State.raise_unrecognized(dep_state)
    if dependencies:
      return Waiting(dependencies)
    # All dependencies are present!
    return Return(dep_values)
