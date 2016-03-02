# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from abc import abstractmethod, abstractproperty

from pants.engine.exp.nodes import DependenciesNode, ProjectionNode, SelectNode, TaskNode
from pants.util.meta import AbstractClass
from pants.util.objects import datatype


class Selector(AbstractClass):
  @abstractproperty
  def optional(self):
    """Return true if this Selector is optional. It may result in a `None` match."""

  @abstractmethod
  def construct_node(self, subject_key, variants):
    """Constructs a Node for this Selector and the given Subject/Variants.

    May return None if the Selector can be known statically to not be satisfiable for the inputs.
    """


class Select(datatype('Subject', ['product', 'optional']), Selector):
  """Selects the given Product for the Subject provided to the constructor.

  If optional=True and no matching product can be produced, will return None.
  """

  def __new__(cls, product, optional=False):
    return super(Select, cls).__new__(cls, product, optional)

  def construct_node(self, subject_key, variants):
    return SelectNode(subject_key, self.product, variants, None)


class SelectVariant(datatype('Variant', ['product', 'variant_key']), Selector):
  """Selects the matching Product and variant name for the Subject provided to the constructor.

  For example: a SelectVariant with a variant_key of "thrift" and a product of type ApacheThrift
  will only match when a consumer passes a variant value for "thrift" that matches the name of an
  ApacheThrift value.
  """
  optional = False

  def construct_node(self, subject_key, variants):
    return SelectNode(subject_key, self.product, variants, self.variant_key)


class SelectDependencies(datatype('Dependencies', ['product', 'deps_product', 'field']), Selector):
  """Selects a product for each of the dependencies of a product for the Subject.

  The dependencies declared on `deps_product` (in the optional `field` parameter, which defaults
  to 'dependencies' when not specified) will be provided to the requesting task in the
  order they were declared.
  """

  def __new__(cls, product, deps_product, field=None):
    return super(SelectDependencies, cls).__new__(cls, product, deps_product, field)

  optional = False

  def construct_node(self, subject_key, variants):
    return DependenciesNode(subject_key, self.product, variants, self.deps_product, self.field)


class SelectProjection(datatype('Projection', ['product', 'projected_subject', 'fields', 'input_product']), Selector):
  """Selects a field of the given Subject to produce a Subject, Product dependency from.

  Projecting an input allows for deduplication in the graph, where multiple Subjects
  resolve to a single backing Subject instead.

  For convenience, if a single field is requested and it is of the requested type, the field value
  is projected directly rather than attempting to use it to construct the projected type.
  """
  optional = False

  def construct_node(self, subject_key, variants):
    return ProjectionNode(subject_key, self.product, variants, self.projected_subject, self.fields, self.input_product)


class SelectLiteral(datatype('Literal', ['subject_key', 'product']), Selector):
  """Selects a literal Subject (other than the one applied to the selector)."""
  optional = False

  def construct_node(self, subject_key, variants):
    # NB: Intentionally ignores subject_key parameter to provide a literal subject.
    return SelectNode(self.subject_key, self.product, variants, None)
