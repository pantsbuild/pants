# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from abc import abstractproperty

import six

from pants.engine.addressable import Exactly
from pants.util.meta import AbstractClass
from pants.util.objects import datatype


def type_or_constraint_repr(constraint):
  """Generate correct repr for types and TypeConstraints"""
  if isinstance(constraint, type):
    return constraint.__name__
  elif isinstance(constraint, Exactly):
    return repr(constraint)


def constraint_for(type_or_constraint):
  """Given a type or an `Exactly` constraint, returns an `Exactly` constraint."""
  if isinstance(type_or_constraint, Exactly):
    return type_or_constraint
  elif isinstance(type_or_constraint, type):
    return Exactly(type_or_constraint)
  else:
    raise TypeError("Expected a type or constraint: got: {}".format(type_or_constraint))


class Selector(AbstractClass):
  # The type constraint for the product type for this selector.

  @property
  def type_constraint(self):
    return constraint_for(self.product)

  @abstractproperty
  def optional(self):
    """Return true if this Selector is optional. It may result in a `None` match."""

  @abstractproperty
  def product(self):
    """The product that this selector produces."""


class Select(datatype('Select', ['product', 'optional']), Selector):
  """Selects the given Product for the Subject provided to the constructor.

  If optional=True and no matching product can be produced, will return None.
  """

  def __new__(cls, product, optional=False):
    obj = super(Select, cls).__new__(cls, product, optional)
    return obj

  def __repr__(self):
    return '{}({}{})'.format(type(self).__name__,
                             type_or_constraint_repr(self.product),
                             ', optional=True' if self.optional else '')


class SelectVariant(datatype('Variant', ['product', 'variant_key']), Selector):
  """Selects the matching Product and variant name for the Subject provided to the constructor.

  For example: a SelectVariant with a variant_key of "thrift" and a product of type ApacheThrift
  will only match when a consumer passes a variant value for "thrift" that matches the name of an
  ApacheThrift value.
  """
  optional = False

  def __new__(cls, product, variant_key):
    if not isinstance(variant_key, six.string_types):
      raise ValueError('Expected variant_key to be a string, but was {!r}'.format(variant_key))
    return super(SelectVariant, cls).__new__(cls, product, variant_key)

  def __repr__(self):
    return '{}({}, {})'.format(type(self).__name__,
                               type_or_constraint_repr(self.product),
                               repr(self.variant_key))


class SelectDependencies(datatype('Dependencies', ['product', 'dep_product', 'field', 'field_types']),
                         Selector):
  """Selects a product for each of the dependencies of a product for the Subject.

  The dependencies declared on `dep_product` (in the optional `field` parameter, which defaults
  to 'dependencies' when not specified) will be provided to the requesting task in the
  order they were declared.

  Field types are used to statically declare the types expected to be contained by the
  `dep_product`.
  """

  DEFAULT_FIELD = 'dependencies'

  optional = False

  def __new__(cls, product, dep_product, field=DEFAULT_FIELD, field_types=tuple()):
    return super(SelectDependencies, cls).__new__(cls, product, dep_product, field, field_types)

  @property
  def input_product_selector(self):
    return Select(self.dep_product)

  @property
  def projected_product_selector(self):
    return Select(self.product)

  def __repr__(self):
    if self.field_types:
      field_types_portion = ', field_types=({},)'.format(', '.join(f.__name__ for f in self.field_types))
    else:
      field_types_portion = ''
    if self.field is not self.DEFAULT_FIELD:
      field_name_portion = ', {}'.format(repr(self.field))
    else:
      field_name_portion = ''
    return '{}({}, {}{}{})'.format(type(self).__name__,
                                     type_or_constraint_repr(self.product),
                                     type_or_constraint_repr(self.dep_product),
                                     field_name_portion,
                                     field_types_portion)


class SelectTransitive(datatype('Transitive', ['product', 'dep_product', 'field', 'field_types']),
                       Selector):
  """A variation of `SelectDependencies` that is used to recursively request a product.

  One use case is to eagerly walk the entire graph.

  It first selects for dep_product then recursively requests products with the `product` type, expanding each by its
  `field`.

  Requires that both the dep_product and product have the same field `field` that contains the same `field_types`.
  """

  DEFAULT_FIELD = 'dependencies'

  optional = False

  def __new__(cls, product, dep_product, field=DEFAULT_FIELD, field_types=tuple()):
    return super(SelectTransitive, cls).__new__(cls, product, dep_product, field, field_types)


class SelectProjection(datatype('Projection', ['product', 'projected_subject', 'field', 'input_product']), Selector):
  """Selects a field of the given Subject to produce a Subject, Product dependency from.

  Projecting an input allows for deduplication in the graph, where multiple Subjects
  resolve to a single backing Subject instead.

  For convenience, if a single field is requested and it is of the requested type, the field value
  is projected directly rather than attempting to use it to construct the projected type.
  """
  optional = False

  def __new__(cls, product, projected_subject, field, input_product):
    if not isinstance(field, six.string_types):
      raise ValueError('Expected `field` to be a string, but was: {!r}'.format(field))
    return super(SelectProjection, cls).__new__(cls, product, projected_subject, field, input_product)

  @property
  def input_product_selector(self):
    return Select(self.input_product)

  @property
  def projected_product_selector(self):
    return Select(self.product)

  def __repr__(self):
    return '{}({}, {}, {}, {})'.format(type(self).__name__,
                                       type_or_constraint_repr(self.product),
                                       self.projected_subject.__name__,
                                       repr(self.field),
                                       getattr(
                                         self.input_product, '__name__', repr(self.input_product)))
