# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import inspect
import shlex
from enum import Enum
from typing import Any, Mapping, Optional, Sequence

from pants.engine.internals import native_engine
from pants.option.custom_types import _flatten_shlexed_list, shell_str
from pants.option.errors import OptionsError


class NativeOptionParser:
    def __init__(
        self,
        args: Optional[Sequence[str]],
        env: Mapping[str, str],
        configs: Optional[Sequence[str]],
        allow_pantsrc: bool,
        include_derivation: bool,
    ):
        self._native_parser = native_engine.PyOptionParser(
            args, dict(env), configs, allow_pantsrc, include_derivation
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

    def get(self, *, scope, flags, default, option_type, member_type=None) -> Any:
        name_parts = flags[-1][2:].split("-")  # '--foo-bar' -> ['foo', 'bar']
        switch = flags[0][1:] if len(flags) > 1 else None  # '-d' -> 'd'
        option_id = native_engine.PyOptionId(*name_parts, scope=scope, switch=switch)

        # The Python code allows registering default=None for dicts/lists, and forces it to
        # an empty dict/list at registration. Since here we only have access to what the user
        # provided, we do the same.
        # TODO: Pass in the final, munged, registration data, not what the user provided?
        rust_member_type = member_type
        if option_type is dict:
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
            elif inspect.isclass(member_type) and issubclass(member_type, Enum):
                rust_member_type = str
                default = [x.value for x in default]
            elif inspect.isfunction(rust_member_type):
                rust_member_type = str
            elif rust_member_type != str and isinstance(default, str):
                default = eval(default)

        getter = self._getter_by_type.get((option_type, rust_member_type))
        if getter is None:
            suffix = f" with member type {rust_member_type}" if option_type is list else ""
            raise OptionsError(f"Unsupported type: {option_type}{suffix}")

        val = getter(option_id, default)

        if option_type is list:
            if member_type == shell_str:
                val = _flatten_shlexed_list(val)
            elif callable(member_type):
                try:
                    val = [member_type(x) for x in val]
                except Exception:
                    print(f"EEEEEEEEEE {member_type} | {val}")
                    raise
        return val


def foo() -> None:
    native_parser = native_engine.PyOptionParser([], {}, None, True, False)
    option_id = native_engine.PyOptionId("version_for_resolve", scope="scala")
    val = native_parser.get_dict(
        option_id,
        {"FOO": "BAR", "BAZ": 55, "QUX": True, "QUUX": 5.4, "FIZZ": [1, 2], "BUZZ": {"X": "Y"}},
    )
    print(f"XXXXXX {val}")
