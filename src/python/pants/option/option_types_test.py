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


def test_option_typeclasses() -> None:
    class MyEnum(Enum):
        Val1 = "val1"
        Val2 = "val2"

    # NB: Option is only valid on Subsystem subclasses, but we won't use any Subsystem machinery for
    # this test other than `register_options`.
    class MySubsystem(Subsystem):
        def __init__(self):
            self.options = SimpleNamespace()
            self.options.str_opt = ""
            self.options.int_opt = 0
            self.options.float_opt = 1.0
            self.options.bool_opt = False
            self.options.enum_opt = MyEnum.Val1
            self.options.dict_opt = {"a key": "a val"}
            self.options.target_opt = ""
            self.options.dir_opt = "."
            self.options.file_opt = "."
            self.options.shellstr_opt = ""
            self.options.memorysize_opt = 22
            self.options.str_list_opt = ["str1", "str2"]
            self.options.int_list_opt = [1, 2]
            self.options.float_list_opt = [1.0, 2.0]
            self.options.bool_list_opt = [False, True]
            self.options.enum_list_opt = [MyEnum.Val2, MyEnum.Val1]
            self.options.target_list_opt = ["str1", "str2"]
            self.options.dir_list_opt = ["str1", "str2"]
            self.options.file_list_opt = ["str1", "str2"]
            self.options.shellstr_list_opt = ["str1", "str2"]
            self.options.memorysize_list_opt = [33, 88]

            self.options.defaultless_str_list_opt = ["str1", "str2"]
            self.options.defaultless_int_list_opt = [1, 2]
            self.options.defaultless_float_list_opt = [1.0, 2.0]
            self.options.defaultless_bool_list_opt = [False, True]
            self.options.defaultless_enum_list_opt = [MyEnum.Val2, MyEnum.Val1]
            self.options.defaultless_target_list_opt = ["str1", "str2"]
            self.options.defaultless_dir_list_opt = ["str1", "str2"]
            self.options.defaultless_file_list_opt = ["str1", "str2"]
            self.options.defaultless_shellstr_list_opt = ["str1", "str2"]
            self.options.defaultless_memorysize_list_opt = [33, 88]

            # NB: These must be set to None, as we must assert they are `None`.
            # See the comment above the `is None` assertions for more detail.
            # Once we test the types a better way, these should probably be set to values.
            self.options.optional_str_opt = None
            self.options.optional_int_opt = None
            self.options.optional_float_opt = None
            self.options.optional_bool_opt = None
            self.options.optional_enum_opt = None
            self.options.optional_target_opt = None
            self.options.optional_dir_opt = None
            self.options.optional_file_opt = None
            self.options.optional_shellstr_opt = None
            self.options.optional_memorysize_opt = None

            # Misc types
            self.options.args = ["arg1", "arg2"]

        str_prop = StrOption("--str-opt", default="a str", help="")
        int_prop = IntOption("--int-opt", default=500, help="")
        float_prop = FloatOption("--float-opt", default=0.0, help="")
        bool_prop = BoolOption("--bool-opt", default=True, help="")
        enum_prop = EnumOption("--enum-opt", default=MyEnum.Val1, help="")
        dict_prop = DictOption("--dict-opt", default={"key": "val"}, help="")
        target_prop = TargetOption("--target-opt", default="a str", help="")
        dir_prop = DirOption("--dir-opt", default="a str", help="")
        file_prop = FileOption("--file-opt", default="a str", help="")
        shellstr_prop = ShellStrOption("--shellstr-opt", default="a str", help="")
        memorysize_prop = MemorySizeOption("--memorysize-opt", default=20, help="")

        # Optional options
        optional_str_prop = StrOption("--optional-str-opt", help="")
        optional_int_prop = IntOption("--optional-int-opt", help="")
        optional_float_prop = FloatOption("--optional-float-opt", help="")
        optional_bool_prop = BoolOption("--optional-bool-opt", help="")
        optional_enum_prop = EnumOption("--optional-enum-opt", option_type=MyEnum, help="")
        optional_target_prop = TargetOption("--optional-target-opt", help="")
        optional_dir_prop = DirOption("--optional-dir-opt", help="")
        optional_file_prop = FileOption("--optional-file-opt", help="")
        optional_shellstr_prop = ShellStrOption("--optional-shellstr-opt", help="")
        optional_memorysize_prop = MemorySizeOption("--optional-memorysize-opt", help="")

        # List options
        str_list_prop = StrListOption("--str-list-opt", default=["a str"], help="")
        int_list_prop = IntListOption("--int-list-opt", default=[10], help="")
        float_list_prop = FloatListOption("--float-list-opt", default=[9.9], help="")
        bool_list_prop = BoolListOption("--bool-list-opt", default=[True], help="")
        enum_list_prop = EnumListOption("--enum-list-opt", default=[MyEnum.Val1], help="")
        target_list_prop = TargetListOption("--target-list-opt", default=["a str"], help="")
        dir_list_prop = DirListOption("--dir-list-opt", default=["a str"], help="")
        file_list_prop = FileListOption("--file-list-opt", default=["a str"], help="")
        shellstr_list_prop = ShellStrListOption("--shellstr-list-opt", default=["a str"], help="")
        memorysize_list_prop = MemorySizeListOption("--memorysize-list-opt", default=[22], help="")
        # And without default provided
        defaultless_str_list_prop = StrListOption("--defaultless-str-list-opt", help="")
        defaultless_int_list_prop = IntListOption("--defaultless-int-list-opt", help="")
        defaultless_float_list_prop = FloatListOption("--defaultless-float-list-opt", help="")
        defaultless_bool_list_prop = BoolListOption("--defaultless-bool-list-opt", help="")
        defaultless_enum_list_prop = EnumListOption(
            "--defaultless-enum-list-opt", member_type=MyEnum, help=""
        )
        defaultless_target_list_prop = TargetListOption("--defaultless-target-list-opt", help="")
        defaultless_dir_list_prop = DirListOption("--defaultless-dir-list-opt", help="")
        defaultless_file_list_prop = FileListOption("--defaultless-file-list-opt", help="")
        defaultless_shellstr_list_prop = ShellStrListOption(
            "--defaultless-shellstr-list-opt", help=""
        )
        defaultless_memorysize_list_prop = MemorySizeListOption(
            "--defaultless-memorysize-list-opt", help=""
        )

        # Misc options
        args_prop = ArgsListOption(help="")

    register = Mock()
    MySubsystem.register_options(register)

    assert register.call_args_list == [
        call("--str-opt", type=str, default="a str", help=""),
        call("--int-opt", type=int, default=500, help=""),
        call("--float-opt", type=float, default=0.0, help=""),
        call("--bool-opt", type=bool, default=True, help=""),
        call("--enum-opt", type=MyEnum, default=MyEnum.Val1, help=""),
        call("--dict-opt", type=dict, default={"key": "val"}, help=""),
        call("--target-opt", type=target_option, default="a str", help=""),
        call("--dir-opt", type=dir_option, default="a str", help=""),
        call("--file-opt", type=file_option, default="a str", help=""),
        call("--shellstr-opt", type=shell_str, default="a str", help=""),
        call("--memorysize-opt", type=memory_size, default=20, help=""),
        call("--optional-str-opt", type=str, default=None, help=""),
        call("--optional-int-opt", type=int, default=None, help=""),
        call("--optional-float-opt", type=float, default=None, help=""),
        call("--optional-bool-opt", type=bool, default=None, help=""),
        call("--optional-enum-opt", type=MyEnum, default=None, help=""),
        call("--optional-target-opt", type=target_option, default=None, help=""),
        call("--optional-dir-opt", type=dir_option, default=None, help=""),
        call("--optional-file-opt", type=file_option, default=None, help=""),
        call("--optional-shellstr-opt", type=shell_str, default=None, help=""),
        call("--optional-memorysize-opt", type=memory_size, default=None, help=""),
        call("--str-list-opt", type=list, default=["a str"], help="", member_type=str),
        call("--int-list-opt", type=list, default=[10], help="", member_type=int),
        call("--float-list-opt", type=list, default=[9.9], help="", member_type=float),
        call("--bool-list-opt", type=list, default=[True], help="", member_type=bool),
        call("--enum-list-opt", type=list, default=[MyEnum.Val1], help="", member_type=MyEnum),
        call(
            "--target-list-opt",
            type=list,
            default=["a str"],
            help="",
            member_type=target_option,
        ),
        call("--dir-list-opt", type=list, default=["a str"], help="", member_type=dir_option),
        call("--file-list-opt", type=list, default=["a str"], help="", member_type=file_option),
        call("--shellstr-list-opt", type=list, default=["a str"], help="", member_type=shell_str),
        call("--memorysize-list-opt", type=list, default=[22], help="", member_type=memory_size),
        call("--defaultless-str-list-opt", type=list, default=[], help="", member_type=str),
        call("--defaultless-int-list-opt", type=list, default=[], help="", member_type=int),
        call("--defaultless-float-list-opt", type=list, default=[], help="", member_type=float),
        call("--defaultless-bool-list-opt", type=list, default=[], help="", member_type=bool),
        call("--defaultless-enum-list-opt", type=list, default=[], help="", member_type=MyEnum),
        call(
            "--defaultless-target-list-opt",
            type=list,
            default=[],
            help="",
            member_type=target_option,
        ),
        call("--defaultless-dir-list-opt", type=list, default=[], help="", member_type=dir_option),
        call(
            "--defaultless-file-list-opt", type=list, default=[], help="", member_type=file_option
        ),
        call(
            "--defaultless-shellstr-list-opt", type=list, default=[], help="", member_type=shell_str
        ),
        call(
            "--defaultless-memorysize-list-opt",
            type=list,
            default=[],
            help="",
            member_type=memory_size,
        ),
        call("--args", type=list, default=[], help="", member_type=shell_str),
    ]

    my_subsystem = MySubsystem()
    assert my_subsystem.str_prop == ""
    assert my_subsystem.int_prop == 0
    assert my_subsystem.float_prop == 1.0
    assert not my_subsystem.bool_prop
    assert my_subsystem.enum_prop == MyEnum.Val1
    assert my_subsystem.dict_prop == {"a key": "a val"}
    assert my_subsystem.target_prop == ""
    assert my_subsystem.dir_prop == "."
    assert my_subsystem.file_prop == "."
    assert my_subsystem.shellstr_prop == ""
    assert my_subsystem.memorysize_prop == 22
    assert my_subsystem.str_list_prop == ("str1", "str2")
    assert my_subsystem.int_list_prop == (1, 2)
    assert my_subsystem.float_list_prop == (1.0, 2.0)
    assert my_subsystem.bool_list_prop == (False, True)
    assert my_subsystem.enum_list_prop == (MyEnum.Val2, MyEnum.Val1)
    assert my_subsystem.target_list_prop == ("str1", "str2")
    assert my_subsystem.shellstr_list_prop == ("str1", "str2")
    assert my_subsystem.memorysize_list_prop == (33, 88)
    assert my_subsystem.defaultless_str_list_prop == ("str1", "str2")
    assert my_subsystem.defaultless_int_list_prop == (1, 2)
    assert my_subsystem.defaultless_float_list_prop == (1.0, 2.0)
    assert my_subsystem.defaultless_bool_list_prop == (False, True)
    assert my_subsystem.defaultless_enum_list_prop == (MyEnum.Val2, MyEnum.Val1)
    assert my_subsystem.defaultless_target_list_prop == ("str1", "str2")
    assert my_subsystem.defaultless_dir_list_prop == ("str1", "str2")
    assert my_subsystem.defaultless_file_list_prop == ("str1", "str2")
    assert my_subsystem.defaultless_shellstr_list_prop == ("str1", "str2")
    assert my_subsystem.defaultless_memorysize_list_prop == (33, 88)
    assert my_subsystem.args_prop == ("arg1", "arg2")

    # These not only assert that we got the right value out of the `options` object, but also
    # (indirectly) test that our property type is actually `Optional[T]` and not accidentally `T`.
    # It does so by relying on two things:
    #   - If the type was `T`, these assertions would always trigger
    #   - Because there's code following these asserts, mypy would error that the code is
    #     unreachable if we got this wrong.
    assert my_subsystem.optional_str_prop is None
    assert my_subsystem.optional_int_prop is None
    assert my_subsystem.optional_float_prop is None
    assert my_subsystem.optional_bool_prop is None
    assert my_subsystem.optional_enum_prop is None
    assert my_subsystem.optional_target_prop is None
    assert my_subsystem.optional_dir_prop is None
    assert my_subsystem.optional_file_prop is None
    assert my_subsystem.optional_shellstr_prop is None
    assert my_subsystem.optional_memorysize_prop is None

    # This "tests" (through mypy) that the property types are what we expect
    # Ideally, we'd test these with pytest-mypy-plugins (or similar)
    #
    # There's no point in repeating this for optional vars. If we got the type wrong
    # (E.g. the property is `str` instead of `str | None`) mypy is happy to "promote" `str` to
    # `str | None`. This gets tested via the "unreachable code" checks above.
    var_str: str = my_subsystem.str_prop  # noqa: F841
    var_int: int = my_subsystem.int_prop  # noqa: F841
    var_float: float = my_subsystem.float_prop  # noqa: F841
    var_bool: bool = my_subsystem.bool_prop  # noqa: F841
    var_enum: MyEnum = my_subsystem.enum_prop  # noqa: F841
    var_dict: dict[str, str] = my_subsystem.dict_prop  # noqa: F841

    var_target: str = my_subsystem.target_prop  # noqa: F841
    var_dir: str = my_subsystem.dir_prop  # noqa: F841
    var_file: str = my_subsystem.file_prop  # noqa: F841
    var_shellstr: str = my_subsystem.shellstr_prop  # noqa: F841
    var_memorysize: int = my_subsystem.memorysize_prop  # noqa: F841

    var_str_list: tuple[str, ...] = my_subsystem.str_list_prop  # noqa: F841
    var_int_list: tuple[int, ...] = my_subsystem.int_list_prop  # noqa: F841
    var_float_list: tuple[float, ...] = my_subsystem.float_list_prop  # noqa: F841
    var_bool_list: tuple[bool, ...] = my_subsystem.bool_list_prop  # noqa: F841
    var_enum_list: tuple[MyEnum, ...] = my_subsystem.enum_list_prop  # noqa: F841
    var_target_list: tuple[str, ...] = my_subsystem.target_list_prop  # noqa: F841
    var_dir_list: tuple[str, ...] = my_subsystem.dir_list_prop  # noqa: F841
    var_file_list: tuple[str, ...] = my_subsystem.file_list_prop  # noqa: F841
    var_shellstr_list: tuple[str, ...] = my_subsystem.shellstr_list_prop  # noqa: F841
    var_memorysize_list: tuple[int, ...] = my_subsystem.memorysize_list_prop  # noqa: F841

    var_args: tuple[str, ...] = my_subsystem.args_prop  # noqa: F841


@pytest.mark.parametrize(
    "prop_type, opt_val",
    [
        (DirOption, ""),
        (FileOption, ""),
        (MemorySizeOption, "2GiB"),
        (DirListOption, [""]),
        (FileListOption, [""]),
        (MemorySizeListOption, ["2GiB"]),
    ],
)
def test_conversion(prop_type, opt_val) -> None:
    class MySubsystem(Subsystem):
        def __init__(self):
            self.options = SimpleNamespace()
            self.options.opt = opt_val

        prop = prop_type("--opt", help="")

    my_subsystem = MySubsystem()
    # We don't need to test the actual function, just that it transformed the value into something
    # else.
    assert my_subsystem.prop != opt_val


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
