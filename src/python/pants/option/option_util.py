# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import cast


def is_list_option(kwargs) -> bool:
    return cast(bool, kwargs.get("action") == "append" or kwargs.get("type") == list)


def is_dict_option(kwargs) -> bool:
    return cast(bool, kwargs.get("type") == dict)
