# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import six

from pants.base.address import Addresses


class FromTarget(object):
  """Used in a BUILD file to redirect the value of the sources= attribute to another target.
  """
  class ExpectedAddressError(Exception):
    """Thrown if an object that is not an address is added to an import attribute.
    """

  def __init__(self, parse_context):
    """
    :param ParseContext parse_context: build file context
    """
    self._parse_context = parse_context

  def __call__(self, address):
    """Expects a string representing an address."""
    if not isinstance(address, six.string_types):
      raise self.ExpectedAddressError("Expected string address argument, got type {type}"
                                     .format(type(address)))
    return Addresses(addresses=[address], rel_path=self._parse_context.rel_path)
