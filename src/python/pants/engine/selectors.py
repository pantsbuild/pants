# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import sys
from abc import abstractproperty

from pants.util.memo import memoized
from pants.util.meta import AbstractClass
from pants.util.objects import datatype


class Selector(AbstractClass):
  @abstractproperty
  def optional(self):
    """Return true if this Selector is optional. It may result in a `None` match."""


class Select(datatype('Subject', ['product', 'optional']), Selector):
  """Selects the given Product for the Subject provided to the constructor.

  If optional=True and no matching product can be produced, will return None.
  """

  def __new__(cls, product, optional=False):
    return super(Select, cls).__new__(cls, product, optional)


class SelectVariant(datatype('Variant', ['product', 'variant_key']), Selector):
  """Selects the matching Product and variant name for the Subject provided to the constructor.

  For example: a SelectVariant with a variant_key of "thrift" and a product of type ApacheThrift
  will only match when a consumer passes a variant value for "thrift" that matches the name of an
  ApacheThrift value.
  """
  optional = False


class SelectDependencies(datatype('Dependencies', ['product', 'deps_product', 'field']), Selector):
  """Selects a product for each of the dependencies of a product for the Subject.

  The dependencies declared on `deps_product` (in the optional `field` parameter, which defaults
  to 'dependencies' when not specified) will be provided to the requesting task in the
  order they were declared.
  """

  def __new__(cls, product, deps_product, field=None):
    return super(SelectDependencies, cls).__new__(cls, product, deps_product, field)

  optional = False


class SelectProjection(datatype('Projection', ['product', 'projected_subject', 'fields', 'input_product']), Selector):
  """Selects a field of the given Subject to produce a Subject, Product dependency from.

  Projecting an input allows for deduplication in the graph, where multiple Subjects
  resolve to a single backing Subject instead.

  For convenience, if a single field is requested and it is of the requested type, the field value
  is projected directly rather than attempting to use it to construct the projected type.
  """
  optional = False


class SelectLiteral(datatype('Literal', ['subject', 'product']), Selector):
  """Selects a literal Subject (other than the one applied to the selector)."""
  optional = False


class Collection(object):
  """
  Singleton Collection Type. The ambition is to gain native support for flattening,
  so methods like <pants.engine.fs.merge_files> won't have to be defined separately.
  Related to: https://github.com/pantsbuild/pants/issues/3169
  """

  @classmethod
  @memoized
  def of(cls, element_type, fields=('dependencies',)):
    type_name = b'{}({})'.format(cls.__name__, element_type.__name__)

    collection_of_type = type(type_name, (cls, datatype("{}s".format(element_type.__name__), fields)), {})

    # Expose the custom class type at the module level to be pickle compatible.
    setattr(sys.modules[cls.__module__], type_name, collection_of_type)

    return collection_of_type
