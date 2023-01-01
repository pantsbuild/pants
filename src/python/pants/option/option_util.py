# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import cast

from pants.option.custom_types import dict_with_files_option


def is_list_option(kwargs) -> bool:
    return cast(bool, kwargs.get("action") == "append" or kwargs.get("type") == list)


def is_dict_option(kwargs) -> bool:
    return kwargs.get("type") in (dict, dict_with_files_option)
