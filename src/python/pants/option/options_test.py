# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import os
import shlex
import unittest.mock
from enum import Enum
from functools import partial
from textwrap import dedent
from typing import Any, Dict, List, Optional, Union, cast

import toml
import yaml
from packaging.version import Version

from pants.base.deprecated import CodeRemovedError
from pants.base.hash_utils import CoercingEncoder
from pants.option.config import Config
from pants.option.custom_types import UnsetBool, file_option, shell_str, target_option
from pants.option.errors import (
    BooleanConversionError,
    BooleanOptionNameWithNo,
    FromfileError,
    ImplicitValIsNone,
    InvalidKwarg,
    InvalidMemberType,
    MemberTypeNotAllowed,
    MutuallyExclusiveOptionError,
    NoOptionNames,
    OptionAlreadyRegistered,
    OptionNameDash,
    OptionNameDoubleDash,
    ParseError,
    RecursiveSubsystemOption,
    Shadowing,
)
from pants.option.global_options import GlobalOptions
from pants.option.optionable import Optionable
from pants.option.options import Options
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.option.parser import Parser
from pants.option.ranked_value import Rank, RankedValue
from pants.option.scope import GLOBAL_SCOPE, ScopeInfo
from pants.testutil.option.fakes import create_options
from pants.testutil.test_base import TestBase
from pants.util.collections import assert_single_element
from pants.util.contextutil import temporary_file, temporary_file_path
from pants.util.dirutil import safe_mkdtemp
from pants.util.strutil import safe_shlex_join

_FAKE_CUR_VERSION = "1.0.0.dev0"


def global_scope() -> ScopeInfo:
    return ScopeInfo(GLOBAL_SCOPE, ScopeInfo.GLOBAL, GlobalOptions)


def task(scope: str) -> ScopeInfo:
    return ScopeInfo(scope, ScopeInfo.TASK)


def intermediate(scope: str) -> ScopeInfo:
    return ScopeInfo(scope, ScopeInfo.INTERMEDIATE)


def subsystem(scope: str) -> ScopeInfo:
    return ScopeInfo(scope, ScopeInfo.SUBSYSTEM)


class OptionsTest(TestBase):
    @staticmethod
    def _create_config(config: Optional[Dict[str, Dict[str, str]]] = None) -> Config:
        with open(os.path.join(safe_mkdtemp(), "test_config.toml"), "w") as fp:
            toml.dump(config or {}, fp)
        return Config.load(config_paths=[fp.name])

    def _parse(
        self,
        *,
        flags: str = "",
        env: Optional[Dict[str, str]] = None,
        config: Optional[Dict[str, Dict[str, Any]]] = None,
        bootstrap_option_values=None,
    ) -> Options:
        args = ["./pants", *shlex.split(flags)]
        options = Options.create(
            env=env or {},
            config=self._create_config(config),
            known_scope_infos=OptionsTest._known_scope_infos,
            args=args,
            bootstrap_option_values=bootstrap_option_values,
        )
        self._register(options)
        return options

    _known_scope_infos = [
        global_scope(),
        intermediate("compile"),
        task("compile.java"),
        task("compile.scala"),
        task("cache.compile.scala"),
        intermediate("stale"),
        intermediate("test"),
        task("test.junit"),
        subsystem("passconsumer"),
        task("simple"),
        task("simple-dashed"),
        task("scoped.a.bit"),
        task("scoped.and-dashed"),
        task("fromfile"),
        task("fingerprinting"),
        task("enum-opt"),
        task("separate-enum-opt-scope"),
    ]

    class SomeEnumOption(Enum):
        a_value = "a-value"
        another_value = "another-value"

    def _register(self, options):
        def register_global(*args, **kwargs):
            options.register(GLOBAL_SCOPE, *args, **kwargs)

        register_global("-z", "--verbose", type=bool, help="Verbose output.", recursive=True)
        register_global("-n", "--num", type=int, default=99, recursive=True, fingerprint=True)
        register_global("--y", type=list, member_type=int)
        register_global(
            "--v2", help="Two-letter long-form option, used to test option name suggestions."
        )
        register_global("--config-override", type=list)

        register_global("--pants-foo")
        register_global("--bar-baz")
        register_global("--store-true-flag", type=bool, fingerprint=True)
        register_global("--store-false-flag", type=bool, implicit_value=False)
        register_global("--store-true-def-true-flag", type=bool, default=True)
        register_global("--store-true-def-false-flag", type=bool, default=False)
        register_global(
            "--store-false-def-false-flag", type=bool, implicit_value=False, default=False
        )
        register_global(
            "--store-false-def-true-flag", type=bool, implicit_value=False, default=True
        )
        register_global("--def-unset-bool-flag", type=bool, default=UnsetBool)

        # Choices.
        register_global("--str-choices", choices=["foo", "bar"])
        register_global("--int-choices", choices=[42, 99], type=list, member_type=int)

        # Custom types.
        register_global("--listy", type=list, member_type=int, default="[1, 2, 3]")
        register_global("--dicty", type=dict, default='{"a": "b"}')
        register_global(
            "--dict-listy", type=list, member_type=dict, default='[{"a": 1, "b": 2}, {"c": 3}]'
        )
        register_global("--targety", type=target_option, default="//:a")
        register_global(
            "--target-listy", type=list, member_type=target_option, default=["//:a", "//:b"]
        )
        register_global("--filey", type=file_option, default=None)
        register_global("--file-listy", type=list, member_type=file_option)
        register_global(
            "--shell-str-listy",
            type=list,
            member_type=shell_str,
            default="--default1 --default2=test",
        )

        # Implicit value.
        register_global("--implicit-valuey", default="default", implicit_value="implicit")

        # For the design doc example test.
        register_global("--a", type=int, recursive=True)
        register_global("--b", type=int, recursive=True)

        # Deprecated global options
        register_global(
            "--global-crufty",
            removal_version="999.99.9.dev0",
            removal_hint="use a less crufty global option",
        )
        register_global(
            "--global-crufty-boolean",
            type=bool,
            removal_version="999.99.9.dev0",
            removal_hint="say no to crufty global options",
        )
        register_global(
            "--global-delayed-deprecated-option",
            removal_version="999.99.9.dev0",
            deprecation_start_version="500.0.0.dev0",
        )
        register_global(
            "--global-delayed-but-already-passed-deprecated-option",
            removal_version="999.99.9.dev0",
            deprecation_start_version=_FAKE_CUR_VERSION,
        )

        # Test that an option past the `removal_version` fails at option registration time.
        with self.assertRaises(CodeRemovedError):
            register_global(
                "--global-crufty-expired",
                removal_version="0.0.1.dev0",
                removal_hint="use a less crufty global option",
            )

        # Mutual Exclusive options
        register_global("--mutex-foo", mutually_exclusive_group="mutex")
        register_global("--mutex-bar", mutually_exclusive_group="mutex")
        register_global("--mutex-baz", mutually_exclusive_group="mutex")

        register_global("--new-name")
        register_global("--old-name", mutually_exclusive_group="new_name")

        # For the design doc example test.
        options.register("compile", "--c", type=int, recursive=True)

        # Test deprecated options with a scope
        options.register("stale", "--still-good")
        options.register(
            "stale",
            "--crufty",
            removal_version="999.99.9.dev0",
            removal_hint="use a less crufty stale scoped option",
        )
        options.register(
            "stale",
            "--crufty-boolean",
            type=bool,
            removal_version="999.99.9.dev0",
            removal_hint="say no to crufty, stale scoped options",
        )

        # Test mutual exclusive options with a scope
        options.register("stale", "--mutex-a", mutually_exclusive_group="crufty_mutex")
        options.register("stale", "--mutex-b", mutually_exclusive_group="crufty_mutex")
        options.register("stale", "--crufty-old", mutually_exclusive_group="crufty_new")
        options.register("stale", "--crufty-new")

        # For task identity test
        options.register("compile.scala", "--modifycompile", fingerprint=True)
        options.register("compile.scala", "--modifylogs")
        options.register(
            "compile.scala",
            "--modifypassthrough",
            fingerprint=True,
            passthrough=True,
            type=list,
            member_type=str,
        )

        # For scoped env vars test
        options.register("simple", "--spam")
        options.register("simple-dashed", "--spam")
        options.register("scoped.a.bit", "--spam")
        options.register("scoped.and-dashed", "--spam")

        # For fromfile test
        options.register("fromfile", "--string")
        options.register("fromfile", "--intvalue", type=int)
        options.register("fromfile", "--dictvalue", type=dict)
        options.register("fromfile", "--listvalue", type=list)
        options.register("fromfile", "--appendvalue", type=list, member_type=int)

        # For fingerprint tests
        options.register("fingerprinting", "--inverted")  # Implicitly: daemon=True
        options.register("fingerprinting", "--definitely-not-inverted", daemon=False)
        options.register("fingerprinting", "--fingerprinted", fingerprint=True)
        options.register("fingerprinting", "--definitely-not-fingerprinted", fingerprint=False)

        # For enum tests
        options.register("enum-opt", "--some-enum", type=self.SomeEnumOption)
        # For testing the default value
        options.register(
            "separate-enum-opt-scope",
            "--some-enum-with-default",
            default=self.SomeEnumOption.a_value,
            type=self.SomeEnumOption,
        )

    def test_env_var_of_type_int(self) -> None:
        create_options_object = partial(
            Options.create,
            config=self._create_config(),
            known_scope_infos=OptionsTest._known_scope_infos,
            args=shlex.split("./pants"),
        )
        options = create_options_object(env={"PANTS_FOO_BAR": "123"})
        options.register(GLOBAL_SCOPE, "--foo-bar", type=int)
        self.assertEqual(123, options.for_global_scope().foo_bar)

        options = create_options_object(env={"PANTS_FOO_BAR": "['123','456']"})
        options.register(GLOBAL_SCOPE, "--foo-bar", type=list, member_type=int)
        self.assertEqual([123, 456], options.for_global_scope().foo_bar)

    def test_arg_scoping(self) -> None:
        # Some basic smoke tests.
        options = self._parse(flags="--verbose")
        self.assertEqual(True, options.for_global_scope().verbose)
        options = self._parse(flags="-z compile path/to/tgt")
        self.assertEqual(["path/to/tgt"], options.specs)
        self.assertEqual(True, options.for_global_scope().verbose)

        with self.assertRaises(ParseError):
            self._parse(flags="--unregistered-option compile").for_global_scope()

        # Scoping of different values of the same option.
        # Also tests the --no-* boolean flag inverses.
        options = self._parse(flags="--verbose compile.java --no-verbose")
        self.assertEqual(True, options.for_global_scope().verbose)
        self.assertEqual(True, options.for_scope("compile").verbose)
        self.assertEqual(False, options.for_scope("compile.java").verbose)

        options = self._parse(
            flags="--verbose compile --no-verbose compile.java -z test test.junit --no-verbose"
        )
        self.assertEqual(True, options.for_global_scope().verbose)
        self.assertEqual(False, options.for_scope("compile").verbose)
        self.assertEqual(True, options.for_scope("compile.java").verbose)
        self.assertEqual(True, options.for_scope("test").verbose)
        self.assertEqual(False, options.for_scope("test.junit").verbose)

        # Test list-typed option.
        global_options = self._parse(config={"DEFAULT": {"y": ["88", "-99"]}}).for_global_scope()
        self.assertEqual([88, -99], global_options.y)

        global_options = self._parse(
            flags="--y=5 --y=-6 --y=77", config={"DEFAULT": {"y": ["88", "-99"]}}
        ).for_global_scope()
        self.assertEqual([88, -99, 5, -6, 77], global_options.y)

        global_options = self._parse().for_global_scope()
        self.assertEqual([], global_options.y)

        global_options = self._parse(
            env={"PANTS_CONFIG_OVERRIDE": "['123','456']"}
        ).for_global_scope()
        self.assertEqual(["123", "456"], global_options.config_override)

        global_options = self._parse(env={"PANTS_CONFIG_OVERRIDE": "['']"}).for_global_scope()
        self.assertEqual([""], global_options.config_override)

        global_options = self._parse(
            flags="--listy='[1, 2]'", config={"DEFAULT": {"listy": "[3, 4]"}}
        ).for_global_scope()
        self.assertEqual([1, 2], global_options.listy)

        # Test dict-typed option.
        global_options = self._parse(flags='--dicty=\'{"c": "d"}\'').for_global_scope()
        self.assertEqual({"c": "d"}, global_options.dicty)

        # Test list-of-dict-typed option.
        global_options = self._parse(
            flags='--dict-listy=\'[{"c": "d"}, {"e": "f"}]\''
        ).for_global_scope()
        self.assertEqual([{"c": "d"}, {"e": "f"}], global_options.dict_listy)

        # Test target-typed option.
        global_options = self._parse().for_global_scope()
        self.assertEqual("//:a", global_options.targety)
        global_options = self._parse(flags="--targety=//:foo").for_global_scope()
        self.assertEqual("//:foo", global_options.targety)

        # Test list-of-target-typed option.
        global_options = self._parse(
            flags='--target-listy=\'["//:foo", "//:bar"]\''
        ).for_global_scope()
        self.assertEqual(["//:foo", "//:bar"], global_options.target_listy)

        # Test file-typed option.
        with temporary_file_path() as fp:
            global_options = self._parse(flags=f'--filey="{fp}"').for_global_scope()
            self.assertEqual(fp, global_options.filey)

        # Test list-of-file-typed option.
        with temporary_file_path() as fp1:
            with temporary_file_path() as fp2:
                global_options = self._parse(
                    flags=f'--file-listy="{fp1}" --file-listy="{fp2}"'
                ).for_global_scope()
                self.assertEqual([fp1, fp2], global_options.file_listy)

    def test_explicit_boolean_values(self) -> None:
        def assert_boolean_value(*, arg: str, expected: bool) -> None:
            global_options = self._parse(flags=f"--verbose={arg}").for_global_scope()
            assert global_options.verbose is expected

        assert_boolean_value(arg="false", expected=False)
        assert_boolean_value(arg="False", expected=False)
        assert_boolean_value(arg="true", expected=True)
        assert_boolean_value(arg="True", expected=True)

    def test_boolean_defaults(self) -> None:
        global_options = self._parse().for_global_scope()
        self.assertFalse(global_options.store_true_flag)
        self.assertTrue(global_options.store_false_flag)
        self.assertFalse(global_options.store_true_def_false_flag)
        self.assertTrue(global_options.store_true_def_true_flag)
        self.assertFalse(global_options.store_false_def_false_flag)
        self.assertTrue(global_options.store_false_def_true_flag)
        self.assertIsNone(global_options.def_unset_bool_flag)

    def test_boolean_set_option(self) -> None:
        global_options = self._parse(
            flags="--store-true-flag --store-false-flag --store-true-def-true-flag "
            "--store-true-def-false-flag --store-false-def-true-flag --store-false-def-false-flag "
            "--def-unset-bool-flag"
        ).for_global_scope()
        self.assertTrue(global_options.store_true_flag)
        self.assertFalse(global_options.store_false_flag)
        self.assertTrue(global_options.store_true_def_false_flag)
        self.assertTrue(global_options.store_true_def_true_flag)
        self.assertFalse(global_options.store_false_def_false_flag)
        self.assertFalse(global_options.store_false_def_true_flag)
        self.assertTrue(global_options.def_unset_bool_flag)

    def test_boolean_negate_option(self) -> None:
        global_options = self._parse(
            flags="--no-store-true-flag --no-store-false-flag  --no-store-true-def-true-flag "
            "--no-store-true-def-false-flag --no-store-false-def-true-flag "
            "--no-store-false-def-false-flag --no-def-unset-bool-flag"
        ).for_global_scope()
        self.assertFalse(global_options.store_true_flag)
        self.assertTrue(global_options.store_false_flag)
        self.assertFalse(global_options.store_true_def_false_flag)
        self.assertFalse(global_options.store_true_def_true_flag)
        self.assertTrue(global_options.store_false_def_false_flag)
        self.assertTrue(global_options.store_false_def_true_flag)
        self.assertFalse(global_options.def_unset_bool_flag)

    def test_boolean_config_override(self) -> None:
        def assert_options_set(value: bool) -> None:
            global_options = self._parse(
                config={
                    "DEFAULT": {
                        "store_true_flag": value,
                        "store_false_flag": value,
                        "store_true_def_true_flag": value,
                        "store_true_def_false_flag": value,
                        "store_false_def_true_flag": value,
                        "store_false_def_false_flag": value,
                        "def_unset_bool_flag": value,
                    },
                },
            ).for_global_scope()
            assert global_options.store_true_flag == value
            assert global_options.store_false_flag == value
            assert global_options.store_true_def_false_flag == value
            assert global_options.store_true_def_true_flag == value
            assert global_options.store_false_def_false_flag == value
            assert global_options.store_false_def_true_flag == value
            assert global_options.def_unset_bool_flag == value

        assert_options_set(False)
        assert_options_set(True)

    def test_boolean_invalid_value(self) -> None:
        def assert_invalid_value(val) -> None:
            with self.assertRaises(BooleanConversionError):
                self._parse(config={"DEFAULT": {"store_true_flag": val}}).for_global_scope()

        assert_invalid_value(11)
        assert_invalid_value("AlmostTrue")

    def test_list_option(self) -> None:
        def check(
            *,
            expected: List[int],
            flags: str = "",
            env_val: Optional[str] = None,
            config_val: Optional[str] = None,
        ) -> None:
            env = {"PANTS_GLOBAL_LISTY": env_val} if env_val else None
            config = {"GLOBAL": {"listy": config_val}} if config_val else None
            global_options = self._parse(flags=flags, env=env, config=config).for_global_scope()
            assert global_options.listy == expected

        default = [1, 2, 3]
        check(expected=default)

        # Appending to the default.
        check(flags="--listy=4", expected=[*default, 4])
        check(flags="--listy=4 --listy=5", expected=[*default, 4, 5])
        check(flags="--listy=+[4,5]", expected=[*default, 4, 5])

        # Filtering from the default.
        check(flags="--listy=-[2]", expected=[1, 3])

        # Replacing the default.
        check(flags="--listy=[4,5]", expected=[4, 5])

        # Appending across env, config and flags (in the right order).
        check(
            flags="--listy=+[8,9]",
            env_val="+[6,7]",
            config_val="+[4,5]",
            expected=[*default, 4, 5, 6, 7, 8, 9],
        )

        # Appending and filtering across env, config and flags (in the right order).
        check(
            flags="--listy=-[1,5,6]", env_val="+[6,7]", config_val="+[4,5]", expected=[2, 3, 4, 7],
        )
        check(
            flags="--listy=+[8,9]",
            env_val="-[4,5]",
            config_val="+[4,5],-[3]",
            expected=[1, 2, 8, 9],
        )

        # Overwriting from env, then appending and filtering.
        check(
            flags="--listy=+[8,9],-[6]", env_val="[6,7]", config_val="+[4,5]", expected=[7, 8, 9],
        )

        # Overwriting from config, then appending.
        check(
            flags="--listy=+[8,9]",
            env_val="+[6,7]",
            config_val="[4,5]",
            expected=[4, 5, 6, 7, 8, 9],
        )

        # Overwriting from flags.
        check(
            flags="--listy=[8,9]", env_val="+[6,7]", config_val="+[4,5],-[8]", expected=[8, 9],
        )

        # Filtering all instances of repeated values.
        check(
            flags="--listy=-[5]",
            config_val="[1, 2, 5, 3, 4, 5, 6, 5, 5]",
            expected=[1, 2, 3, 4, 6],
        )

        # Filtering a value even though it was appended again at a higher rank.
        check(
            flags="--listy=+[4]", env_val="-[4]", config_val="+[4,5]", expected=[*default, 5],
        )

        # Filtering a value even though it was appended again at the same rank.
        check(
            env_val="-[4],+[4]", config_val="+[4,5]", expected=[*default, 5],
        )

        # Overwriting cancels filters.
        check(env_val="[4]", config_val="-[4]", expected=[4])

    def test_dict_list_option(self) -> None:
        def check(
            *,
            expected: List[Dict[str, int]],
            flags: str = "",
            env_val: Optional[str] = None,
            config_val: Optional[str] = None,
        ) -> None:
            env = {"PANTS_GLOBAL_DICT_LISTY": env_val} if env_val else None
            config = {"GLOBAL": {"dict_listy": config_val}} if config_val else None
            global_options = self._parse(flags=flags, env=env, config=config).for_global_scope()
            assert global_options.dict_listy == expected

        default = [{"a": 1, "b": 2}, {"c": 3}]
        one_element_appended = [*default, {"d": 4, "e": 5}]
        two_elements_appended = [*one_element_appended, {"f": 6}]
        replaced = [{"d": 4, "e": 5}, {"f": 6}]

        check(expected=default)

        check(flags='--dict-listy=\'{"d": 4, "e": 5}\'', expected=one_element_appended)
        check(
            flags='--dict-listy=\'{"d": 4, "e": 5}\' --dict-listy=\'{"f": 6}\'',
            expected=two_elements_appended,
        )
        check(
            flags='--dict-listy=\'+[{"d": 4, "e": 5}, {"f": 6}]\'', expected=two_elements_appended,
        )
        check(flags='--dict-listy=\'[{"d": 4, "e": 5}, {"f": 6}]\'', expected=replaced)

        check(env_val='{"d": 4, "e": 5}', expected=one_element_appended)
        check(env_val='+[{"d": 4, "e": 5}, {"f": 6}]', expected=two_elements_appended)
        check(env_val='[{"d": 4, "e": 5}, {"f": 6}]', expected=replaced)

        check(config_val='{"d": 4, "e": 5}', expected=one_element_appended)
        check(config_val='+[{"d": 4, "e": 5}, {"f": 6}]', expected=two_elements_appended)
        check(config_val='[{"d": 4, "e": 5}, {"f": 6}]', expected=replaced)

    def test_target_list_option(self) -> None:
        def check(
            *,
            expected: List[str],
            flags: str = "",
            env_val: Optional[str] = None,
            config_val: Optional[str] = None,
        ) -> None:
            env = {"PANTS_GLOBAL_TARGET_LISTY": env_val} if env_val else None
            config = {"GLOBAL": {"target_listy": config_val}} if config_val else None
            global_options = self._parse(flags=flags, env=env, config=config).for_global_scope()
            assert global_options.target_listy == expected

        default = ["//:a", "//:b"]
        specified_args = ["//:c", "//:d"]
        all_args = [*default, *specified_args]

        check(expected=default)

        check(flags="--target-listy=//:c --target-listy=//:d", expected=all_args)
        check(flags='--target-listy=\'+["//:c", "//:d"]\'', expected=all_args)
        check(flags='--target-listy=\'["//:c", "//:d"]\'', expected=specified_args)

        check(env_val="//:c", expected=[*default, "//:c"])
        check(env_val='+["//:c", "//:d"]', expected=all_args)
        check(env_val='["//:c", "//:d"]', expected=specified_args)

        check(config_val="//:c", expected=[*default, "//:c"])
        check(config_val='+["//:c", "//:d"]', expected=all_args)
        check(config_val='["//:c", "//:d"]', expected=specified_args)

    def test_shell_str_list(self) -> None:
        def check(
            *,
            expected: List[str],
            flags: str = "",
            env_val: Optional[str] = None,
            config_val: Optional[str] = None,
        ) -> None:
            env = {"PANTS_GLOBAL_SHELL_STR_LISTY": env_val} if env_val else None
            config = {"GLOBAL": {"shell_str_listy": config_val}} if config_val else None
            global_options = self._parse(flags=flags, env=env, config=config).for_global_scope()
            assert global_options.shell_str_listy == expected

        default = ["--default1", "--default2=test"]
        specified_args = ["arg1", "arg2=foo", "--arg3"]
        all_args = [*default, *specified_args]

        check(expected=default)

        check(
            flags="--shell-str-listy='arg1 arg2=foo' --shell-str-listy='--arg3'", expected=all_args
        )
        check(flags="""--shell-str-listy='+["arg1 arg2=foo", "--arg3"]'""", expected=all_args)
        check(flags="""--shell-str-listy='["arg1 arg2=foo", "--arg3"]'""", expected=specified_args)

        check(env_val="arg1 arg2=foo --arg3", expected=all_args)
        check(env_val='+["arg1 arg2=foo", "--arg3"]', expected=all_args)
        check(env_val='["arg1 arg2=foo", "--arg3"]', expected=specified_args)

        check(config_val="arg1 arg2=foo --arg3", expected=all_args)
        check(config_val='+["arg1 arg2=foo", "--arg3"]', expected=all_args)
        check(config_val='["arg1 arg2=foo", "--arg3"]', expected=specified_args)

    def test_dict_option(self) -> None:
        def check(
            *, expected: Dict[str, str], flags: str = "", config_val: Optional[str] = None,
        ) -> None:
            config = {"GLOBAL": {"dicty": config_val}} if config_val else None
            global_options = self._parse(flags=flags, config=config).for_global_scope()
            assert global_options.dicty == expected

        default = {"a": "b"}
        specified_args = {"c": "d"}
        all_args = {**default, **specified_args}

        check(expected=default)

        check(flags='--dicty=\'{"c": "d"}\'', expected=specified_args)
        check(flags='--dicty=\'+{"c": "d"}\'', expected=all_args)

        check(config_val='{"c": "d"}', expected=specified_args)
        check(config_val='+{"c": "d"}', expected=all_args)
        check(
            config_val='+{"c": "d"}',
            flags='--dicty=\'+{"e": "f"}\'',
            expected={**all_args, "e": "f"},
        )

        # Check that highest rank wins if we have multiple values for the same key.
        check(config_val='+{"a": "b+", "c": "d"}', expected={"a": "b+", "c": "d"})
        check(
            config_val='+{"a": "b+", "c": "d"}',
            flags='--dicty=\'+{"a": "b++"}\'',
            expected={"a": "b++", "c": "d"},
        )

    def test_defaults(self) -> None:
        # Hard-coded defaults.
        options = self._parse(flags="compile.java -n33")
        self.assertEqual(99, options.for_global_scope().num)
        self.assertEqual(99, options.for_scope("compile").num)
        self.assertEqual(33, options.for_scope("compile.java").num)
        self.assertEqual(99, options.for_scope("test").num)
        self.assertEqual(99, options.for_scope("test.junit").num)

        options = self._parse(flags="compile -n22 compile.java -n33")
        self.assertEqual(99, options.for_global_scope().num)
        self.assertEqual(22, options.for_scope("compile").num)
        self.assertEqual(33, options.for_scope("compile.java").num)

        # Get defaults from config and environment.
        config = {"DEFAULT": {"num": "88"}, "compile": {"num": "77"}, "compile.java": {"num": "66"}}
        options = self._parse(flags="compile.java -n22", config=config)
        self.assertEqual(88, options.for_global_scope().num)
        self.assertEqual(77, options.for_scope("compile").num)
        self.assertEqual(22, options.for_scope("compile.java").num)

        env = {"PANTS_COMPILE_NUM": "55"}
        options = self._parse(flags="compile", env=env, config=config)
        self.assertEqual(88, options.for_global_scope().num)
        self.assertEqual(55, options.for_scope("compile").num)
        self.assertEqual(55, options.for_scope("compile.java").num)

        options = self._parse(flags="compile.java -n44", env=env, config=config)
        self.assertEqual(88, options.for_global_scope().num)
        self.assertEqual(55, options.for_scope("compile").num)
        self.assertEqual(44, options.for_scope("compile.java").num)

    def test_choices(self) -> None:
        options = self._parse(flags="--str-choices=foo")
        self.assertEqual("foo", options.for_global_scope().str_choices)
        options = self._parse(config={"DEFAULT": {"str_choices": "bar"}})
        self.assertEqual("bar", options.for_global_scope().str_choices)
        with self.assertRaises(ParseError):
            options = self._parse(flags="--str-choices=baz")
            options.for_global_scope()
        with self.assertRaises(ParseError):
            options = self._parse(config={"DEFAULT": {"str_choices": "baz"}})
            options.for_global_scope()

        options = self._parse(flags="--int-choices=42 --int-choices=99")
        self.assertEqual([42, 99], options.for_global_scope().int_choices)

    def test_parse_name_and_dest(self) -> None:
        self.assertEqual(("thing", "thing"), Parser.parse_name_and_dest("--thing"))
        self.assertEqual(
            ("thing", "other_thing"), Parser.parse_name_and_dest("--thing", dest="other_thing")
        )

    def test_validation(self) -> None:
        def assertError(expected_error, *args, **kwargs):
            with self.assertRaises(expected_error):
                options = Options.create(
                    args=[],
                    env={},
                    config=self._create_config(),
                    known_scope_infos=[global_scope()],
                )
                options.register(GLOBAL_SCOPE, *args, **kwargs)
                options.for_global_scope()

        assertError(NoOptionNames)
        assertError(OptionNameDash, "badname")
        assertError(OptionNameDoubleDash, "-badname")
        assertError(InvalidKwarg, "--foo", badkwarg=42)
        assertError(ImplicitValIsNone, "--foo", implicit_value=None)
        assertError(BooleanOptionNameWithNo, "--no-foo", type=bool)
        assertError(MemberTypeNotAllowed, "--foo", member_type=int)
        assertError(MemberTypeNotAllowed, "--foo", type=dict, member_type=int)
        assertError(InvalidMemberType, "--foo", type=list, member_type=set)
        assertError(InvalidMemberType, "--foo", type=list, member_type=list)
        assertError(InvalidMemberType, "--foo", type=list, member_type=list)

    def test_implicit_value(self) -> None:
        def check(*, flag: str = "", expected: str) -> None:
            options = self._parse(flags=flag)
            assert options.for_global_scope().implicit_valuey == expected

        check(expected="default")
        check(flag="--implicit-valuey", expected="implicit")
        check(flag="--implicit-valuey=explicit", expected="explicit")

    def test_shadowing(self) -> None:
        options = Options.create(
            env={},
            config=self._create_config(),
            known_scope_infos=[global_scope(), task("bar"), intermediate("foo"), task("foo.bar")],
            args=["./pants"],
        )
        options.register("", "--opt1")
        options.register("foo", "-o", "--opt2")

        def assert_raises_shadowing(*, scope: str, args: List[str]) -> None:
            with self.assertRaises(Shadowing):
                options.register(scope, *args)

        assert_raises_shadowing(scope="", args=["--opt2"])
        assert_raises_shadowing(scope="bar", args=["--opt1"])
        assert_raises_shadowing(scope="foo.bar", args=["--opt1"])
        assert_raises_shadowing(scope="foo.bar", args=["--opt2"])
        assert_raises_shadowing(scope="foo.bar", args=["--opt1", "--opt3"])
        assert_raises_shadowing(scope="foo.bar", args=["--opt3", "--opt2"])

    def test_recursion(self) -> None:
        # Recursive option.
        options = self._parse(flags="-n=5 compile -n=6")
        self.assertEqual(5, options.for_global_scope().num)
        self.assertEqual(6, options.for_scope("compile").num)

        # Non-recursive option.
        options = self._parse(flags="--bar-baz=foo")
        self.assertEqual("foo", options.for_global_scope().bar_baz)
        options = self._parse(flags="compile --bar-baz=foo")
        with self.assertRaises(ParseError):
            options.for_scope("compile")

    def test_no_recursive_subsystem_options(self) -> None:
        options = Options.create(
            env={},
            config=self._create_config(),
            known_scope_infos=[global_scope(), subsystem("foo")],
            args=["./pants"],
        )
        # All subsystem options are implicitly recursive (a subscope of subsystem scope represents
        # a separate instance of the subsystem, so it needs all the options).
        # We disallow explicit specification of recursive (even if set to True), to avoid confusion.
        with self.assertRaises(RecursiveSubsystemOption):
            options.register("foo", "--bar", recursive=False)
            options.for_scope("foo")
        with self.assertRaises(RecursiveSubsystemOption):
            options.register("foo", "--baz", recursive=True)
            options.for_scope("foo")

    def test_is_known_scope(self) -> None:
        options = self._parse()
        for scope_info in self._known_scope_infos:
            self.assertTrue(options.is_known_scope(scope_info.scope))
        self.assertFalse(options.is_known_scope("nonexistent_scope"))

    def test_designdoc_example(self) -> None:
        # The example from the design doc.
        # Get defaults from config and environment.
        config = {
            "DEFAULT": {"b": "99"},
            "compile": {"a": "88", "c": "77"},
        }

        env = {"PANTS_COMPILE_C": "66"}

        options = self._parse(
            flags="--a=1 compile --b=2 compile.java --a=3 --c=4", env=env, config=config,
        )

        self.assertEqual(1, options.for_global_scope().a)
        self.assertEqual(99, options.for_global_scope().b)
        with self.assertRaises(AttributeError):
            options.for_global_scope().c

        self.assertEqual(1, options.for_scope("compile").a)
        self.assertEqual(2, options.for_scope("compile").b)
        self.assertEqual(66, options.for_scope("compile").c)

        self.assertEqual(3, options.for_scope("compile.java").a)
        self.assertEqual(2, options.for_scope("compile.java").b)
        self.assertEqual(4, options.for_scope("compile.java").c)

    def test_file_spec_args(self) -> None:
        with temporary_file(binary_mode=False) as tmp:
            tmp.write(
                dedent(
                    """
                    foo
                    bar
                    """
                )
            )
            tmp.flush()
            # Note that we prevent loading a real pants.toml during get_bootstrap_options().
            flags = f'--spec-file={tmp.name} --pants-config-files="[]" compile morx:tgt fleem:tgt'
            bootstrapper = OptionsBootstrapper.create(args=shlex.split(f"./pants {flags}"))
            bootstrap_options = bootstrapper.bootstrap_options.for_global_scope()
            options = self._parse(flags=flags, bootstrap_option_values=bootstrap_options)
            sorted_specs = sorted(options.specs)
            self.assertEqual(["bar", "fleem:tgt", "foo", "morx:tgt"], sorted_specs)

    def test_passthru_args_subsystems_and_goals(self):
        # Test that passthrough args are applied.
        options = self._parse(flags="")
        options = Options.create(
            env={},
            config=self._create_config(),
            known_scope_infos=[global_scope(), task("test"), subsystem("passconsumer")],
            args=["./pants", "test", "target", "--", "bar", "--baz"],
        )
        options.register(
            "passconsumer", "--passthing", passthrough=True, type=list, member_type=str
        )

        self.assertEqual(["bar", "--baz"], options.for_scope("passconsumer").passthing)

    def test_at_most_one_goal_with_passthru_args(self):
        with self.assertRaisesWithMessageContaining(
            Options.AmbiguousPassthroughError,
            """Specifying multiple goals (in this case: ['test', 'fmt']) """
            """along with passthrough args (args after `--`) is ambiguous.""",
        ):
            _ = Options.create(
                env={},
                config={},
                known_scope_infos=[global_scope(), task("test"), task("fmt")],
                args=["./pants", "test", "fmt", "target", "--", "bar", "--baz"],
            )

    def test_global_scope_env_vars(self):
        def check_pants_foo(expected_val, env):
            val = self._parse(env=env).for_global_scope().pants_foo
            self.assertEqual(expected_val, val)

        check_pants_foo(
            "AAA", {"PANTS_GLOBAL_PANTS_FOO": "AAA", "PANTS_PANTS_FOO": "BBB", "PANTS_FOO": "CCC"}
        )
        check_pants_foo("BBB", {"PANTS_PANTS_FOO": "BBB", "PANTS_FOO": "CCC"})
        check_pants_foo("CCC", {"PANTS_FOO": "CCC"})
        check_pants_foo(None, {})
        # Check that an empty string is distinct from no value being specified.
        check_pants_foo("", {"PANTS_PANTS_FOO": "", "PANTS_FOO": "CCC"})

        # A global option that doesn't begin with 'pants-': Setting BAR_BAZ should have no effect.

        def check_bar_baz(expected_val, env):
            val = self._parse(env=env).for_global_scope().bar_baz
            self.assertEqual(expected_val, val)

        check_bar_baz(
            "AAA", {"PANTS_GLOBAL_BAR_BAZ": "AAA", "PANTS_BAR_BAZ": "BBB", "BAR_BAZ": "CCC"}
        )
        check_bar_baz("BBB", {"PANTS_BAR_BAZ": "BBB", "BAR_BAZ": "CCC"})
        check_bar_baz(None, {"BAR_BAZ": "CCC"})
        check_bar_baz(None, {})

    def test_scoped_env_vars(self) -> None:
        def check_scoped_spam(scope, expected_val, env):
            val = self._parse(env=env).for_scope(scope).spam
            self.assertEqual(expected_val, val)

        check_scoped_spam("simple", "value", {"PANTS_SIMPLE_SPAM": "value"})
        check_scoped_spam("simple-dashed", "value", {"PANTS_SIMPLE_DASHED_SPAM": "value"})
        check_scoped_spam("scoped.a.bit", "value", {"PANTS_SCOPED_A_BIT_SPAM": "value"})
        check_scoped_spam("scoped.and-dashed", "value", {"PANTS_SCOPED_AND_DASHED_SPAM": "value"})

    def test_drop_flag_values(self) -> None:
        options = self._parse(
            flags="--bar-baz=fred -n33 --pants-foo=red enum-opt --some-enum=another-value simple -n1",
            env={"PANTS_FOO": "BAR"},
            config={"simple": {"num": 42}, "enum-opt": {"some-enum": "a-value"}},
        )
        defaulted_only_options = options.drop_flag_values()

        # No option value supplied in any form.
        self.assertEqual("fred", options.for_global_scope().bar_baz)
        self.assertIsNone(defaulted_only_options.for_global_scope().bar_baz)

        # A defaulted option value.
        self.assertEqual(33, options.for_global_scope().num)
        self.assertEqual(99, defaulted_only_options.for_global_scope().num)

        # A config specified option value.
        self.assertEqual(1, options.for_scope("simple").num)
        self.assertEqual(42, defaulted_only_options.for_scope("simple").num)

        # An env var specified option value.
        self.assertEqual("red", options.for_global_scope().pants_foo)
        self.assertEqual("BAR", defaulted_only_options.for_global_scope().pants_foo)

        # Overriding an enum option value.
        self.assertEqual(self.SomeEnumOption.another_value, options.for_scope("enum-opt").some_enum)

        # Getting the default value for an enum option.
        self.assertEqual(
            self.SomeEnumOption.a_value,
            defaulted_only_options.for_scope("separate-enum-opt-scope").some_enum_with_default,
        )

    def test_enum_option_type_parse_error(self) -> None:
        self.maxDiff = None
        with self.assertRaisesWithMessageContaining(
            ParseError,
            "Error applying type 'SomeEnumOption' to option value 'invalid-value', for option "
            "'--some_enum' in scope 'enum-opt'",
        ):
            options = self._parse(flags="enum-opt --some-enum=invalid-value")
            options.for_scope("enum-opt").some_enum

    def assertOptionWarning(self, w, option_string):
        single_warning = assert_single_element(w)
        self.assertEqual(single_warning.category, DeprecationWarning)
        warning_message = str(single_warning.message)
        self.assertIn("will be removed in version", warning_message)
        self.assertIn(option_string, warning_message)

    def test_deprecated_options(self) -> None:
        def assert_deprecation_triggered(
            *,
            flags: str = "",
            option: str,
            expected: Union[str, bool],
            scope: Optional[str] = None,
            env: Optional[Dict[str, str]] = None,
            config: Optional[Dict[str, Dict[str, str]]] = None,
        ) -> None:
            with self.warnings_catcher() as w:
                options = self._parse(flags=flags, env=env, config=config)
                scoped_options = (
                    options.for_global_scope() if not scope else options.for_scope(scope)
                )
            assert getattr(scoped_options, option) == expected
            self.assertOptionWarning(w, option)

        assert_deprecation_triggered(
            flags="--global-crufty=crufty1", option="global_crufty", expected="crufty1",
        )
        assert_deprecation_triggered(
            flags="--global-crufty-boolean", option="global_crufty_boolean", expected=True,
        )
        assert_deprecation_triggered(
            flags="--no-global-crufty-boolean", option="global_crufty_boolean", expected=False,
        )
        assert_deprecation_triggered(
            flags="stale --crufty=stale_and_crufty",
            scope="stale",
            option="crufty",
            expected="stale_and_crufty",
        )

        assert_scoped_boolean_deprecation = partial(
            assert_deprecation_triggered, scope="stale", option="crufty_boolean"
        )
        assert_scoped_boolean_deprecation(flags="stale --crufty-boolean", expected=True)
        assert_scoped_boolean_deprecation(flags="stale --no-crufty-boolean", expected=False)
        assert_scoped_boolean_deprecation(flags="--stale-crufty-boolean", expected=True)
        assert_scoped_boolean_deprecation(flags="--no-stale-crufty-boolean", expected=False)

        assert_deprecation_triggered(
            env={"PANTS_GLOBAL_CRUFTY": "crufty1"}, option="global_crufty", expected="crufty1",
        )
        assert_deprecation_triggered(
            env={"PANTS_STALE_CRUFTY": "stale_and_crufty"},
            scope="stale",
            option="crufty",
            expected="stale_and_crufty",
        )

        assert_deprecation_triggered(
            config={"GLOBAL": {"global_crufty": "crufty1"}},
            option="global_crufty",
            expected="crufty1",
        )
        assert_deprecation_triggered(
            config={"stale": {"crufty": "stale_and_crufty"}},
            scope="stale",
            option="crufty",
            expected="stale_and_crufty",
        )

        # Make sure the warnings don't come out for regular options.
        with self.warnings_catcher() as w:
            self._parse(flags="stale --pants-foo stale --still-good")
            self.assertEqual(0, len(w))

    @unittest.mock.patch("pants.base.deprecated.PANTS_SEMVER", Version(_FAKE_CUR_VERSION))
    def test_delayed_deprecated_option(self) -> None:
        with self.warnings_catcher() as w:
            delayed_deprecation_option_value = (
                self._parse(flags="--global-delayed-deprecated-option=xxx")
                .for_global_scope()
                .global_delayed_deprecated_option
            )
            self.assertEqual(delayed_deprecation_option_value, "xxx")
            self.assertEqual(0, len(w))

        with self.warnings_catcher() as w:
            delayed_passed_option_value = (
                self._parse(flags="--global-delayed-but-already-passed-deprecated-option=xxx")
                .for_global_scope()
                .global_delayed_but_already_passed_deprecated_option
            )
            self.assertEqual(delayed_passed_option_value, "xxx")
            self.assertOptionWarning(w, "global_delayed_but_already_passed_deprecated_option")

    def test_mutually_exclusive_options(self) -> None:
        """Ensure error is raised when mutual exclusive options are given together."""

        def assert_mutually_exclusive_raised(
            *,
            flags: str,
            scope: Optional[str] = None,
            env: Optional[Dict[str, str]] = None,
            config: Optional[Dict[str, Dict[str, str]]] = None,
        ) -> None:
            with self.assertRaises(MutuallyExclusiveOptionError):
                options = self._parse(flags=flags, env=env, config=config)
                if scope:
                    options.for_scope(scope)
                else:
                    options.for_global_scope()

        assert_mutually_exclusive_raised(flags="--mutex-foo=foo --mutex-bar=bar")
        assert_mutually_exclusive_raised(flags="--mutex-foo=foo --mutex-baz=baz")
        assert_mutually_exclusive_raised(flags="--mutex-bar=bar --mutex-baz=baz")
        assert_mutually_exclusive_raised(flags="--mutex-foo=foo --mutex-bar=bar --mutex-baz=baz")
        assert_mutually_exclusive_raised(flags="--new-name=foo --old-name=bar")
        assert_mutually_exclusive_raised(flags="--new-name=foo --old-name=bar")
        assert_mutually_exclusive_raised(flags="stale --mutex-a=foo --mutex-b=bar", scope="stale")
        assert_mutually_exclusive_raised(
            flags="stale --crufty-new=foo --crufty-old=bar", scope="stale"
        )

        assert_mutually_exclusive_raised(flags="--mutex-foo=foo", env={"PANTS_MUTEX_BAR": "bar"})
        assert_mutually_exclusive_raised(flags="--new-name=foo", env={"PANTS_OLD_NAME": "bar"})
        assert_mutually_exclusive_raised(
            flags="stale --mutex-a=foo", env={"PANTS_STALE_MUTEX_B": "bar"}, scope="stale",
        )
        assert_mutually_exclusive_raised(
            flags="stale --crufty-new=foo", env={"PANTS_STALE_CRUFTY_OLD": "bar"}, scope="stale",
        )

        assert_mutually_exclusive_raised(
            flags="--mutex-foo=foo", config={"GLOBAL": {"mutex_bar": "bar"}},
        )
        assert_mutually_exclusive_raised(
            flags="--new-name=foo", config={"GLOBAL": {"old_name": "bar"}},
        )
        assert_mutually_exclusive_raised(
            flags="stale --mutex-a=foo", config={"stale": {"mutex_b": "bar"}}, scope="stale",
        )
        assert_mutually_exclusive_raised(
            flags="stale --crufty-old=foo", config={"stale": {"crufty_new": "bar"}}, scope="stale",
        )

        def assert_other_option_also_set(
            *,
            flags: str = "",
            other_option: str,
            scope: Optional[str] = None,
            env: Optional[Dict[str, str]] = None,
            config: Optional[Dict[str, Dict[str, str]]] = None,
        ) -> None:
            options = self._parse(flags=flags, env=env, config=config)
            scoped_options = options.for_global_scope() if not scope else options.for_scope(scope)
            assert getattr(scoped_options, other_option) == "orz"

        assert_other_option_also_set(flags="--mutex-foo=orz", other_option="mutex")
        assert_other_option_also_set(flags="--old-name=orz", other_option="new_name")
        assert_other_option_also_set(
            flags="stale --mutex-a=orz", other_option="crufty_mutex", scope="stale",
        )
        assert_other_option_also_set(
            flags="stale --crufty-old=orz", other_option="crufty_new", scope="stale",
        )
        assert_other_option_also_set(env={"PANTS_GLOBAL_MUTEX_BAZ": "orz"}, other_option="mutex")
        assert_other_option_also_set(env={"PANTS_OLD_NAME": "orz"}, other_option="new_name")
        assert_other_option_also_set(
            env={"PANTS_STALE_MUTEX_B": "orz"}, other_option="crufty_mutex", scope="stale",
        )
        assert_other_option_also_set(
            config={"stale": {"crufty_old": "orz"}}, other_option="crufty_new", scope="stale",
        )

    def test_middle_scoped_options(self) -> None:
        """Make sure the rules for inheriting from a hierarchy of scopes.

        Values should follow
         1. A short circuit scan for a value from the following sources in-order:
            flags, env, config, hardcoded defaults
         2. Values for each source follow the . hierarchy scoping rule
            within that source.
        """

        # Short circuit using command line.
        options = self._parse(flags="--a=100 compile --a=99")
        self.assertEqual(100, options.for_global_scope().a)
        self.assertEqual(99, options.for_scope("compile").a)
        self.assertEqual(99, options.for_scope("compile.java").a)

        options = self._parse(config={"DEFAULT": {"a": 100}, "compile": {"a": 99}})
        self.assertEqual(100, options.for_global_scope().a)
        self.assertEqual(99, options.for_scope("compile").a)
        self.assertEqual(99, options.for_scope("compile.java").a)

        options = self._parse(env={"PANTS_A": "100", "PANTS_COMPILE_A": "99"})
        self.assertEqual(100, options.for_global_scope().a)
        self.assertEqual(99, options.for_scope("compile").a)
        self.assertEqual(99, options.for_scope("compile.java").a)

        # Command line has precedence over config.
        options = self._parse(flags="compile --a=99", config={"DEFAULT": {"a": 100}})
        self.assertEqual(100, options.for_global_scope().a)
        self.assertEqual(99, options.for_scope("compile").a)
        self.assertEqual(99, options.for_scope("compile.java").a)

        # Command line has precedence over environment.
        options = self._parse(flags="compile --a=99", env={"PANTS_A": "100"})
        self.assertEqual(100, options.for_global_scope().a)
        self.assertEqual(99, options.for_scope("compile").a)
        self.assertEqual(99, options.for_scope("compile.java").a)

        # Env has precedence over config.
        options = self._parse(config={"DEFAULT": {"a": 100}}, env={"PANTS_COMPILE_A": "99"})
        self.assertEqual(100, options.for_global_scope().a)
        self.assertEqual(99, options.for_scope("compile").a)
        self.assertEqual(99, options.for_scope("compile.java").a)

        # Command line global overrides the middle scope setting in then env.
        options = self._parse(flags="--a=100", env={"PANTS_COMPILE_A": "99"})
        self.assertEqual(100, options.for_global_scope().a)
        self.assertEqual(100, options.for_scope("compile").a)
        self.assertEqual(100, options.for_scope("compile.java").a)

        # Command line global overrides the middle scope in config.
        options = self._parse(flags="--a=100 ", config={"compile": {"a": 99}})
        self.assertEqual(100, options.for_global_scope().a)
        self.assertEqual(100, options.for_scope("compile").a)
        self.assertEqual(100, options.for_scope("compile.java").a)

        # Env global overrides the middle scope in config.
        options = self._parse(
            flags="--a=100 ", config={"compile": {"a": 99}}, env={"PANTS_A": "100"}
        )
        self.assertEqual(100, options.for_global_scope().a)
        self.assertEqual(100, options.for_scope("compile").a)
        self.assertEqual(100, options.for_scope("compile.java").a)

    def test_complete_scopes(self) -> None:
        self.assertEqual(
            {intermediate("foo"), intermediate("foo.bar"), task("foo.bar.baz")},
            set(Options.complete_scopes({task("foo.bar.baz")})),
        )
        self.assertEqual(
            {global_scope(), intermediate("foo"), intermediate("foo.bar"), task("foo.bar.baz")},
            set(Options.complete_scopes({GlobalOptions.get_scope_info(), task("foo.bar.baz")})),
        )
        self.assertEqual(
            {intermediate("foo"), intermediate("foo.bar"), task("foo.bar.baz")},
            set(Options.complete_scopes({intermediate("foo"), task("foo.bar.baz")})),
        )
        self.assertEqual(
            {
                intermediate("foo"),
                intermediate("foo.bar"),
                task("foo.bar.baz"),
                intermediate("qux"),
                task("qux.quux"),
            },
            set(Options.complete_scopes({task("foo.bar.baz"), task("qux.quux")})),
        )

    def test_get_fingerprintable_for_scope(self) -> None:
        # Note: tests handling recursive and non-recursive options from enclosing scopes correctly.
        options = self._parse(
            flags='--store-true-flag --num=88 compile.scala --num=77 --modifycompile="blah blah blah" '
            '--modifylogs="durrrr" -- -d -v'
        )

        # NB: Passthrough args end up on our `--modifypassthrough` arg.
        pairs = options.get_fingerprintable_for_scope("compile.scala")
        self.assertEqual(
            [(str, "blah blah blah"), (str, ["-d", "-v"]), (bool, True), (int, 77)], pairs
        )

    def test_fingerprintable(self) -> None:
        options = self._parse(
            flags="fingerprinting --fingerprinted=shall_be_fingerprinted "
            "--definitely-not-fingerprinted=shant_be_fingerprinted"
        )
        pairs = options.get_fingerprintable_for_scope("fingerprinting")
        self.assertIn((str, "shall_be_fingerprinted"), pairs)
        self.assertNotIn((str, "shant_be_fingerprinted"), pairs)

    def test_fingerprintable_inverted(self) -> None:
        options = self._parse(
            flags="fingerprinting --inverted=shall_be_fingerprinted "
            "--definitely-not-inverted=shant_be_fingerprinted"
        )
        pairs = options.get_fingerprintable_for_scope(
            "fingerprinting", fingerprint_key="daemon", invert=True
        )
        self.assertIn((str, "shall_be_fingerprinted"), pairs)
        self.assertNotIn((str, "shant_be_fingerprinted"), pairs)

    def assert_fromfile(self, parse_func, expected_append=None, append_contents=None):
        def _do_assert_fromfile(dest, expected, contents):
            with temporary_file(binary_mode=False) as fp:
                fp.write(contents)
                fp.close()
                options = parse_func(dest, fp.name)
                self.assertEqual(expected, options.for_scope("fromfile")[dest])

        _do_assert_fromfile(dest="string", expected="jake", contents="jake")
        _do_assert_fromfile(dest="intvalue", expected=42, contents="42")
        _do_assert_fromfile(
            dest="dictvalue",
            expected={"a": 42, "b": (1, 2)},
            contents=dedent(
                """
                {
                  'a': 42,
                  'b': (
                    1,
                    2
                  )
                }
                """
            ),
        )
        _do_assert_fromfile(
            dest="listvalue",
            expected=["a", "1", "2"],
            contents=dedent(
                """
                ['a',
                 1,
                 2]
                """
            ),
        )

        expected_append = expected_append or [1, 2, 42]
        append_contents = append_contents or dedent(
            """
            [
             1,
             2,
             42
            ]
            """
        )
        _do_assert_fromfile(dest="appendvalue", expected=expected_append, contents=append_contents)

    def test_fromfile_flags(self) -> None:
        def parse_func(dest, fromfile):
            return self._parse(flags=f"fromfile --{dest.replace('_', '-')}=@{fromfile}")

        # You can only append a single item at a time with append flags, ie: we don't override the
        # default list like we do with env of config.  As such, send in a single append value here
        # instead of a whole default list as in `test_fromfile_config` and `test_fromfile_env`.
        self.assert_fromfile(parse_func, expected_append=[42], append_contents="42")

    def test_fromfile_config(self) -> None:
        def parse_func(dest, fromfile):
            return self._parse(flags="fromfile", config={"fromfile": {dest: f"@{fromfile}"}})

        self.assert_fromfile(parse_func)

    def test_fromfile_env(self) -> None:
        def parse_func(dest, fromfile):
            return self._parse(
                flags="fromfile", env={f"PANTS_FROMFILE_{dest.upper()}": f"@{fromfile}"}
            )

        self.assert_fromfile(parse_func)

    def test_fromfile_json(self) -> None:
        val = {"a": {"b": 1}, "c": [2, 3]}
        with temporary_file(suffix=".json", binary_mode=False) as fp:
            json.dump(val, fp)
            fp.close()
            options = self._parse(flags=f"fromfile --{'dictvalue'}=@{fp.name}")
            self.assertEqual(val, options.for_scope("fromfile")["dictvalue"])

    def test_fromfile_yaml(self) -> None:
        val = {"a": {"b": 1}, "c": [2, 3]}
        with temporary_file(suffix=".yaml", binary_mode=False) as fp:
            yaml.safe_dump(val, fp)
            fp.close()
            options = self._parse(flags=f"fromfile --{'dictvalue'}=@{fp.name}")
            self.assertEqual(val, options.for_scope("fromfile")["dictvalue"])

    def test_fromfile_error(self) -> None:
        options = self._parse(flags="fromfile --string=@/does/not/exist")
        with self.assertRaises(FromfileError):
            options.for_scope("fromfile")

    def test_fromfile_escape(self) -> None:
        options = self._parse(flags=r"fromfile --string=@@/does/not/exist")
        self.assertEqual("@/does/not/exist", options.for_scope("fromfile").string)

    def test_ranked_value_equality(self) -> None:
        none = RankedValue(Rank.NONE, None)
        some = RankedValue(Rank.HARDCODED, "some")
        self.assertEqual(RankedValue(Rank.NONE, None), none)
        self.assertEqual(RankedValue(Rank.HARDCODED, "some"), some)
        self.assertNotEqual(some, none)
        self.assertEqual(some, RankedValue(Rank.HARDCODED, "some"))
        self.assertNotEqual(some, RankedValue(Rank.HARDCODED, "few"))
        self.assertNotEqual(some, RankedValue(Rank.CONFIG, "some"))

    def test_pants_global_designdoc_example(self) -> None:
        # The example from the design doc.
        # Get defaults from config and environment.
        config = {
            "GLOBAL": {"b": "99"},
            "compile": {"a": "88", "c": "77"},
        }

        env = {"PANTS_COMPILE_C": "66"}

        options = self._parse(
            flags="--a=1 compile --b=2 compile.java --a=3 --c=4", env=env, config=config,
        )

        self.assertEqual(1, options.for_global_scope().a)
        self.assertEqual(99, options.for_global_scope().b)
        with self.assertRaises(AttributeError):
            options.for_global_scope().c

        self.assertEqual(1, options.for_scope("compile").a)
        self.assertEqual(2, options.for_scope("compile").b)
        self.assertEqual(66, options.for_scope("compile").c)

        self.assertEqual(3, options.for_scope("compile.java").a)
        self.assertEqual(2, options.for_scope("compile.java").b)
        self.assertEqual(4, options.for_scope("compile.java").c)

    def test_invalid_option_errors(self) -> None:
        self.maxDiff = None

        def parse_joined_command_line(*args):
            bootstrap_options = create_options(
                {
                    GLOBAL_SCOPE: {
                        # Set the Levenshtein edit distance to search for misspelled options.
                        "option_name_check_distance": 2,
                        # If bootstrap option values are provided, this option is accessed and must be provided.
                        "spec_files": [],
                    },
                }
            )
            return self._parse(
                flags=safe_shlex_join(list(args)),
                bootstrap_option_values=bootstrap_options.for_global_scope(),
            )

        with self.assertRaisesWithMessage(
            ParseError,
            (
                "Unrecognized command line flag '--aasdf' on global scope.\n\n(Run `./pants "
                "help-advanced` for all available options.)"
            ),
        ):
            parse_joined_command_line("--aasdf").for_global_scope()

        with self.assertRaisesWithMessage(
            ParseError,
            (
                "Unrecognized command line flags on global scope: --aasdf, --aasdy.\n\n(Run "
                "`./pants help-advanced` for all available options.)"
            ),
        ):
            parse_joined_command_line("--aasdf", "--aasdy").for_global_scope()

        with self.assertRaisesWithMessage(
            ParseError,
            dedent(
                """\
                Unrecognized command line flags on global scope: -v, --config-overridden, --c.
                Suggestions:
                -v: [--v2, --verbose, --a, --b, --y, -n, -z, --compile-c]
                --config-overridden: [--config-override]
                --c: [--compile-c, --compile-scala-modifycompile, --compile-scala-modifylogs, --compile-scala-modifypassthrough, --config-override, --a, --b, --y, -n, -z, --v2]

                (Run `./pants help-advanced` for all available options.)"""
            ),
        ):
            parse_joined_command_line(
                # A nonexistent short-form option -- other short-form options should be displayed.
                "-vd",
                # An incorrect form of `--config-override=val` (`ridden` instead of `ride`) should
                # show the correct option name.
                "--config-overridden=val",
                # An option name without the correct prefix scope should match all flags with the
                # same or similar unscoped option names.
                "--c=[]",
            ).for_global_scope()

        # Test when only some flags have suggestsions.
        with self.assertRaisesWithMessage(
            ParseError,
            (
                "Unrecognized command line flags on global scope: --aasdf, --config-overridden.\n"
                "Suggestions:\n"
                "--config-overridden: [--config-override]\n\n"
                "(Run `./pants help-advanced` for all available options.)"
            ),
        ):
            parse_joined_command_line("--aasdf", "--config-overridden").for_global_scope()

        with self.assertRaisesWithMessage(
            ParseError,
            dedent(
                """\
                Unrecognized command line flag '--sam' on scope 'simple'. Suggestions:
                --simple-spam, --simple-dashed-spam, --a, --num, --scoped-a-bit-spam, --scoped-and-dashed-spam

                (Run `./pants help-advanced simple` for all available options.)"""
            ),
        ):
            parse_joined_command_line(
                # Verify that misspelling searches work for options in non-global scopes.
                "--simple-sam=val",
            ).for_scope("simple")

        with self.assertRaisesWithMessage(
            ParseError,
            dedent(
                """\
                Unrecognized command line flag '--modifylogs' on scope 'compile'. Suggestions:
                --compile-scala-modifylogs

                (Run `./pants help-advanced compile` for all available options.)"""
            ),
        ):
            parse_joined_command_line(
                # Verify that options with too shallow scoping match the correct option.
                "--compile-modifylogs=val",
            ).for_scope("compile")

        with self.assertRaisesWithMessage(
            ParseError,
            dedent(
                """\
                Unrecognized command line flag '--modifylogs' on scope 'cache.compile.scala'.
                Suggestions:
                --compile-scala-modifylogs

                (Run `./pants help-advanced cache.compile.scala` for all available options.)"""
            ),
        ):
            parse_joined_command_line(
                # Verify that options with too deep scoping match the correct option.
                "--cache-compile-scala-modifylogs=val",
            ).for_scope("cache.compile.scala")

    def test_pants_global_with_default(self) -> None:
        """This test makes sure values under [DEFAULT] still gets read."""
        # This cast shouldn't be necessary - likely a bug in MyPy. Once this gets fixed, MyPy will
        # tell us that we can remove the cast.
        config = cast(
            Dict[str, Dict[str, Any]], {"DEFAULT": {"b": "99"}, "GLOBAL": {"store_true_flag": True}}
        )
        global_options = self._parse(config=config).for_global_scope()
        self.assertEqual(99, global_options.b)
        self.assertTrue(global_options.store_true_flag)

    def test_double_registration(self) -> None:
        options = Options.create(
            env={},
            config=self._create_config(),
            known_scope_infos=OptionsTest._known_scope_infos,
            args=shlex.split("./pants"),
        )
        options.register(GLOBAL_SCOPE, "--foo-bar")
        with self.assertRaises(OptionAlreadyRegistered):
            options.register(GLOBAL_SCOPE, "--foo-bar")

    def test_enum_serializability(self) -> None:
        # We serialize options to JSON e.g., when uploading stats.
        # This test spot-checks that enum types can be serialized.
        options = self._parse(flags="enum-opt --some-enum=another-value")
        json.dumps({"foo": [options.for_scope("enum-opt").as_dict()]}, cls=CoercingEncoder)

    def test_scope_deprecation(self) -> None:
        # Note: This test demonstrates that two different new scopes can deprecate the same
        # old scope. I.e., it's possible to split an old scope's options among multiple new scopes.
        class DummyOptionable1(Optionable):
            options_scope = "new-scope1"
            options_scope_category = ScopeInfo.SUBSYSTEM
            deprecated_options_scope = "deprecated-scope"
            deprecated_options_scope_removal_version = "9999.9.9.dev0"

        class DummyOptionable2(Optionable):
            options_scope = "new-scope2"
            options_scope_category = ScopeInfo.SUBSYSTEM
            deprecated_options_scope = "deprecated-scope"
            deprecated_options_scope_removal_version = "9999.9.9.dev0"

        options = Options.create(
            env={},
            config=self._create_config(
                {
                    "GLOBAL": {"inherited": "aa"},
                    DummyOptionable1.options_scope: {"foo": "xx"},
                    DummyOptionable1.deprecated_options_scope: {
                        "foo": "yy",
                        "bar": "zz",
                        "baz": "ww",
                        "qux": "uu",
                    },
                }
            ),
            known_scope_infos=[
                global_scope(),
                DummyOptionable1.get_scope_info(),
                DummyOptionable2.get_scope_info(),
            ],
            args=shlex.split("./pants --new-scope1-baz=vv"),
        )

        options.register(GLOBAL_SCOPE, "--inherited")
        options.register(DummyOptionable1.options_scope, "--foo")
        options.register(DummyOptionable1.options_scope, "--bar")
        options.register(DummyOptionable1.options_scope, "--baz")
        options.register(DummyOptionable2.options_scope, "--qux")

        with self.warnings_catcher() as w:
            vals1 = options.for_scope(DummyOptionable1.options_scope)

        # Check that we got a warning, but not for the inherited option.
        single_warning_dummy1 = assert_single_element(w)
        self.assertEqual(single_warning_dummy1.category, DeprecationWarning)
        self.assertNotIn("inherited", str(single_warning_dummy1.message))

        # Check values.
        # Deprecated scope takes precedence at equal rank.
        self.assertEqual("yy", vals1.foo)
        self.assertEqual("zz", vals1.bar)
        # New scope takes precedence at higher rank.
        self.assertEqual("vv", vals1.baz)

        with self.warnings_catcher() as w:
            vals2 = options.for_scope(DummyOptionable2.options_scope)

        # Check that we got a warning.
        single_warning_dummy2 = assert_single_element(w)
        self.assertEqual(single_warning_dummy2.category, DeprecationWarning)
        self.assertNotIn("inherited", str(single_warning_dummy2.message))

        # Check values.
        self.assertEqual("uu", vals2.qux)

    def test_scope_deprecation_parent(self) -> None:
        # Note: This test demonstrates that a scope can mark itself as deprecating a subscope of
        # another scope.
        class DummyOptionable1(Optionable):
            options_scope = "test"
            options_scope_category = ScopeInfo.SUBSYSTEM

            @classmethod
            def register_options(cls, register):
                super().register_options(register)
                register("--bar")

        class DummyOptionable2(Optionable):
            options_scope = "lint"
            options_scope_category = ScopeInfo.SUBSYSTEM
            deprecated_options_scope = "test.a-bit-linty"
            deprecated_options_scope_removal_version = "9999.9.9.dev0"

            @classmethod
            def register_options(cls, register):
                super().register_options(register)
                register("--foo")

        known_scope_infos = (
            [global_scope()]
            + list(DummyOptionable1.known_scope_infos())
            + list(DummyOptionable2.known_scope_infos())
        )

        options = Options.create(
            env={},
            config=self._create_config(),
            known_scope_infos=known_scope_infos,
            args=shlex.split("./pants --test-a-bit-linty-foo=vv"),
        )

        # NB: Order matters here, because Optionables are typically registered in sorted order.
        DummyOptionable2.register_options_on_scope(options)
        DummyOptionable1.register_options_on_scope(options)

        with self.warnings_catcher() as w:
            vals = options.for_scope(DummyOptionable2.options_scope)

        # Check that we got a warning, but also the correct value.
        single_warning_dummy1 = assert_single_element(w)
        self.assertEqual(single_warning_dummy1.category, DeprecationWarning)
        self.assertEqual("vv", vals.foo)

    def test_scope_deprecation_defaults(self) -> None:
        # Confirms that a DEFAULT option does not trigger deprecation warnings for a deprecated scope.
        class DummyOptionable1(Optionable):
            options_scope = "new-scope1"
            options_scope_category = ScopeInfo.SUBSYSTEM
            deprecated_options_scope = "deprecated-scope"
            deprecated_options_scope_removal_version = "9999.9.9.dev0"

        options = Options.create(
            env={},
            config=self._create_config(
                {"DEFAULT": {"foo": "aa"}, DummyOptionable1.options_scope: {"foo": "xx"}}
            ),
            known_scope_infos=[global_scope(), DummyOptionable1.get_scope_info()],
            args=shlex.split("./pants"),
        )

        options.register(DummyOptionable1.options_scope, "--foo")

        with self.warnings_catcher() as w:
            vals1 = options.for_scope(DummyOptionable1.options_scope)

        # Check that we got no warnings and that the actual scope took precedence.
        self.assertEqual(0, len(w))
        self.assertEqual("xx", vals1.foo)

    def test_scope_dependency_deprecation(self) -> None:
        # Test that a dependency scope can be deprecated.
        class DummyOptionable1(Optionable):
            options_scope = "scope"
            options_scope_category = ScopeInfo.SUBSYSTEM

        options = Options.create(
            env={},
            config=self._create_config(),
            known_scope_infos=[
                global_scope(),
                DummyOptionable1.get_scope_info(),
                # A deprecated, scoped dependency on `DummyOptionable1`. This
                # imitates the construction of SubsystemClientMixin.known_scope_infos.
                ScopeInfo(
                    DummyOptionable1.subscope("sub"),
                    ScopeInfo.SUBSYSTEM,
                    DummyOptionable1,
                    removal_version="9999.9.9.dev0",
                    removal_hint="Sayonara!",
                ),
            ],
            args=shlex.split("./pants --scope-sub-foo=vv"),
        )

        options.register(DummyOptionable1.options_scope, "--foo")

        with self.warnings_catcher() as w:
            vals1 = options.for_scope(DummyOptionable1.subscope("sub"))

        # Check that we got a warning, but also the correct value.
        single_warning_dummy1 = assert_single_element(w)
        self.assertEqual(single_warning_dummy1.category, DeprecationWarning)
        self.assertEqual("vv", vals1.foo)
