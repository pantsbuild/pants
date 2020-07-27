# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import dataclasses
from enum import Enum
from typing import Tuple

from pants.engine.goal import GoalSubsystem
from pants.engine.unions import UnionMembership
from pants.help.help_info_extracter import HelpInfoExtracter
from pants.option.config import Config
from pants.option.global_options import GlobalOptions
from pants.option.options import Options
from pants.option.parser import Parser
from pants.option.ranked_value import Rank, RankedValue
from pants.option.scope import GLOBAL_SCOPE
from pants.subsystem.subsystem import Subsystem


class LogLevel(Enum):
    INFO = "info"
    DEBUG = "debug"


def test_global_scope():
    def do_test(args, kwargs, expected_display_args, expected_scoped_cmd_line_args):
        # The scoped and unscoped args are the same in global scope.
        expected_unscoped_cmd_line_args = expected_scoped_cmd_line_args
        ohi = HelpInfoExtracter("").get_option_help_info(args, kwargs)
        assert tuple(expected_display_args) == ohi.display_args
        assert tuple(expected_scoped_cmd_line_args) == ohi.scoped_cmd_line_args
        assert tuple(expected_unscoped_cmd_line_args) == ohi.unscoped_cmd_line_args

    do_test(["-f"], {"type": bool}, ["-f"], ["-f"])
    do_test(["--foo"], {"type": bool}, ["--[no-]foo"], ["--foo", "--no-foo"])
    do_test(
        ["--foo"], {"type": bool, "implicit_value": False}, ["--[no-]foo"], ["--foo", "--no-foo"],
    )
    do_test(["-f", "--foo"], {"type": bool}, ["-f", "--[no-]foo"], ["-f", "--foo", "--no-foo"])

    do_test(["--foo"], {}, ["--foo=<str>"], ["--foo"])
    do_test(["--foo"], {"metavar": "xx"}, ["--foo=xx"], ["--foo"])
    do_test(["--foo"], {"type": int}, ["--foo=<int>"], ["--foo"])
    do_test(
        ["--foo"], {"type": list}, ["--foo=\"['<str>', '<str>', ...]\""], ["--foo"],
    )
    do_test(
        ["--foo"], {"type": list, "member_type": int}, ['--foo="[<int>, <int>, ...]"'], ["--foo"],
    )
    do_test(
        ["--foo"],
        {"type": list, "member_type": dict},
        [
            "--foo=\"[{'key1': val1, 'key2': val2, ...}, "
            "{'key1': val1, 'key2': val2, ...}, ...]\"",
        ],
        ["--foo"],
    )
    do_test(["--foo"], {"type": dict}, ["--foo=\"{'key1': val1, 'key2': val2, ...}\""], ["--foo"])

    do_test(["--foo", "--bar"], {}, ["--foo=<str>", "--bar=<str>"], ["--foo", "--bar"])


def test_non_global_scope():
    def do_test(
        args,
        kwargs,
        expected_display_args,
        expected_scoped_cmd_line_args,
        expected_unscoped_cmd_line_args,
    ):
        ohi = HelpInfoExtracter("bar.baz").get_option_help_info(args, kwargs)
        assert tuple(expected_display_args) == ohi.display_args
        assert tuple(expected_scoped_cmd_line_args) == ohi.scoped_cmd_line_args
        assert tuple(expected_unscoped_cmd_line_args) == ohi.unscoped_cmd_line_args

    do_test(["-f"], {"type": bool}, ["--bar-baz-f"], ["--bar-baz-f"], ["-f"])
    do_test(
        ["--foo"],
        {"type": bool},
        ["--[no-]bar-baz-foo"],
        ["--bar-baz-foo", "--no-bar-baz-foo"],
        ["--foo", "--no-foo"],
    )
    do_test(
        ["--foo"],
        {"type": bool, "implicit_value": False},
        ["--[no-]bar-baz-foo"],
        ["--bar-baz-foo", "--no-bar-baz-foo"],
        ["--foo", "--no-foo"],
    )


def test_default() -> None:
    def do_test(args, kwargs, expected_default_str):
        # Defaults are computed in the parser and added into the kwargs, so we
        # must jump through this hoop in this test.
        parser = Parser(
            env={},
            config=Config.load([]),
            scope_info=GlobalOptions.get_scope_info(),
            parent_parser=None,
        )
        parser.register(*args, **kwargs)
        oshi = HelpInfoExtracter(parser.scope).get_option_scope_help_info(
            "description", parser, False
        )
        assert oshi.description == "description"
        assert len(oshi.basic) == 1
        ohi = oshi.basic[0]
        assert ohi.default_str == expected_default_str

    do_test(["--foo"], {"type": bool}, "False")
    do_test(["--foo"], {"type": bool, "default": True}, "True")
    do_test(["--foo"], {"type": bool, "implicit_value": False}, "True")
    do_test(["--foo"], {"type": bool, "implicit_value": False, "default": False}, "False")
    do_test(["--foo"], {}, "None")
    do_test(["--foo"], {"type": int}, "None")
    do_test(["--foo"], {"type": int, "default": 42}, "42")
    do_test(["--foo"], {"type": list}, "[]")
    do_test(["--foo"], {"type": dict}, "{}")
    do_test(["--foo"], {"type": LogLevel}, "None")
    do_test(["--foo"], {"type": LogLevel, "default": LogLevel.DEBUG}, "debug")


def test_compute_default():
    def do_test(expected_default, expected_default_str, **kwargs):
        kwargs["default"] = RankedValue(Rank.HARDCODED, kwargs["default"])
        assert (expected_default, expected_default_str) == HelpInfoExtracter.compute_default(
            **kwargs
        )

    do_test(False, "False", type=bool, default=False)
    do_test(42, "42", type=int, default=42)
    do_test("foo", "foo", type=str, default="foo")
    do_test(None, "None", type=str, default=None)
    do_test([1, 2, 3], "[\n  1,\n  2,\n  3\n]", type=list, member_type=int, default=[1, 2, 3])
    do_test(LogLevel.INFO, "info", type=LogLevel, default=LogLevel.INFO)


def test_deprecated():
    kwargs = {"removal_version": "999.99.9", "removal_hint": "do not use this"}
    ohi = HelpInfoExtracter("").get_option_help_info(["--foo"], kwargs)
    assert "999.99.9" == ohi.removal_version
    assert "do not use this" == ohi.removal_hint
    assert ohi.deprecated_message is not None


def test_passthrough():
    kwargs = {"passthrough": True, "type": list, "member_type": str}
    ohi = HelpInfoExtracter("").get_option_help_info(["--thing"], kwargs)
    assert 2 == len(ohi.display_args)
    assert any(args.startswith("--thing") for args in ohi.display_args)
    assert any(args.startswith("... -- ") for args in ohi.display_args)


def test_choices() -> None:
    kwargs = {"choices": ["info", "debug"]}
    ohi = HelpInfoExtracter("").get_option_help_info(["--foo"], kwargs)
    assert ohi.choices == ("info", "debug")


def test_choices_enum() -> None:
    kwargs = {"type": LogLevel}
    ohi = HelpInfoExtracter("").get_option_help_info(["--foo"], kwargs)
    assert ohi.choices == ("info", "debug")


def test_list_of_enum() -> None:
    kwargs = {"type": list, "member_type": LogLevel}
    ohi = HelpInfoExtracter("").get_option_help_info(["--foo"], kwargs)
    assert ohi.choices == ("info", "debug")


def test_grouping():
    def do_test(kwargs, expected_basic=False, expected_advanced=False):
        def exp_to_len(exp):
            return int(exp)  # True -> 1, False -> 0.

        parser = Parser(
            env={},
            config=Config.load([]),
            scope_info=GlobalOptions.get_scope_info(),
            parent_parser=None,
        )
        parser.register("--foo", **kwargs)
        oshi = HelpInfoExtracter("").get_option_scope_help_info("", parser, False)
        assert exp_to_len(expected_basic) == len(oshi.basic)
        assert exp_to_len(expected_advanced) == len(oshi.advanced)

    do_test({}, expected_basic=True)
    do_test({"advanced": False}, expected_basic=True)
    do_test({"advanced": True}, expected_advanced=True)
    do_test({"recursive_root": True}, expected_basic=True)
    do_test({"advanced": True, "recursive_root": True}, expected_advanced=True)


def test_get_all_help_info():
    class Global(Subsystem):
        """Global options."""

        options_scope = GLOBAL_SCOPE

        @classmethod
        def register_options(cls, register):
            register("-o", "--opt1", type=int, default=42, help="Option 1")

    class Foo(Subsystem):
        """A foo."""

        options_scope = "foo"

        @classmethod
        def register_options(cls, register):
            register("--opt2", type=bool, default=True, help="Option 2")
            register("--opt3", advanced=True, choices=["a", "b", "c"])

    class Bar(GoalSubsystem):
        """The bar goal."""

        name = "bar"

    options = Options.create(
        env={},
        config=Config.load_file_contents(""),
        known_scope_infos=[Global.get_scope_info(), Foo.get_scope_info(), Bar.get_scope_info()],
        args=["./pants"],
        bootstrap_option_values=None,
    )
    Global.register_options_on_scope(options)
    Foo.register_options_on_scope(options)
    Bar.register_options_on_scope(options)

    def fake_consumed_scopes_mapper(scope: str) -> Tuple[str, ...]:
        return ("somescope", f"used_by_{scope or 'GLOBAL_SCOPE'}")

    all_help_info = HelpInfoExtracter.get_all_help_info(
        options, UnionMembership({}), fake_consumed_scopes_mapper
    )
    all_help_info_dict = dataclasses.asdict(all_help_info)
    expected_all_help_info_dict = {
        "scope_to_help_info": {
            GLOBAL_SCOPE: {
                "scope": GLOBAL_SCOPE,
                "description": "Global options.",
                "is_goal": False,
                "basic": (
                    {
                        "display_args": ("-o=<int>", "--opt1=<int>"),
                        "comma_separated_display_args": "-o=<int>, --opt1=<int>",
                        "scoped_cmd_line_args": ("-o", "--opt1"),
                        "unscoped_cmd_line_args": ("-o", "--opt1"),
                        "config_key": "opt1",
                        "env_var": "PANTS_OPT1",
                        "value_history": {
                            "ranked_values": (
                                {"rank": Rank.NONE, "value": None, "details": None},
                                {"rank": Rank.HARDCODED, "value": 42, "details": None},
                            ),
                        },
                        "typ": int,
                        "default": 42,
                        "default_str": "42",
                        "help": "Option 1",
                        "deprecated_message": None,
                        "removal_version": None,
                        "removal_hint": None,
                        "choices": None,
                        "comma_separated_choices": None,
                    },
                ),
                "advanced": tuple(),
                "deprecated": tuple(),
            },
            "foo": {
                "scope": "foo",
                "description": "A foo.",
                "is_goal": False,
                "basic": (
                    {
                        "display_args": ("--[no-]foo-opt2",),
                        "comma_separated_display_args": "--[no-]foo-opt2",
                        "scoped_cmd_line_args": ("--foo-opt2", "--no-foo-opt2"),
                        "unscoped_cmd_line_args": ("--opt2", "--no-opt2"),
                        "config_key": "opt2",
                        "env_var": "PANTS_FOO_OPT2",
                        "value_history": {
                            "ranked_values": (
                                {"rank": Rank.NONE, "value": None, "details": None},
                                {"rank": Rank.HARDCODED, "value": True, "details": None},
                            ),
                        },
                        "typ": bool,
                        "default": True,
                        "default_str": "True",
                        "help": "Option 2",
                        "deprecated_message": None,
                        "removal_version": None,
                        "removal_hint": None,
                        "choices": None,
                        "comma_separated_choices": None,
                    },
                ),
                "advanced": (
                    {
                        "display_args": ("--foo-opt3=<str>",),
                        "comma_separated_display_args": "--foo-opt3=<str>",
                        "scoped_cmd_line_args": ("--foo-opt3",),
                        "unscoped_cmd_line_args": ("--opt3",),
                        "config_key": "opt3",
                        "env_var": "PANTS_FOO_OPT3",
                        "value_history": {
                            "ranked_values": ({"rank": Rank.NONE, "value": None, "details": None},),
                        },
                        "typ": str,
                        "default": None,
                        "default_str": "None",
                        "help": "No help available.",
                        "deprecated_message": None,
                        "removal_version": None,
                        "removal_hint": None,
                        "choices": ("a", "b", "c"),
                        "comma_separated_choices": "a, b, c",
                    },
                ),
                "deprecated": tuple(),
            },
            "bar": {
                "scope": "bar",
                "description": "The bar goal.",
                "is_goal": True,
                "basic": tuple(),
                "advanced": tuple(),
                "deprecated": tuple(),
            },
        },
        "name_to_goal_info": {
            "bar": {
                "name": "bar",
                "description": "The bar goal.",
                "consumed_scopes": ("somescope", "used_by_bar"),
                "is_implemented": True,
            }
        },
    }
    assert expected_all_help_info_dict == all_help_info_dict
