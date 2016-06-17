# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from textwrap import dedent

import six

from pants.base.deprecated import deprecated
from pants.build_graph.address import Addresses


from_target_deprecation_hint = dedent('''
    Using sources = from_target() has been deprecated. Try using remote_sources() instead.

    For example, instead of this:

      java_protobuf_library(name='proto',
        sources=from_target(':other-target'),
        platform='java7',
      )

    Try this:

      remote_sources(name='proto',
        dest=java_protobuf_library,
        sources_target=':other-target',
        args=dict(
          platform='java7',
        )
      )
  ''').strip()


class FromTarget(object):
  """Used in a BUILD file to redirect the value of the sources= attribute to another target."""

  class ExpectedAddressError(Exception):
    """Thrown if an object that is not an address is added to an import attribute."""

  def __init__(self, parse_context):
    self._parse_context = parse_context

  @deprecated(removal_version='1.3.0', hint_message=from_target_deprecation_hint)
  def __call__(self, address):
    """
    :param string address: A target address.
    :returns: A singleton Addresses instance for the specified address.
    """
    if not isinstance(address, six.string_types):
      raise self.ExpectedAddressError("Expected string address argument, got type {type}"
                                     .format(type(address)))
    return Addresses(addresses=[address], rel_path=self._parse_context.rel_path)
