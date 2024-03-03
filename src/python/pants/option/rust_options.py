# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Any

from pants.engine.internals import native_engine
from pants.option.errors import OptionsError
from pants.option.option_value_container import OptionValueContainer


class NativeOptionParser:
    def __init__(self):
        self._native_parser = native_engine.PyOptionParser([], {}, None, True, False)
        self._getter_by_type = {
            (bool, None): self._native_parser.get_bool,
            (int, None): self._native_parser.get_int,
            (float, None): self._native_parser.get_float,
            (str, None): self._native_parser.get_string,
            (list, bool): self._native_parser.get_bool_list,
            (list, int): self._native_parser.get_int_list,
            (list, float): self._native_parser.get_float_list,
            (list, str): self._native_parser.get_string_list,
            (dict, None): self._native_parser.get_dict
        }

    def get(self, *, scope, flags, default, option_type, member_type=None) -> Any:
        name_parts = flags[-1][2:].split('-')  # '--foo-bar' -> ['foo', 'bar']
        switch = flags[0][1:] if len(flags) > 1 else None  # '-d' -> 'd'
        option_id = native_engine.PyOptionId(*name_parts, scope=scope, switch=switch)
        member_type = None if option_type is dict else member_type
        getter = self._getter_by_type.get((option_type, member_type))
        if getter is None:
            suffix = f"with member type {member_type}" if option_type is list else ""
            raise OptionsError(f"Unsupported type: {option_type}{suffix}")
        return getter(option_id, default)


def foo() -> None:
    native_parser = native_engine.PyOptionParser([], {}, None, True, False)
    option_id = native_engine.PyOptionId("version_for_resolve", scope="scala")
    val = native_parser.get_dict(option_id, {"FOO": "BAR", "BAZ": 55, "QUX": True, "QUUX": 5.4, "FIZZ": [1, 2], "BUZZ": {"X": "Y"}})
    print(f"XXXXXX {val}")
