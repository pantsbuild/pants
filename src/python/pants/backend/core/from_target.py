# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)


import six

from pants.backend.core.targets.address_set import AddressSet


class FromTarget(object):

  class ExpectedAddressError(Exception):
    """Thrown if an object that is not an address is added to an import attribute.
    """

  def __init__(self, parse_context):
    """
    :param ParseContext parse_context: build file context
    """
    self._rel_path=parse_context._rel_path

  def __call__(self, address, *args, **kwargs):
    """Expects a string representing an address"""
    if not isinstance(address, six.string_types):
      raise self.ExpectedAddressError("Expected string address argument, got type {type}"
                                     .format(type(address)))
    return AddressSet(addresses=[address])
