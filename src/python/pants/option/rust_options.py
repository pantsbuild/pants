# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import inspect
import logging
import shlex
from enum import Enum
from typing import Any, Mapping, Optional, Sequence, Tuple

from pants.engine.internals import native_engine
from pants.engine.internals.native_engine import PyConfigSource
from pants.option.config import ConfigSource
from pants.option.custom_types import _flatten_shlexed_list, shell_str
from pants.option.errors import OptionsError
from pants.option.ranked_value import Rank
from pants.util.strutil import get_strict_env

logger = logging.getLogger()


class NativeOptionParser:
    int_to_rank = [
        Rank.NONE,
        Rank.HARDCODED,
        Rank.CONFIG_DEFAULT,
        Rank.CONFIG,
        Rank.ENVIRONMENT,
        Rank.FLAG,
    ]

    def __init__(
        self,
        args: Optional[Sequence[str]],
        env: Mapping[str, str],
        config_sources: Optional[Sequence[ConfigSource]],
        allow_pantsrc: bool,
    ):
        py_config_sources = [PyConfigSource(cs.path, cs.content) for cs in config_sources]
        self._native_parser = native_engine.PyOptionParser(
            args,
            dict(get_strict_env(env, logger)),
            py_config_sources,
            allow_pantsrc,
        )

        self._getter_by_type = {
            (bool, None): self._native_parser.get_bool,
            (int, None): self._native_parser.get_int,
            (float, None): self._native_parser.get_float,
            (str, None): self._native_parser.get_string,
            (list, bool): self._native_parser.get_bool_list,
            (list, int): self._native_parser.get_int_list,
            (list, float): self._native_parser.get_float_list,
            (list, str): self._native_parser.get_string_list,
            (dict, None): self._native_parser.get_dict,
        }

    def get(
        self, *, scope, flags, default, option_type, member_type=None, passthrough=False
    ) -> Tuple[Any, Rank]:
        def is_enum(typ):
            # TODO: When we switch to Python 3.11, use: return isinstance(typ, EnumType)
            return inspect.isclass(typ) and issubclass(typ, Enum)

        name_parts = (
            flags[-1][2:].replace(".", "-").split("-")
        )  # '--foo.bar-baz' -> ['foo', 'bar', 'baz']
        switch = flags[0][1:] if len(flags) > 1 else None  # '-d' -> 'd'
        option_id = native_engine.PyOptionId(*name_parts, scope=scope or "GLOBAL", switch=switch)

        rust_option_type = option_type
        rust_member_type = member_type

        if option_type is dict:
            # The Python code allows registering default=None for dicts/lists, and forces it to
            # an empty dict/list at registration. Since here we only have access to what the user
            # provided, we do the same.
            if default is None:
                default = {}
            elif isinstance(default, str):
                default = eval(default)
        elif option_type is list:
            if default is None:
                default = []
            if member_type is None:
                member_type = rust_member_type = str

            if member_type == shell_str:
                rust_member_type = str
                if isinstance(default, str):
                    default = shlex.split(default)
            elif is_enum(member_type):
                rust_member_type = str
                default = [x.value for x in default]
            elif inspect.isfunction(rust_member_type):
                rust_member_type = str
            elif rust_member_type != str and isinstance(default, str):
                default = eval(default)
        elif is_enum(option_type):
            if default is not None:
                default = default.value
                rust_option_type = type(default)
            else:
                rust_option_type = str
        elif option_type not in {bool, int, float, str}:
            # For enum and other specialized types.
            rust_option_type = str
            if default is not None:
                default = str(default)

        getter = self._getter_by_type.get((rust_option_type, rust_member_type))
        if getter is None:
            suffix = f" with member type {rust_member_type}" if rust_option_type is list else ""
            raise OptionsError(f"Unsupported type: {rust_option_type}{suffix}")

        val, rank_int = getter(option_id, default)  # type:ignore
        rank = self.int_to_rank[rank_int]

        if val is not None:
            if option_type is list:
                if member_type == shell_str:
                    val = _flatten_shlexed_list(val)
                elif callable(member_type):
                    val = [member_type(x) for x in val]
                if passthrough:
                    val += self._native_parser.get_passthrough_args() or []
            elif is_enum(option_type):
                val = option_type(val)
            elif callable(option_type):
                val = option_type(val)

        return (val, rank)
