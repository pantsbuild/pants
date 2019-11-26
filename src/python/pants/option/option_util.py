# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import shlex
from typing import Sequence, Tuple

from pants.option.custom_types import dict_with_files_option, list_option


def is_list_option(kwargs):
  return (kwargs.get('action') == 'append' or kwargs.get('type') == list or
          kwargs.get('type') == list_option)


def is_dict_option(kwargs):
  return kwargs.get('type') in (dict, dict_with_files_option)


# TODO: consider moving this directly into the option system, e.g. allowing registration of an
#  option with `type=flattened_list, member_type=shlexed`.
def flatten_shlexed_list(shlexed_args: Sequence[str]) -> Tuple[str, ...]:
  """Convert a list of shlexed args into a flattened list of individual args.

   For example, ['arg1 arg2=foo', '--arg3'] would be converted to ['arg1', 'arg2=foo', '--arg3'].
   """
  return tuple(
    arg for shlexed_arg in shlexed_args for arg in shlex.split(shlexed_arg)
  )
