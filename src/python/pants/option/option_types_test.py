# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import unittest.mock
from enum import Enum
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

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
    OptionsInfo,
    ShellStrListOption,
    ShellStrOption,
    SkipOption,
    StrListOption,
    StrOption,
    TargetListOption,
    TargetOption,
    collect_options_info,
)
from pants.option.subsystem import Subsystem

if TYPE_CHECKING:
    from mypy_typing_asserts import assert_type


class MyEnum(Enum):
    Val1 = "val1"
    Val2 = "val2"


def opt_info(*names, **options):
    return OptionsInfo(
        flag_names=names,
        flag_options=options,
    )


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
        dyn_prop = option_type(
            "--dyn-opt", default=lambda cls: cls.dyn_default, help=lambda cls: cls.dyn_help
        )

    class MySubsystem(MyBaseSubsystem):
        dyn_help = "Dynamic Help"
        dyn_default = default

    default_if_not_given: Any | None = [] if expected_register_kwargs["type"] is list else None

    assert list(collect_options_info(MySubsystem)) == [
        opt_info("--opt", default=default, help="", **expected_register_kwargs),
        opt_info(
            "--opt-no-default", default=default_if_not_given, help="", **expected_register_kwargs
        ),
        opt_info("--dyn-opt", default=default, help="Dynamic Help", **expected_register_kwargs),
    ]

    my_subsystem = MySubsystem()
    transform_opt: Any = tuple if expected_register_kwargs["type"] is list else lambda x: x  # type: ignore
    assert my_subsystem.prop == transform_opt(option_value)
    assert my_subsystem.prop_no_default == transform_opt(option_value)
    assert my_subsystem.dyn_prop == transform_opt(option_value)


def test_other_options() -> None:
    class MyBaseSubsystem(Subsystem):
        def __init__(self):
            self.options = SimpleNamespace()
            self.options.enum_prop = MyEnum.Val2
            self.options.optional_enum_prop = MyEnum.Val2
            self.options.dyn_enum_prop = MyEnum.Val2
            self.options.enum_list_prop = [MyEnum.Val2]
            self.options.dyn_enum_list_prop = [MyEnum.Val2]
            self.options.defaultless_enum_list_prop = [MyEnum.Val2]
            self.options.dict_prop = {"key1": "val1"}

        enum_prop = EnumOption(default=MyEnum.Val1, help="")
        dyn_enum_prop = EnumOption(
            default=lambda cls: cls.dyn_default,
            enum_type=MyEnum,
            help=lambda cls: f"{cls.dyn_help}",
        )
        optional_enum_prop = EnumOption(enum_type=MyEnum, default=None, help="")
        enum_list_prop = EnumListOption(default=[MyEnum.Val1], help="")
        dyn_enum_list_prop = EnumListOption(
            enum_type=MyEnum,
            default=lambda cls: cls.dyn_default_list,
            help=lambda cls: f"{cls.dyn_help}",
        )
        defaultless_enum_list_prop = EnumListOption(enum_type=MyEnum, help="")
        dict_prop = DictOption[Any](help="")

    class MySubsystem(MyBaseSubsystem):
        dyn_help = "Dynamic Help"
        dyn_default = MyEnum.Val1
        dyn_default_list = [MyEnum.Val1]

    assert list(collect_options_info(MySubsystem)) == [
        opt_info("--enum-prop", default=MyEnum.Val1, help="", type=MyEnum),
        opt_info("--dyn-enum-prop", default=MyEnum.Val1, type=MyEnum, help="Dynamic Help"),
        opt_info("--optional-enum-prop", default=None, help="", type=MyEnum),
        opt_info("--enum-list-prop", default=[MyEnum.Val1], help="", type=list, member_type=MyEnum),
        opt_info(
            "--dyn-enum-list-prop",
            default=[MyEnum.Val1],
            help="Dynamic Help",
            type=list,
            member_type=MyEnum,
        ),
        opt_info(
            "--defaultless-enum-list-prop", default=[], help="", type=list, member_type=MyEnum
        ),
        opt_info("--dict-prop", default={}, help="", type=dict),
    ]

    my_subsystem = MySubsystem()
    assert my_subsystem.enum_prop == MyEnum.Val2
    assert my_subsystem.dyn_enum_prop == MyEnum.Val2
    assert my_subsystem.optional_enum_prop == MyEnum.Val2
    assert my_subsystem.enum_list_prop == (MyEnum.Val2,)
    assert my_subsystem.dyn_enum_list_prop == (MyEnum.Val2,)
    assert my_subsystem.defaultless_enum_list_prop == (MyEnum.Val2,)
    assert my_subsystem.dict_prop == {"key1": "val1"}


def test_specialized_options() -> None:
    class MySubsystem(Subsystem):
        options_scope = "my-subsystem"
        name = "Wrench"

        def __init__(self):
            self.options = SimpleNamespace()
            self.options.skip_prop1 = True
            self.options.skip_prop2 = True
            self.options.args_prop1 = ["--arg1"]
            self.options.args_prop2 = ["--arg1"]
            self.options.args_prop3 = ["--arg1"]

        skip_prop1 = SkipOption("fmt", "lint")
        skip_prop2 = SkipOption("fmt")
        args_prop1 = ArgsListOption(example="--foo")
        args_prop2 = ArgsListOption(example="--bar", tool_name="Drill")
        args_prop3 = ArgsListOption(example="--baz", extra_help="Swing it!")

    class SubsystemWithName(Subsystem):
        options_scope = "other-subsystem"
        name = "Hammer"
        skip_prop1 = SkipOption("fmt")
        args_prop1 = ArgsListOption(example="--nail")
        args_prop2 = ArgsListOption(example="--screw", tool_name="Screwdriver")

    def expected_skip_opt_info(help: str):
        return opt_info(
            unittest.mock.ANY,
            help=help,
            default=False,
            type=bool,
        )

    def expected_args_opt_info(help: str):
        return opt_info(
            unittest.mock.ANY,
            member_type=shell_str,
            help=help,
            default=[],
            type=list,
        )

    assert list(collect_options_info(MySubsystem)) == [
        expected_skip_opt_info(
            "If true, don't use Wrench when running `./pants fmt` and `./pants lint`."
        ),
        expected_skip_opt_info("If true, don't use Wrench when running `./pants fmt`."),
        expected_args_opt_info(
            "Arguments to pass directly to Wrench, e.g. `--my-subsystem-args='--foo'`."
        ),
        expected_args_opt_info(
            "Arguments to pass directly to Drill, e.g. `--my-subsystem-args='--bar'`."
        ),
        expected_args_opt_info(
            "Arguments to pass directly to Wrench, e.g. `--my-subsystem-args='--baz'`.\n\nSwing it!"
        ),
    ]
    assert list(collect_options_info(SubsystemWithName)) == [
        expected_skip_opt_info("If true, don't use Hammer when running `./pants fmt`."),
        expected_args_opt_info(
            "Arguments to pass directly to Hammer, e.g. `--other-subsystem-args='--nail'`."
        ),
        expected_args_opt_info(
            "Arguments to pass directly to Screwdriver, e.g. `--other-subsystem-args='--screw'`."
        ),
    ]

    # Choose an arbitrary prop, they all point to the same option attr
    my_subsystem = MySubsystem()
    assert my_subsystem.args_prop1 == ("--arg1",)
    assert my_subsystem.skip_prop1


def test_advanced_params():
    class MySubsystem(Subsystem):
        def __init__(self):
            self.options = SimpleNamespace()

        prop = StrOption(
            default=None,
            help="",
            advanced=True,
            daemon=True,
            default_help_repr="Help!",
            fingerprint=False,
            fromfile=True,
            metavar="META",
            mutually_exclusive_group="group",
            removal_hint=lambda cls: f"{cls.__name__} is purple",
            removal_version="99.9.9",
        )

    flag_options = MySubsystem.prop.flag_options
    assert flag_options["advanced"]
    assert flag_options["metavar"] == "META"
    assert flag_options["fromfile"]
    assert flag_options["mutually_exclusive_group"] == "group"
    assert flag_options["default_help_repr"] == "Help!"
    assert flag_options["removal_version"] == "99.9.9"
    assert flag_options["removal_hint"] == "MySubsystem is purple"
    assert flag_options["daemon"]
    assert not flag_options["fingerprint"]


def test_subsystem_option_ordering() -> None:
    class MySubsystemBase(Subsystem):
        # Make sure these are out of alphabetical order
        z = StrOption(default=None, help="")
        y = StrOption(default=None, help="")

    class MySubsystem(MySubsystemBase):
        b = StrOption(default=None, help="")
        a = StrOption(default=None, help="")

    assert list(collect_options_info(MySubsystem)) == [
        opt_info("--z", type=str, default=None, help=""),
        opt_info("--y", type=str, default=None, help=""),
        opt_info("--b", type=str, default=None, help=""),
        opt_info("--a", type=str, default=None, help=""),
    ]


@pytest.mark.parametrize(
    "cls",
    [
        StrOption,
        IntOption,
        FloatOption,
        BoolOption,
        TargetOption,
        DirOption,
        FileOption,
        ShellStrOption,
        MemorySizeOption,
        StrListOption,
        IntListOption,
        FloatListOption,
        BoolListOption,
        TargetListOption,
        DirListOption,
        FileListOption,
        ShellStrListOption,
        MemorySizeListOption,
        EnumOption,
        EnumListOption,
        DictOption,
    ],
)
def test_register_if(cls) -> None:
    extra_kwargs = {"enum_type": MyEnum} if cls in {EnumOption, EnumListOption} else {}

    class MySubsystemBase(Subsystem):
        registered = cls(
            register_if=lambda cls: cls.truthy,
            default=None,
            **extra_kwargs,
            help="",
        )
        not_registered = cls(
            register_if=lambda cls: cls.falsey,
            default=None,
            **extra_kwargs,
            help="",
        )

    class MySubsystem(MySubsystemBase):
        truthy = True
        falsey = False

    options_info = list(collect_options_info(MySubsystem))
    assert len(options_info) == 1
    assert options_info[0].flag_names == ("--registered",)


def test_property_types() -> None:
    # NB: This test has no runtime assertions

    class MySubsystem(Subsystem):
        def __init__(self):
            pass

        str_opt = StrOption(default="", help="")
        optional_str_opt = StrOption(default=None, help="")
        int_opt = IntOption(default=0, help="")
        optional_int_opt = IntOption(default=None, help="")
        float_opt = FloatOption(default=1.0, help="")
        optional_float_opt = FloatOption(default=None, help="")
        bool_opt = BoolOption(default=True, help="")
        optional_bool_opt = BoolOption(default=None, help="")
        target_opt = TargetOption(default="", help="")
        optional_target_opt = TargetOption(default=None, help="")
        dir_opt = DirOption(default="", help="")
        optional_dir_opt = DirOption(default=None, help="")
        file_opt = FileOption(default="", help="")
        optional_file_opt = FileOption(default=None, help="")
        shellstr_opt = ShellStrOption(default="", help="")
        optional_shellstr_opt = ShellStrOption(default=None, help="")
        memorysize_opt = MemorySizeOption(default=1, help="")
        optional_memorysize_opt = MemorySizeOption(default=None, help="")

        # List opts
        str_list_opt = StrListOption(help="")
        int_list_opt = IntListOption(help="")
        float_list_opt = FloatListOption(help="")
        bool_list_opt = BoolListOption(help="")
        target_list_opt = TargetListOption(help="")
        dir_list_opt = DirListOption(help="")
        file_list_opt = FileListOption(help="")
        shellstr_list_opt = ShellStrListOption(help="")
        memorysize_list_opt = MemorySizeListOption(help="")
        # And just test one dynamic default
        dyn_str_list_opt = StrListOption(default=lambda cls: cls.default, help="")

        # Enum opts
        enum_opt = EnumOption(default=MyEnum.Val1, help="")
        optional_enum_opt = EnumOption(enum_type=MyEnum, default=None, help="")
        dyn_enum_opt = EnumOption(enum_type=MyEnum, default=lambda cls: cls.default, help="")
        # mypy correctly complains about not matching any possibilities
        enum_opt_bad = EnumOption(default=None, help="")  # type: ignore[call-overload]
        enum_list_opt1 = EnumListOption(default=[MyEnum.Val1], help="")
        enum_list_opt2 = EnumListOption(enum_type=MyEnum, help="")
        dyn_enum_list_opt = EnumListOption(
            enum_type=MyEnum, default=lambda cls: cls.default_list, help=""
        )
        # mypy correctly complains about needing a type annotation
        enum_list_bad_opt = EnumListOption(default=[], help="")  # type: ignore[var-annotated]

        # Dict opts
        dict_opt1 = DictOption[str](help="")
        dict_opt2 = DictOption[Any](default=dict(key="val"), help="")
        # mypy correctly complains about needing a type annotation
        dict_opt3 = DictOption(help="")  # type: ignore[var-annotated]
        dict_opt4 = DictOption(default={"key": "val"}, help="")
        dict_opt5 = DictOption(default=dict(key="val"), help="")
        dict_opt6 = DictOption(default=dict(key=1), help="")
        dict_opt7 = DictOption(default=dict(key1=1, key2="str"), help="")
        dyn_dict_opt = DictOption[str](default=lambda cls: cls.default, help="")

        # Specialized Opts
        skip_opt = SkipOption("fmt")
        args_opt = ArgsListOption(example="--whatever")

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
        assert_type["tuple[str, ...]"](my_subsystem.dyn_str_list_opt)

        assert_type["MyEnum"](my_subsystem.enum_opt)
        assert_type["MyEnum | None"](my_subsystem.optional_enum_opt)
        assert_type["MyEnum"](my_subsystem.dyn_enum_opt)
        assert_type["Any"](my_subsystem.enum_opt_bad)
        assert_type["tuple[MyEnum, ...]"](my_subsystem.enum_list_opt1)
        assert_type["tuple[MyEnum, ...]"](my_subsystem.enum_list_opt2)
        assert_type["tuple[MyEnum, ...]"](my_subsystem.dyn_enum_list_opt)
        assert_type["tuple[Any, ...]"](my_subsystem.enum_list_bad_opt)

        assert_type["dict[str, str]"](my_subsystem.dict_opt1)
        assert_type["dict[str, Any]"](my_subsystem.dict_opt2)
        assert_type["dict[str, Any]"](my_subsystem.dict_opt3)
        assert_type["dict[str, str]"](my_subsystem.dict_opt4)
        assert_type["dict[str, str]"](my_subsystem.dict_opt5)
        assert_type["dict[str, int]"](my_subsystem.dict_opt6)
        assert_type["dict[str, object]"](my_subsystem.dict_opt7)
        assert_type["dict[str, str]"](my_subsystem.dyn_dict_opt)

        assert_type["bool"](my_subsystem.skip_opt)
        assert_type["tuple[str, ...]"](my_subsystem.args_opt)
