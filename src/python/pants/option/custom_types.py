# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.deprecated import deprecated_module
from pants.option.option_type import OptionType
from pants.option.option_types import DictOption, FileOption, ListOption


deprecated_module('0.0.57',
                  hint_message='Use pants.option.option_types and pants.build_graph.option_types.')

dict_option = DictOption
list_option = ListOption
file_option = FileOption


def _fingerprint_target_specs(context, hasher, address_specs):
  """Returns a fingerprint of the targets resolved from the given address specs."""
  for address_spec in address_specs:
    for target in context.resolve(address_spec):
      # Not all targets have hashes; in particular, `Dependencies` targets don't.
      h = target.compute_invalidation_hash()
      if h:
        hasher.update(h)


@deprecated(removal_version='0.0.57',
            hint_message='Use `from pants.build_graph.option_types import TargetOption`.')
class target_option(OptionType):
  """Same type as 'str', but indicates a single target spec."""

  @classmethod
  def from_untyped(cls, s):
    return s

  @classmethod
  def fingerprint(cls, context, hasher, option_val):
    _fingerprint_target_specs(context, hasher, [option_val])


@deprecated(removal_version='0.0.57',
            hint_message='Use `from pants.build_graph.option_types import TargetListOption`.')
class target_list_option(OptionType):
  """Same type as 'list_option', but indicates list contents are target specs."""

  @classmethod
  def from_untyped(cls, s):
    return _convert(s, (list, tuple))

  @classmethod
  def fingerprint(cls, context, hasher, option_val):
    _fingerprint_target_specs(context, hasher, option_val)
