# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.address import Address
from pants.option.errors import ParseError
from pants.option.option_type import OptionType
from pants.util.eval import parse_expression


def _fingerprint_target_addresses(context, hasher, addresses):
  """Returns a fingerprint of the targets resolved from the given addresses."""
  for address in addresses:
    for target in context.resolve_address(address):
      # Not all targets have hashes; in particular, `Dependencies` targets don't.
      h = target.compute_invalidation_hash()
      if h:
        hasher.update(h)


class TargetOption(OptionType):
  """An option of type 'Address', which is parsed from a target address spec string."""

  @classmethod
  def from_untyped(cls, s):
    try:
      return Address.parse(s)
    except Exception as e:
      raise ParseError(
          'This option expects a single target address spec. Parse failed with: {}'.format(e))

  @classmethod
  def fingerprint(cls, context, hasher, option_val):
    _fingerprint_target_addresses(context, hasher, [option_val])


class TargetListOption(OptionType):
  """An option of type 'list' of 'Address', which is parsed from target address spec strings."""

  @classmethod
  def from_untyped(cls, s):
    addresses = []
    for entry in cls._convert(s, (list, tuple)):
      try:
        addresses.append(Address.parse(entry))
      except Exception as e:
        raise ParseError(
            'This option expects a list of target address specs. Parse failed with: {}'.format(e))
    return addresses

  @classmethod
  def fingerprint(cls, context, hasher, option_val):
    _fingerprint_target_addresses(context, hasher, option_val)
