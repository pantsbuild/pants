# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import ast
from abc import abstractproperty

import six

from pants.util.meta import AbstractClass
from pants.util.objects import Exactly, datatype


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


class Get(datatype(['product', 'subject'])):
  """Experimental synchronous generator API.

  May be called equivalently as either:
    # verbose form: Get(product_type, subject_type, subject)
    # shorthand form: Get(product_type, subject_type(subject))
  """

  @staticmethod
  def extract_constraints(call_node):
    """Parses a `Get(..)` call in one of its two legal forms to return its type constraints.

    :param call_node: An `ast.Call` node representing a call to `Get(..)`.
    :return: A tuple of product type id and subject type id.
    """
    def render_args():
      return ', '.join(a.id for a in call_node.args)

    if len(call_node.args) == 2:
      product_type, subject_constructor = call_node.args
      if not isinstance(product_type, ast.Name) or not isinstance(subject_constructor, ast.Call):
        raise ValueError('Two arg form of {} expected (product_type, subject_type(subject)), but '
                        'got: ({})'.format(Get.__name__, render_args()))
      return (product_type.id, subject_constructor.func.id)
    elif len(call_node.args) == 3:
      product_type, subject_type, _ = call_node.args
      if not isinstance(product_type, ast.Name) or not isinstance(subject_type, ast.Name):
        raise ValueError('Three arg form of {} expected (product_type, subject_type, subject), but '
                        'got: ({})'.format(Get.__name__, render_args()))
      return (product_type.id, subject_type.id)
    else:
      raise ValueError('Invalid {}; expected either two or three args, but '
                      'got: ({})'.format(Get.__name__, render_args()))

  def __new__(cls, *args):
    if len(args) == 2:
      product, subject = args
    elif len(args) == 3:
      product, subject_type, subject = args
      if type(subject) is not subject_type:
        raise TypeError('Declared type did not match actual type for {}({}).'.format(
          Get.__name__, ', '.join(str(a) for a in args)))
    else:
      raise Exception('Expected either two or three arguments to {}; got {}.'.format(
        Get.__name__, args))
    return super(Get, cls).__new__(cls, product, subject)


class Selector(AbstractClass):

  @property
  def type_constraint(self):
    """The type constraint for the product type for this selector."""
    return constraint_for(self.product)

  @abstractproperty
  def optional(self):
    """Return true if this Selector is optional. It may result in a `None` match."""

  @abstractproperty
  def product(self):
    """The product that this selector produces."""


class Select(datatype(['product', 'optional']), Selector):
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


class SelectVariant(datatype(['product', 'variant_key']), Selector):
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


class SelectDependencies(datatype(['product', 'dep_product', 'field', 'field_types']),
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
