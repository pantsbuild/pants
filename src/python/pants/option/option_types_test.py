# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from enum import Enum
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
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

if TYPE_CHECKING:
    from mypy_typing_asserts import assert_type


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
    class MyBaseSubsystem(Subsystem):
        def __init__(self):
            self.options = SimpleNamespace()
            self.options.opt = option_value
            self.options.opt_no_default = option_value
            self.options.dyn_opt = option_value

        prop = option_type("--opt", default=default, help="")
        if expected_register_kwargs["type"] is list:
            prop_no_default = option_type("--opt-no-default", help="")
        else:
            prop_no_default = option_type("--opt-no-default", default=None, help="")
        dyn_prop = option_type("--dyn-opt", default=default, help=lambda cls: cls.dyn_help)

    class MySubsystem(MyBaseSubsystem):
        dyn_help = "Dynamic Help"

    register = Mock()
    MySubsystem.register_options(register)
    my_subsystem = MySubsystem()
    default_if_not_given: Any | None = [] if expected_register_kwargs["type"] is list else None
    transform_opt: Any = tuple if expected_register_kwargs["type"] is list else lambda x: x  # type: ignore

    assert register.call_args_list == [
        call("--opt", default=default, help="", **expected_register_kwargs),
        call("--opt-no-default", default=default_if_not_given, help="", **expected_register_kwargs),
        call("--dyn-opt", default=default, help="Dynamic Help", **expected_register_kwargs),
    ]
    assert my_subsystem.prop == transform_opt(option_value)
    assert my_subsystem.prop_no_default == transform_opt(option_value)
    assert my_subsystem.dyn_prop == transform_opt(option_value)


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
        optional_enum_prop = EnumOption(
            "--optional-enum-opt", enum_type=MyEnum, default=None, help=""
        )
        enum_list_prop = EnumListOption("--enum-list-opt", default=[MyEnum.Val1], help="")
        defaultless_enum_list_prop = EnumListOption(
            "--defaultless-enum-list-opt", enum_type=MyEnum, help=""
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
        z_prop = StrOption("--z", default=None, help="")
        y_prop = StrOption("--y", default=None, help="")

    class MySubsystem(MySubsystemBase):
        b_prop = StrOption("--b", default=None, help="")
        a_prop = StrOption("--a", default=None, help="")

    register = Mock()
    MySubsystem.register_options(register)
    assert register.call_args_list == [
        call("--z", type=str, default=None, help=""),
        call("--y", type=str, default=None, help=""),
        call("--b", type=str, default=None, help=""),
        call("--a", type=str, default=None, help=""),
    ]


def test_property_types() -> None:
    # NB: This test has no runtime assertions

    class MySubsystem(Subsystem):
        def __init__(self):
            pass

        str_opt = StrOption("--opt", default="", help="")
        optional_str_opt = StrOption("--opt", default=None, help="")
        int_opt = IntOption("--opt", default=0, help="")
        optional_int_opt = IntOption("--opt", default=None, help="")
        float_opt = FloatOption("--opt", default=1.0, help="")
        optional_float_opt = FloatOption("--opt", default=None, help="")
        bool_opt = BoolOption("--opt", default=True, help="")
        optional_bool_opt = BoolOption("--opt", default=None, help="")
        target_opt = TargetOption("--opt", default="", help="")
        optional_target_opt = TargetOption("--opt", default=None, help="")
        dir_opt = DirOption("--opt", default="", help="")
        optional_dir_opt = DirOption("--opt", default=None, help="")
        file_opt = FileOption("--opt", default="", help="")
        optional_file_opt = FileOption("--opt", default=None, help="")
        shellstr_opt = ShellStrOption("--opt", default="", help="")
        optional_shellstr_opt = ShellStrOption("--opt", default=None, help="")
        memorysize_opt = MemorySizeOption("--opt", default=1, help="")
        optional_memorysize_opt = MemorySizeOption("--opt", default=None, help="")

        # List opts
        str_list_opt = StrListOption("--opt", help="")
        int_list_opt = IntListOption("--opt", help="")
        float_list_opt = FloatListOption("--opt", help="")
        bool_list_opt = BoolListOption("--opt", help="")
        target_list_opt = TargetListOption("--opt", help="")
        dir_list_opt = DirListOption("--opt", help="")
        file_list_opt = FileListOption("--opt", help="")
        shellstr_list_opt = ShellStrListOption("--opt", help="")
        memorysize_list_opt = MemorySizeListOption("--opt", help="")

        # Enum opts
        enum_opt = EnumOption("--opt", default=MyEnum.Val1, help="")
        optional_enum_opt = EnumOption("--opt", enum_type=MyEnum, default=None, help="")
        # mypy correctly complains about not matching any possibilities
        enum_opt_bad = EnumOption("--opt", default=None, help="")  # type: ignore[call-overload]
        enum_list_opt1 = EnumListOption("--opt", default=[MyEnum.Val1], help="")
        enum_list_opt2 = EnumListOption("--opt", enum_type=MyEnum, help="")
        # mypy correctly complains about needing a type annotation
        enum_list_bad_opt = EnumListOption("--opt", default=[], help="")  # type: ignore[var-annotated]

        # Dict opts
        dict_opt1 = DictOption[str]("--opt", help="")
        dict_opt2 = DictOption[Any]("--opt", default=dict(key="val"), help="")
        # mypy correctly complains about needing a type annotation
        dict_opt3 = DictOption("--opt", help="")  # type: ignore[var-annotated]
        dict_opt4 = DictOption("--opt", default={"key": "val"}, help="")
        dict_opt5 = DictOption("--opt", default=dict(key="val"), help="")
        dict_opt6 = DictOption("--opt", default=dict(key=1), help="")
        dict_opt7 = DictOption("--opt", default=dict(key1=1, key2="str"), help="")

    my_subsystem = MySubsystem()
    if TYPE_CHECKING:
        assert_type["str"](my_subsystem.str_opt)
        assert_type["str | None"](my_subsystem.optional_str_opt)
        assert_type["int"](my_subsystem.int_opt)
        assert_type["int | None"](my_subsystem.optional_int_opt)
        assert_type["float"](my_subsystem.float_opt)
        assert_type["float | None"](my_subsystem.optional_float_opt)
        assert_type["bool"](my_subsystem.bool_opt)
        assert_type["bool | None"](my_subsystem.optional_bool_opt)
        assert_type["str"](my_subsystem.target_opt)
        assert_type["str | None"](my_subsystem.optional_target_opt)
        assert_type["str"](my_subsystem.dir_opt)
        assert_type["str | None"](my_subsystem.optional_dir_opt)
        assert_type["str"](my_subsystem.file_opt)
        assert_type["str | None"](my_subsystem.optional_file_opt)
        assert_type["str"](my_subsystem.shellstr_opt)
        assert_type["str | None"](my_subsystem.optional_shellstr_opt)
        assert_type["int"](my_subsystem.memorysize_opt)
        assert_type["int | None"](my_subsystem.optional_memorysize_opt)

        assert_type["tuple[str, ...]"](my_subsystem.str_list_opt)
        assert_type["tuple[int, ...]"](my_subsystem.int_list_opt)
        assert_type["tuple[float, ...]"](my_subsystem.float_list_opt)
        assert_type["tuple[bool, ...]"](my_subsystem.bool_list_opt)
        assert_type["tuple[str, ...]"](my_subsystem.target_list_opt)
        assert_type["tuple[str, ...]"](my_subsystem.dir_list_opt)
        assert_type["tuple[str, ...]"](my_subsystem.file_list_opt)
        assert_type["tuple[str, ...]"](my_subsystem.shellstr_list_opt)
        assert_type["tuple[int, ...]"](my_subsystem.memorysize_list_opt)

        assert_type["MyEnum"](my_subsystem.enum_opt)
        assert_type["MyEnum | None"](my_subsystem.optional_enum_opt)
        assert_type["Any"](my_subsystem.enum_opt_bad)
        assert_type["tuple[MyEnum, ...]"](my_subsystem.enum_list_opt1)
        assert_type["tuple[MyEnum, ...]"](my_subsystem.enum_list_opt2)
        assert_type["tuple[Any, ...]"](my_subsystem.enum_list_bad_opt)

        assert_type["dict[str, str]"](my_subsystem.dict_opt1)
        assert_type["dict[str, Any]"](my_subsystem.dict_opt2)
        assert_type["dict[str, Any]"](my_subsystem.dict_opt3)
        assert_type["dict[str, str]"](my_subsystem.dict_opt4)
        assert_type["dict[str, str]"](my_subsystem.dict_opt5)
        assert_type["dict[str, int]"](my_subsystem.dict_opt6)
        assert_type["dict[str, object]"](my_subsystem.dict_opt7)
