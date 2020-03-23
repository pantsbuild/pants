# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import shlex
from typing import List, Sequence, cast

from pants.option.custom_types import dict_with_files_option


def is_list_option(kwargs) -> bool:
    return cast(bool, kwargs.get("action") == "append" or kwargs.get("type") == list)


def is_dict_option(kwargs) -> bool:
    return kwargs.get("type") in (dict, dict_with_files_option)


def flatten_shlexed_list(shlexed_args: Sequence[str]) -> List[str]:
    """Convert a list of shlexed args into a flattened list of individual args.

    For example, ['arg1 arg2=foo', '--arg3'] would be converted to ['arg1', 'arg2=foo', '--arg3'].
    """
    return [arg for shlexed_arg in shlexed_args for arg in shlex.split(shlexed_arg)]
