# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from enum import Enum
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock, call

import pytest

from pants.option.custom_types import dir_option, file_option, memory_size, shell_str, target_option
from pants.option.option_types import (
    ArgsListOption,
    BoolListOption,
    BoolOption,
    DictOption,
    DirListOption,
    DirOption,
    EnumListOption,
    EnumOption,
    FileListOption,
    FileOption,
    FloatListOption,
    FloatOption,
    IntListOption,
    IntOption,
    MemorySizeListOption,
    MemorySizeOption,
    ShellStrListOption,
    ShellStrOption,
    StrListOption,
    StrOption,
    TargetListOption,
    TargetOption,
)
from pants.option.subsystem import Subsystem


class MyEnum(Enum):
    Val1 = "val1"
    Val2 = "val2"


@pytest.mark.parametrize(
    "option_type, default, option_value, expected_register_kwargs",
    [
        (StrOption, "a str", "", dict(type=str)),
        (IntOption, 500, 0, dict(type=int)),
        (FloatOption, 0.0, 1.0, dict(type=float)),
        (BoolOption, True, False, dict(type=bool)),
        (TargetOption, "a str", "", dict(type=target_option)),
        (DirOption, "a str", ".", dict(type=dir_option)),
        (FileOption, "a str", ".", dict(type=file_option)),
        (ShellStrOption, "a str", "", dict(type=shell_str)),
        (MemorySizeOption, 20, 22, dict(type=memory_size)),
        # List options
        (StrListOption, ["a str"], ["str1", "str2"], dict(type=list, member_type=str)),
        (IntListOption, [10], [1, 2], dict(type=list, member_type=int)),
        (FloatListOption, [9.9], [1.0, 2.0], dict(type=list, member_type=float)),
        (BoolListOption, [True], [False, True], dict(type=list, member_type=bool)),
        (TargetListOption, ["a str"], ["str1", "str2"], dict(type=list, member_type=target_option)),
        (DirListOption, ["a str"], ["str1", "str2"], dict(type=list, member_type=dir_option)),
        (FileListOption, ["a str"], ["str1", "str2"], dict(type=list, member_type=file_option)),
        (ShellStrListOption, ["a str"], ["str1", "str2"], dict(type=list, member_type=shell_str)),
        (MemorySizeListOption, [22], [33, 88], dict(type=list, member_type=memory_size)),
    ],
)
def test_option_typeclasses(option_type, default, option_value, expected_register_kwargs) -> None:
    class MySubsystem(Subsystem):
        def __init__(self):
            self.options = SimpleNamespace()
            self.options.opt = option_value
            self.options.opt_no_default = option_value

        prop = option_type("--opt", default=default, help="")
        prop_no_default = option_type("--opt-no-default", help="")

    register = Mock()
    MySubsystem.register_options(register)
    my_subsystem = MySubsystem()
    default_if_not_given: Any | None = [] if expected_register_kwargs["type"] is list else None
    transform_opt: Any = tuple if expected_register_kwargs["type"] is list else lambda x: x  # type: ignore

    assert register.call_args_list == [
        call("--opt", default=default, help="", **expected_register_kwargs),
        call("--opt-no-default", default=default_if_not_given, help="", **expected_register_kwargs),
    ]
    assert my_subsystem.prop == transform_opt(option_value)
    assert my_subsystem.prop_no_default == transform_opt(option_value)


def test_other_options():
    class MySubsystem(Subsystem):
        def __init__(self):
            self.options = SimpleNamespace()
            self.options.dict_opt = {"key1": "val1"}
            self.options.enum_opt = MyEnum.Val2
            self.options.optional_enum_opt = MyEnum.Val2
            self.options.enum_list_opt = [MyEnum.Val2]
            self.options.defaultless_enum_list_opt = [MyEnum.Val2]
            self.options.args = ["--arg1"]

        dict_prop = DictOption[Any]("--dict-opt", help="")
        enum_prop = EnumOption("--enum-opt", default=MyEnum.Val1, help="")
        optional_enum_prop = EnumOption("--optional-enum-opt", option_type=MyEnum, help="")
        enum_list_prop = EnumListOption("--enum-list-opt", default=[MyEnum.Val1], help="")
        defaultless_enum_list_prop = EnumListOption(
            "--defaultless-enum-list-opt", member_type=MyEnum, help=""
        )
        args_prop = ArgsListOption(help="")

    register = Mock()
    MySubsystem.register_options(register)
    my_subsystem = MySubsystem()

    assert register.call_args_list == [
        call("--dict-opt", default={}, help="", type=dict),
        call("--enum-opt", default=MyEnum.Val1, help="", type=MyEnum),
        call("--optional-enum-opt", default=None, help="", type=MyEnum),
        call("--enum-list-opt", default=[MyEnum.Val1], help="", type=list, member_type=MyEnum),
        call("--defaultless-enum-list-opt", default=[], help="", type=list, member_type=MyEnum),
        call("--args", default=[], help="", type=list, member_type=shell_str),
    ]
    assert my_subsystem.dict_prop == {"key1": "val1"}
    assert my_subsystem.enum_prop == MyEnum.Val2
    assert my_subsystem.optional_enum_prop == MyEnum.Val2
    assert my_subsystem.enum_list_prop == (MyEnum.Val2,)
    assert my_subsystem.defaultless_enum_list_prop == (MyEnum.Val2,)
    assert my_subsystem.args_prop == ("--arg1",)


def test_builder_methods():
    class MySubsystem(Subsystem):
        def __init__(self):
            self.options = SimpleNamespace()

        prop = (
            StrOption("--opt", default=None, help="")
            .advanced()
            .metavar("META")
            .from_file()
            .mutually_exclusive_group("group")
            .default_help_repr("Help!")
            .deprecated(removal_version="99.9.9", hint="it's purple")
            .daemoned()
            .non_fingerprinted()
        )

    flag_options = MySubsystem.prop.flag_options
    assert flag_options["advanced"]
    assert flag_options["metavar"] == "META"
    assert flag_options["fromfile"]
    assert flag_options["mutually_exclusive_group"] == "group"
    assert flag_options["default_help_repr"] == "Help!"
    assert flag_options["removal_version"] == "99.9.9"
    assert flag_options["removal_hint"] == "it's purple"
    assert flag_options["daemon"]
    assert not flag_options["fingerprint"]


def test_subsystem_option_ordering() -> None:
    class MySubsystemBase(Subsystem):
        # Make sure these are out of alphabetical order
        z_prop = StrOption("--z", help="")
        y_prop = StrOption("--y", help="")

    class MySubsystem(MySubsystemBase):
        b_prop = StrOption("--b", help="")
        a_prop = StrOption("--a", help="")

    register = Mock()
    MySubsystem.register_options(register)
    assert register.call_args_list == [
        call("--z", type=str, default=None, help=""),
        call("--y", type=str, default=None, help=""),
        call("--b", type=str, default=None, help=""),
        call("--a", type=str, default=None, help=""),
    ]


def test_dict_option_valuetype() -> None:
    class MySubsystem(Subsystem):
        def __init__(self):
            self.options = SimpleNamespace()
            self.options.opt = None

        d1 = DictOption[str]("--opt", help="")
        d2 = DictOption[Any]("--opt", default=dict(key="val"), help="")
        # mypy correctly complains about needing a type annotation
        d3 = DictOption("--opt", help="")  # type: ignore[var-annotated]
        d4 = DictOption("--opt", default={"key": "val"}, help="")
        d5 = DictOption("--opt", default=dict(key="val"), help="")
        d6 = DictOption("--opt", default=dict(key=1), help="")
        d7 = DictOption("--opt", default=dict(key1=1, key2="str"), help="")

    my_subsystem = MySubsystem()
    d1: dict[str, str] = my_subsystem.d1  # noqa: F841
    d2: dict[str, Any] = my_subsystem.d2  # noqa: F841
    d3: dict[str, Any] = my_subsystem.d3  # noqa: F841
    d4: dict[str, str] = my_subsystem.d4  # noqa: F841
    d5: dict[str, str] = my_subsystem.d5  # noqa: F841
    d6: dict[str, int] = my_subsystem.d6  # noqa: F841
    d7: dict[str, Any] = my_subsystem.d7  # noqa: F841
