# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
from abc import abstractmethod, abstractproperty
from collections import deque
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
