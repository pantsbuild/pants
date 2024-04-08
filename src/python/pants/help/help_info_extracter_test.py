# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from enum import Enum
from typing import Any, Iterable, List, Optional, Tuple, Union

from pants.base.build_environment import get_buildroot
from pants.build_graph.build_configuration import BuildConfiguration
from pants.engine.goal import GoalSubsystem
from pants.engine.internals.parser import BuildFileSymbolInfo, BuildFileSymbolsInfo
from pants.engine.rules import collect_rules, rule
from pants.engine.target import IntField, RegisteredTargetTypes, StringField, Target
from pants.engine.unions import UnionMembership
from pants.help.help_info_extracter import HelpInfoExtracter, pretty_print_type_hint, to_help_str
from pants.option.config import Config
from pants.option.global_options import GlobalOptions, LogLevelOption
from pants.option.option_types import BoolOption, IntOption, StrListOption
from pants.option.options import Options
from pants.option.parser import Parser
from pants.option.ranked_value import Rank, RankedValue
from pants.option.scope import GLOBAL_SCOPE
from pants.option.subsystem import Subsystem
from pants.util.logging import LogLevel
from pants.util.strutil import help_text


class LogLevelSimple(Enum):
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
    do_test(["-f", "--foo"], {"type": bool}, ["-f", "--[no-]foo"], ["-f", "--foo", "--no-foo"])

    do_test(["--foo"], {}, ["--foo=<str>"], ["--foo"])
    do_test(["--foo"], {"metavar": "xx"}, ["--foo=xx"], ["--foo"])
    do_test(["--foo"], {"type": int}, ["--foo=<int>"], ["--foo"])
    do_test(
        ["--foo"],
        {"type": list},
        ["--foo=\"['<str>', '<str>', ...]\""],
        ["--foo"],
    )
    do_test(
        ["--foo"],
        {"type": list, "member_type": int},
        ['--foo="[<int>, <int>, ...]"'],
        ["--foo"],
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


def test_default() -> None:
    def do_test(args, kwargs, expected_default_str):
        # Defaults are computed in the parser and added into the kwargs, so we
        # must jump through this hoop in this test.
        parser = Parser(
            env={},
            config=Config.load([]),
            scope_info=GlobalOptions.get_scope_info(),
        )
        parser.register(*args, **kwargs)
        oshi = HelpInfoExtracter(parser.scope).get_option_scope_help_info(
            "description", parser, False, "provider"
        )
        assert oshi.description == "description"
        assert oshi.provider == "provider"
        assert len(oshi.basic) == 1
        ohi = oshi.basic[0]
        assert to_help_str(ohi.default) == expected_default_str

    do_test(["--foo"], {"type": bool}, "False")
    do_test(["--foo"], {"type": bool, "default": True}, "True")
    do_test(["--foo"], {}, "None")
    do_test(["--foo"], {"type": int}, "None")
    do_test(["--foo"], {"type": int, "default": 42}, "42")
    do_test(["--foo"], {"type": int, "default": 65536, "default_help_repr": "64KiB"}, "64KiB")
    do_test(["--foo"], {"type": list}, "[]")
    do_test(["--foo"], {"type": dict}, "{}")
    do_test(["--foo"], {"type": LogLevelSimple}, "None")
    do_test(["--foo"], {"type": LogLevelSimple, "default": LogLevelSimple.DEBUG}, "debug")


def test_compute_default():
    def do_test(expected_default: Optional[Any], **kwargs):
        kwargs["default"] = RankedValue(Rank.HARDCODED, kwargs["default"])
        assert expected_default == HelpInfoExtracter.compute_default(**kwargs)

    do_test(False, type=bool, default=False)
    do_test(42, type=int, default=42)
    do_test("foo", type=str, default="foo")
    do_test(None, type=str, default=None)
    do_test([1, 2, 3], type=list, member_type=int, default=[1, 2, 3])
    do_test(LogLevelSimple.INFO, type=LogLevelSimple, default=LogLevelSimple.INFO)


def test_deprecated():
    kwargs = {"removal_version": "999.99.9", "removal_hint": "do not use this"}
    ohi = HelpInfoExtracter("").get_option_help_info(["--foo"], kwargs)
    assert "999.99.9" == ohi.removal_version
    assert "do not use this" == ohi.removal_hint
    assert ohi.deprecated_message is not None
    assert ohi.deprecation_active


def test_not_deprecated():
    ohi = HelpInfoExtracter("").get_option_help_info(["--foo"], {})
    assert ohi.removal_version is None
    assert not ohi.deprecation_active


def test_deprecation_start_version_past():
    kwargs = {"deprecation_start_version": "1.0.0", "removal_version": "999.99.9"}
    ohi = HelpInfoExtracter("").get_option_help_info(["--foo"], kwargs)
    assert "999.99.9" == ohi.removal_version
    assert ohi.deprecation_active


def test_deprecation_start_version_future():
    kwargs = {"deprecation_start_version": "999.99.8", "removal_version": "999.99.9"}
    ohi = HelpInfoExtracter("").get_option_help_info(["--foo"], kwargs)
    assert "999.99.9" == ohi.removal_version
    assert not ohi.deprecation_active


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
    kwargs = {"type": LogLevelSimple}
    ohi = HelpInfoExtracter("").get_option_help_info(["--foo"], kwargs)
    assert ohi.choices == ("info", "debug")


def test_list_of_enum() -> None:
    kwargs = {"type": list, "member_type": LogLevelSimple}
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
        )
        parser.register("--foo", **kwargs)
        oshi = HelpInfoExtracter("").get_option_scope_help_info("", parser, False, "")
        assert exp_to_len(expected_basic) == len(oshi.basic)
        assert exp_to_len(expected_advanced) == len(oshi.advanced)

    do_test({}, expected_basic=True)
    do_test({"advanced": False}, expected_basic=True)
    do_test({"advanced": True}, expected_advanced=True)


def test_get_all_help_info():
    class Global(Subsystem):
        options_scope = GLOBAL_SCOPE
        help = help_text("Global options.")

        opt1 = IntOption(default=42, help="Option 1")
        # This is special in having a short option `-l`. Make sure it works.
        level = LogLevelOption()

        # Options required by the plugin discovery extracter
        backend_packages = StrListOption(help="")
        pythonpath = StrListOption(help="", default=[f"{get_buildroot()}/pants-plugins"])

    class Foo(Subsystem):
        options_scope = "foo"
        help = "A foo."

        opt2 = BoolOption(default=True, advanced=True, help="Option 2")

    class Bar(GoalSubsystem):
        name = "bar"
        help = "The bar goal."
        deprecated_options_scope = "bar-old"
        deprecated_options_scope_removal_version = "9.9.999"

    class QuxField(StringField):
        alias = "qux"
        default = "blahblah"
        help = lambda: "A qux string."

    class QuuxField(IntField):
        alias = "quux"
        required = True
        help = "A quux int.\n\nMust be non-zero. Or zero. Whatever you like really."

    class BazLibrary(Target):
        alias = "baz_library"
        help = "A library of baz-es.\n\nUse it however you like."

        core_fields = [QuxField, QuuxField]

    options = Options.create(
        env={},
        config=Config.load([]),
        known_scope_infos=[Global.get_scope_info(), Foo.get_scope_info(), Bar.get_scope_info()],
        args=["./pants", "--backend-packages=['internal_plugins.releases']"],
        bootstrap_option_values=None,
    )
    Global.register_options_on_scope(options, UnionMembership({}))
    Foo.register_options_on_scope(options, UnionMembership({}))
    Bar.register_options_on_scope(options, UnionMembership({}))

    @rule
    def rule_info_test(foo: Foo) -> Target:  # type: ignore[empty-body]
        """This rule is for testing info extraction only."""
        ...

    def fake_consumed_scopes_mapper(scope: str) -> Tuple[str, ...]:
        return ("somescope", f"used_by_{scope or 'GLOBAL_SCOPE'}")

    bc_builder = BuildConfiguration.Builder()
    bc_builder.register_subsystems("help_info_extracter_test", (Foo, Bar))
    bc_builder.register_target_types("help_info_extracter_test", (BazLibrary,))
    bc_builder.register_rules("help_info_extracter_test", collect_rules(locals()))

    all_help_info = HelpInfoExtracter.get_all_help_info(
        options,
        UnionMembership({}),
        fake_consumed_scopes_mapper,
        RegisteredTargetTypes({BazLibrary.alias: BazLibrary}),
        BuildFileSymbolsInfo.from_info((BuildFileSymbolInfo("dummy", rule_info_test),)),
        bc_builder.create(),
    )

    all_help_info_dict = all_help_info.asdict()
    expected_all_help_info_dict = {
        "scope_to_help_info": {
            GLOBAL_SCOPE: {
                "scope": GLOBAL_SCOPE,
                "description": "Global options.",
                "provider": "",
                "is_goal": False,
                "deprecated_scope": None,
                "basic": (
                    {
                        "display_args": ("--opt1=<int>",),
                        "comma_separated_display_args": "--opt1=<int>",
                        "scoped_cmd_line_args": ("--opt1",),
                        "unscoped_cmd_line_args": ("--opt1",),
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
                        "fromfile": False,
                        "help": "Option 1",
                        "deprecation_active": False,
                        "deprecated_message": None,
                        "removal_version": None,
                        "removal_hint": None,
                        "choices": None,
                        "comma_separated_choices": None,
                        "target_field_name": None,
                    },
                    {
                        "display_args": ("-l=<LogLevel>", "--level=<LogLevel>"),
                        "comma_separated_display_args": "-l=<LogLevel>, --level=<LogLevel>",
                        "scoped_cmd_line_args": ("-l", "--level"),
                        "unscoped_cmd_line_args": ("-l", "--level"),
                        "config_key": "level",
                        "env_var": "PANTS_LEVEL",
                        "value_history": {
                            "ranked_values": (
                                {"rank": Rank.NONE, "value": None, "details": None},
                                {"rank": Rank.HARDCODED, "value": LogLevel.INFO, "details": None},
                            ),
                        },
                        "typ": LogLevel,
                        "default": LogLevel.INFO,
                        "fromfile": False,
                        "help": "Set the logging level.",
                        "deprecation_active": False,
                        "deprecated_message": None,
                        "removal_version": None,
                        "removal_hint": None,
                        "choices": ("trace", "debug", "info", "warn", "error"),
                        "comma_separated_choices": "trace, debug, info, warn, error",
                        "target_field_name": None,
                    },
                    {
                        "choices": None,
                        "comma_separated_choices": None,
                        "comma_separated_display_args": "--backend-packages=\"['<str>', '<str>', ...]\"",
                        "config_key": "backend_packages",
                        "default": [],
                        "deprecated_message": None,
                        "deprecation_active": False,
                        "display_args": ("--backend-packages=\"['<str>', '<str>', ...]\"",),
                        "env_var": "PANTS_BACKEND_PACKAGES",
                        "fromfile": False,
                        "help": "",
                        "removal_hint": None,
                        "removal_version": None,
                        "scoped_cmd_line_args": ("--backend-packages",),
                        "target_field_name": None,
                        "typ": list,
                        "unscoped_cmd_line_args": ("--backend-packages",),
                        "value_history": {
                            "ranked_values": (
                                {"details": "", "rank": Rank.NONE, "value": []},
                                {"details": "", "rank": Rank.HARDCODED, "value": []},
                                {
                                    "details": "from command-line flag",
                                    "rank": Rank.FLAG,
                                    "value": ["internal_plugins.releases"],
                                },
                            ),
                        },
                    },
                    {
                        "choices": None,
                        "comma_separated_choices": None,
                        "comma_separated_display_args": "--pythonpath=\"['<str>', '<str>', ...]\"",
                        "config_key": "pythonpath",
                        "default": [f"{get_buildroot()}/pants-plugins"],
                        "deprecated_message": None,
                        "deprecation_active": False,
                        "display_args": ("--pythonpath=\"['<str>', '<str>', ...]\"",),
                        "env_var": "PANTS_PYTHONPATH",
                        "fromfile": False,
                        "help": "",
                        "removal_hint": None,
                        "removal_version": None,
                        "scoped_cmd_line_args": ("--pythonpath",),
                        "target_field_name": None,
                        "typ": list,
                        "unscoped_cmd_line_args": ("--pythonpath",),
                        "value_history": {
                            "ranked_values": (
                                {"details": "", "rank": Rank.NONE, "value": []},
                                {
                                    "details": "",
                                    "rank": Rank.HARDCODED,
                                    "value": [f"{get_buildroot()}/pants-plugins"],
                                },
                            ),
                        },
                    },
                ),
                "advanced": tuple(),
                "deprecated": tuple(),
            },
            "foo": {
                "scope": "foo",
                "provider": "help_info_extracter_test",
                "description": "A foo.",
                "is_goal": False,
                "deprecated_scope": None,
                "basic": (),
                "advanced": (
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
                        "fromfile": False,
                        "help": "Option 2",
                        "deprecation_active": False,
                        "deprecated_message": None,
                        "removal_version": None,
                        "removal_hint": None,
                        "choices": None,
                        "comma_separated_choices": None,
                        "target_field_name": None,
                    },
                ),
                "deprecated": tuple(),
            },
            "bar": {
                "scope": "bar",
                "provider": "help_info_extracter_test",
                "description": "The bar goal.",
                "is_goal": True,
                "deprecated_scope": "bar-old",
                "basic": tuple(),
                "advanced": tuple(),
                "deprecated": tuple(),
            },
            "bar-old": {
                "scope": "bar-old",
                "provider": "help_info_extracter_test",
                "description": "The bar goal.",
                "is_goal": True,
                "deprecated_scope": "bar-old",
                "basic": tuple(),
                "advanced": tuple(),
                "deprecated": tuple(),
            },
        },
        "name_to_goal_info": {
            "bar": {
                "name": "bar",
                "provider": "help_info_extracter_test",
                "description": "The bar goal.",
                "consumed_scopes": ("somescope", "used_by_bar"),
                "is_implemented": True,
            },
            "bar-old": {
                "name": "bar",
                "provider": "help_info_extracter_test",
                "description": "The bar goal.",
                "consumed_scopes": ("somescope", "used_by_bar-old"),
                "is_implemented": True,
            },
        },
        "name_to_target_type_info": {
            "baz_library": {
                "alias": "baz_library",
                "provider": "help_info_extracter_test",
                "summary": "A library of baz-es.",
                "description": "A library of baz-es.\n\nUse it however you like.",
                "fields": (
                    {
                        "alias": "qux",
                        "provider": "",
                        "default": "'blahblah'",
                        "description": "A qux string.",
                        "required": False,
                        "type_hint": "str | None",
                    },
                    {
                        "alias": "quux",
                        "provider": "",
                        "default": None,
                        "description": "A quux int.\n\nMust be non-zero. Or zero. "
                        "Whatever you like really.",
                        "required": True,
                        "type_hint": "int",
                    },
                ),
            }
        },
        "name_to_rule_info": {
            "construct_scope_foo": {
                "description": None,
                "documentation": "A foo.",
                "awaitables": ("Get(ScopedOptions, Scope, ..)",),
                "input_types": (),
                "name": "construct_scope_foo",
                "output_type": "Foo",
                "provider": "help_info_extracter_test",
            },
            "pants.help.help_info_extracter_test.test_get_all_help_info.rule_info_test": {
                "description": None,
                "documentation": "This rule is for testing info extraction only.",
                "awaitables": (),
                "input_types": ("Foo",),
                "name": "pants.help.help_info_extracter_test.test_get_all_help_info.rule_info_test",
                "output_type": "Target",
                "provider": "help_info_extracter_test",
            },
        },
        "name_to_api_type_info": {
            "pants.help.help_info_extracter_test.Foo": {
                "consumed_by_rules": (
                    "pants.help.help_info_extracter_test.test_get_all_help_info.rule_info_test",
                ),
                "dependents": ("help_info_extracter_test",),
                "dependencies": ("pants.option.scope",),
                "documentation": None,
                "is_union": False,
                "module": "pants.help.help_info_extracter_test",
                "name": "Foo",
                "provider": "help_info_extracter_test",
                "returned_by_rules": ("construct_scope_foo",),
                "union_members": (),
                "union_type": None,
                "used_in_rules": (),
            },
            "pants.engine.target.Target": {
                "consumed_by_rules": (),
                "dependents": (),
                "dependencies": (),
                "documentation": (
                    "A Target represents an addressable set of metadata.\n\n    Set the `help` "
                    "class property with a description, which will be used in `./pants help`. For "
                    "the\n    best rendering, use soft wrapping (e.g. implicit string concatenation"
                    ") within paragraphs, but\n    hard wrapping (`\n`) to separate distinct "
                    "paragraphs and/or lists.\n    "
                ),
                "is_union": False,
                "module": "pants.engine.target",
                "name": "Target",
                "provider": "help_info_extracter_test",
                "returned_by_rules": (
                    "pants.help.help_info_extracter_test.test_get_all_help_info.rule_info_test",
                ),
                "union_members": (),
                "union_type": None,
                "used_in_rules": (),
            },
            "pants.option.scope.Scope": {
                "consumed_by_rules": (),
                "dependents": (),
                "dependencies": (),
                "documentation": "An options scope.",
                "is_union": False,
                "module": "pants.option.scope",
                "name": "Scope",
                "provider": "pants.option.scope",
                "returned_by_rules": (),
                "union_members": (),
                "union_type": None,
                "used_in_rules": ("construct_scope_foo",),
            },
        },
        "name_to_backend_help_info": {
            "pants.backend.python": {
                "description": "Support for Python.\n\nSee https://www.pantsbuild.org/docs/python-backend.",
                "enabled": False,
                "name": "pants.backend.python",
                "provider": "pants",
            },
            "internal_plugins.releases": {
                "description": "",
                "enabled": True,
                "name": "internal_plugins.releases",
                "provider": "pants-plugins",
            },
            "plugin.dist": {
                "description": "This is an empty Pants plugin for the help info extracter test.",
                "enabled": True,
                "name": "plugin.dist",
                "provider": "dummy-plugin",
            },
        },
        "name_to_build_file_info": {
            "dummy": {
                "name": "dummy",
                "is_target": False,
                "signature": (
                    "(foo: pants.help.help_info_extracter_test.test_get_all_help_info.<locals>.Foo)"
                    " -> pants.engine.target.Target"
                ),
                "documentation": "This rule is for testing info extraction only.",
            },
        },
        "env_var_to_help_info": {
            "PANTS_OPT1": {
                "display_args": ("--opt1=<int>",),
                "comma_separated_display_args": "--opt1=<int>",
                "scoped_cmd_line_args": ("--opt1",),
                "unscoped_cmd_line_args": ("--opt1",),
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
                "fromfile": False,
                "help": "Option 1",
                "deprecation_active": False,
                "deprecated_message": None,
                "removal_version": None,
                "removal_hint": None,
                "choices": None,
                "comma_separated_choices": None,
                "target_field_name": None,
            },
            "PANTS_LEVEL": {
                "display_args": ("-l=<LogLevel>", "--level=<LogLevel>"),
                "comma_separated_display_args": "-l=<LogLevel>, --level=<LogLevel>",
                "scoped_cmd_line_args": ("-l", "--level"),
                "unscoped_cmd_line_args": ("-l", "--level"),
                "config_key": "level",
                "env_var": "PANTS_LEVEL",
                "value_history": {
                    "ranked_values": (
                        {"rank": Rank.NONE, "value": None, "details": None},
                        {"rank": Rank.HARDCODED, "value": LogLevel.INFO, "details": None},
                    ),
                },
                "typ": LogLevel,
                "default": LogLevel.INFO,
                "fromfile": False,
                "help": "Set the logging level.",
                "deprecation_active": False,
                "deprecated_message": None,
                "removal_version": None,
                "removal_hint": None,
                "choices": ("trace", "debug", "info", "warn", "error"),
                "comma_separated_choices": "trace, debug, info, warn, error",
                "target_field_name": None,
            },
            "PANTS_BACKEND_PACKAGES": {
                "choices": None,
                "comma_separated_choices": None,
                "comma_separated_display_args": "--backend-packages=\"['<str>', '<str>', ...]\"",
                "config_key": "backend_packages",
                "default": [],
                "deprecated_message": None,
                "deprecation_active": False,
                "display_args": ("--backend-packages=\"['<str>', '<str>', ...]\"",),
                "env_var": "PANTS_BACKEND_PACKAGES",
                "fromfile": False,
                "help": "",
                "removal_hint": None,
                "removal_version": None,
                "scoped_cmd_line_args": ("--backend-packages",),
                "target_field_name": None,
                "typ": list,
                "unscoped_cmd_line_args": ("--backend-packages",),
                "value_history": {
                    "ranked_values": (
                        {"details": "", "rank": Rank.NONE, "value": []},
                        {"details": "", "rank": Rank.HARDCODED, "value": []},
                        {
                            "details": "from command-line flag",
                            "rank": Rank.FLAG,
                            "value": ["internal_plugins.releases"],
                        },
                    ),
                },
            },
            "PANTS_PYTHONPATH": {
                "choices": None,
                "comma_separated_choices": None,
                "comma_separated_display_args": "--pythonpath=\"['<str>', '<str>', ...]\"",
                "config_key": "pythonpath",
                "default": [f"{get_buildroot()}/pants-plugins"],
                "deprecated_message": None,
                "deprecation_active": False,
                "display_args": ("--pythonpath=\"['<str>', '<str>', ...]\"",),
                "env_var": "PANTS_PYTHONPATH",
                "fromfile": False,
                "help": "",
                "removal_hint": None,
                "removal_version": None,
                "scoped_cmd_line_args": ("--pythonpath",),
                "target_field_name": None,
                "typ": list,
                "unscoped_cmd_line_args": ("--pythonpath",),
                "value_history": {
                    "ranked_values": (
                        {"details": "", "rank": Rank.NONE, "value": []},
                        {
                            "details": "",
                            "rank": Rank.HARDCODED,
                            "value": [f"{get_buildroot()}/pants-plugins"],
                        },
                    ),
                },
            },
            "PANTS_FOO_OPT2": {
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
                "fromfile": False,
                "help": "Option 2",
                "deprecation_active": False,
                "deprecated_message": None,
                "removal_version": None,
                "removal_hint": None,
                "choices": None,
                "comma_separated_choices": None,
                "target_field_name": None,
            },
        },
    }

    # Break down this colossal structure into pieces so it is easier to spot where the issue is.
    # Check keys equality first, then contents
    assert set(expected_all_help_info_dict) == set(all_help_info_dict)
    for key in all_help_info_dict:
        actual = all_help_info_dict[key]
        expected = expected_all_help_info_dict[key]
        assert (key, expected) == (key, actual)


def test_pretty_print_type_hint() -> None:
    assert pretty_print_type_hint(str) == "str"
    assert pretty_print_type_hint(int) == "int"
    assert pretty_print_type_hint(None) == "None"

    class ExampleCls:
        pass

    assert pretty_print_type_hint(ExampleCls) == "ExampleCls"

    # Transform Unions to use `|`
    assert pretty_print_type_hint(Union[int, float]) == "int | float"
    assert pretty_print_type_hint(Optional[int]) == "int | None"
    # NB: `Iterable[List[ExampleCls]]` will use the full module name for `ExampleCls`. We can't
    # easily control that because it comes from the __repr__ implementation for `typing.Iterable`.
    example_cls_repr = (
        f"{__name__}.{test_pretty_print_type_hint.__name__}.<locals>.{ExampleCls.__name__}"
    )
    assert (
        pretty_print_type_hint(Union[Iterable[List[ExampleCls]], Optional[float], Any])
        == f"Iterable[List[{example_cls_repr}]] | float | None | Any"
    )
