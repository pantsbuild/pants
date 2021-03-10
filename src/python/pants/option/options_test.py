# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
import os
import shlex
import unittest.mock
import warnings
from collections import defaultdict
from enum import Enum
from functools import partial
from textwrap import dedent
from typing import Any, Dict, List, cast

import pytest
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
from pants.option.parser_hierarchy import enclosing_scope
from pants.option.ranked_value import Rank, RankedValue
from pants.option.scope import GLOBAL_SCOPE, ScopeInfo
from pants.util.contextutil import temporary_file, temporary_file_path
from pants.util.dirutil import safe_mkdtemp

_FAKE_CUR_VERSION = "1.0.0.dev0"


def global_scope() -> ScopeInfo:
    return ScopeInfo(GLOBAL_SCOPE, GlobalOptions)


def task(scope: str) -> ScopeInfo:
    return ScopeInfo(scope)


def intermediate(scope: str) -> ScopeInfo:
    return ScopeInfo(scope)


def subsystem(scope: str) -> ScopeInfo:
    return ScopeInfo(scope)


class _FakeOptionValues:
    def __init__(self, option_values):
        self._option_values = option_values

    def __iter__(self):
        return iter(self._option_values.keys())

    def __getitem__(self, key):
        return getattr(self, key)

    def get(self, key, default=None):
        if hasattr(self, key):
            return getattr(self, key, default)
        return default

    def __getattr__(self, key):
        try:
            value = self._option_values[key]
        except KeyError:
            # Instead of letting KeyError raise here, re-raise an AttributeError to not break getattr().
            raise AttributeError(key)
        return value.value if isinstance(value, RankedValue) else value

    def get_rank(self, key):
        value = self._option_values[key]
        return value.rank if isinstance(value, RankedValue) else Rank.FLAG

    def is_flagged(self, key):
        return self.get_rank(key) == Rank.FLAG

    def is_default(self, key):
        return self.get_rank(key) in (Rank.NONE, Rank.HARDCODED)

    @property
    def option_values(self):
        return self._option_values


def create_options(options, passthru_args=None, fingerprintable_options=None):
    """Create a fake Options object for testing.

    Note that the returned object only provides access to the provided options values. There is
    no registration mechanism on this object. Code under test shouldn't care about resolving
    cmd-line flags vs. config vs. env vars etc. etc.

    :param dict options: A dict of scope -> (dict of option name -> value).
    :param list passthru_args: A list of passthrough command line argument values.
    :param dict fingerprintable_options: A dict of scope -> (dict of option name -> option type).
                                         This registry should contain entries for any of the
                                         `options` that are expected to contribute to fingerprinting.
    :returns: An fake `Options` object encapsulating the given scoped options.
    """
    fingerprintable = fingerprintable_options or defaultdict(dict)

    class FakeOptions:
        def for_scope(self, scope):
            # TODO(John Sirois): Some users pass in A dict of scope -> _FakeOptionValues instead of a
            # dict of scope -> (dict of option name -> value).  Clean up these usages and kill this
            # accommodation.
            options_for_this_scope = options.get(scope) or {}
            if isinstance(options_for_this_scope, _FakeOptionValues):
                options_for_this_scope = options_for_this_scope.option_values

            if passthru_args:
                # TODO: This is _very_ partial support for passthrough args: this should be
                # inspecting the kwargs of option registrations to decide which arguments to
                # extend: this explicit `passthrough_args` argument is only passthrough because
                # it is marked as such.
                pa = options_for_this_scope.get("passthrough_args", [])
                if isinstance(pa, RankedValue):
                    pa = pa.value
                options_for_this_scope["passthrough_args"] = [*pa, *passthru_args]

            scoped_options = {}
            if scope:
                scoped_options.update(self.for_scope(enclosing_scope(scope)).option_values)
            scoped_options.update(options_for_this_scope)
            return _FakeOptionValues(scoped_options)

        def for_global_scope(self):
            return self.for_scope(GLOBAL_SCOPE)

        def items(self):
            return list(options.items())

        @property
        def scope_to_flags(self):
            return {}

        def get_fingerprintable_for_scope(self, bottom_scope):
            """Returns a list of fingerprintable (option type, option value) pairs for the given
            scope.

            Note that this method only collects values for a single scope, NOT from
            all enclosing scopes as in the Options class!

            :param str bottom_scope: The scope to gather fingerprintable options for.
            """
            pairs = []
            option_values = self.for_scope(bottom_scope)
            for option_name, option_type in fingerprintable[bottom_scope].items():
                pairs.append((option_type, option_values[option_name]))
            return pairs

        def __getitem__(self, scope):
            return self.for_scope(scope)

    return FakeOptions()


class OptionsTest(unittest.TestCase):
    @staticmethod
    def _create_config(config: dict[str, dict[str, str]] | None = None) -> Config:
        with open(os.path.join(safe_mkdtemp(), "test_config.toml"), "w") as fp:
            toml.dump(config or {}, fp)
        return Config.load(config_paths=[fp.name])

    def _parse(
        self,
        *,
        flags: str = "",
        env: dict[str, str] | None = None,
        config: dict[str, dict[str, Any]] | None = None,
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
        task("other-enum-scope"),
    ]

    class SomeEnumOption(Enum):
        a_value = "a-value"
        another_value = "another-value"
        yet_another = "yet-another"
        one_more = "one-more"

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
        options.register("compile", "--c", type=int)

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
        options.register("fromfile", "--passthru-listvalue", type=list, passthrough=True)
        options.register("fromfile", "--appendvalue", type=list, member_type=int)

        # For fingerprint tests
        options.register("fingerprinting", "--inverted")  # Implicitly: daemon=True
        options.register("fingerprinting", "--definitely-not-inverted", daemon=False)
        options.register("fingerprinting", "--fingerprinted", fingerprint=True)
        options.register("fingerprinting", "--definitely-not-fingerprinted", fingerprint=False)

        # For enum tests
        options.register("enum-opt", "--some-enum", type=self.SomeEnumOption)
        options.register(
            "other-enum-scope", "--some-list-enum", type=list, member_type=self.SomeEnumOption
        )
        options.register(
            "other-enum-scope",
            "--some-list-enum-with-default",
            type=list,
            member_type=self.SomeEnumOption,
            default=[self.SomeEnumOption.yet_another],
        )

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
            env_val: str | None = None,
            config_val: str | None = None,
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
            flags="--listy=-[1,5,6]",
            env_val="+[6,7]",
            config_val="+[4,5]",
            expected=[2, 3, 4, 7],
        )
        check(
            flags="--listy=+[8,9]",
            env_val="-[4,5]",
            config_val="+[4,5],-[3]",
            expected=[1, 2, 8, 9],
        )

        # Overwriting from env, then appending and filtering.
        check(
            flags="--listy=+[8,9],-[6]",
            env_val="[6,7]",
            config_val="+[4,5]",
            expected=[7, 8, 9],
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
            flags="--listy=[8,9]",
            env_val="+[6,7]",
            config_val="+[4,5],-[8]",
            expected=[8, 9],
        )

        # Filtering all instances of repeated values.
        check(
            flags="--listy=-[5]",
            config_val="[1, 2, 5, 3, 4, 5, 6, 5, 5]",
            expected=[1, 2, 3, 4, 6],
        )

        # Filtering a value even though it was appended again at a higher rank.
        check(
            flags="--listy=+[4]",
            env_val="-[4]",
            config_val="+[4,5]",
            expected=[*default, 5],
        )

        # Filtering a value even though it was appended again at the same rank.
        check(
            env_val="-[4],+[4]",
            config_val="+[4,5]",
            expected=[*default, 5],
        )

        # Overwriting cancels filters.
        check(env_val="[4]", config_val="-[4]", expected=[4])

    def test_dict_list_option(self) -> None:
        def check(
            *,
            expected: List[Dict[str, int]],
            flags: str = "",
            env_val: str | None = None,
            config_val: str | None = None,
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
            flags='--dict-listy=\'+[{"d": 4, "e": 5}, {"f": 6}]\'',
            expected=two_elements_appended,
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
            env_val: str | None = None,
            config_val: str | None = None,
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
            env_val: str | None = None,
            config_val: str | None = None,
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
            *,
            expected: Dict[str, str],
            flags: str = "",
            config_val: str | None = None,
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

    def test_parse_dest(self) -> None:
        self.assertEqual("thing", Parser.parse_dest("--thing"))
        self.assertEqual("other_thing", Parser.parse_dest("--thing", dest="other_thing"))

    def test_validation(self) -> None:
        def assertError(expected_error, *args, **kwargs):
            with self.assertRaises(expected_error):
                options = Options.create(
                    args=["./pants"],
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
            flags="--a=1 compile --b=2 compile.java --a=3 --c=4",
            env=env,
            config=config,
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
            flags = f'--spec-files={tmp.name} --pants-config-files="[]" compile morx:tgt fleem:tgt'
            bootstrapper = OptionsBootstrapper.create(
                env={}, args=shlex.split(f"./pants {flags}"), allow_pantsrc=False
            )
            bootstrap_options = bootstrapper.bootstrap_options.for_global_scope()
            options = self._parse(flags=flags, bootstrap_option_values=bootstrap_options)
            sorted_specs = sorted(options.specs)
            self.assertEqual(["bar", "fleem:tgt", "foo", "morx:tgt"], sorted_specs)

    def test_passthru_args_subsystems_and_goals(self):
        # Test that passthrough args are applied.
        options = Options.create(
            env={},
            config=self._create_config(),
            known_scope_infos=[global_scope(), task("test"), subsystem("passconsumer")],
            args=["./pants", "test", "target", "--", "bar", "--baz", "@dont_fromfile_expand_me"],
        )
        options.register(
            "passconsumer", "--passthing", passthrough=True, type=list, member_type=str
        )

        self.assertEqual(
            ["bar", "--baz", "@dont_fromfile_expand_me"],
            options.for_scope("passconsumer").passthing,
        )

    def test_at_most_one_goal_with_passthru_args(self):
        with pytest.raises(Options.AmbiguousPassthroughError) as exc:
            Options.create(
                env={},
                config={},
                known_scope_infos=[global_scope(), task("test"), task("fmt")],
                args=["./pants", "test", "fmt", "target", "--", "bar", "--baz"],
            )
        assert (
            "Specifying multiple goals (in this case: ['test', 'fmt']) along with passthrough args "
            "(args after `--`) is ambiguous."
        ) in str(exc.value)

    def test_passthru_args_not_interpreted(self):
        # Test that passthrough args are not interpreted.
        options = Options.create(
            env={},
            config=self._create_config(),
            known_scope_infos=[global_scope(), task("test"), subsystem("consumer")],
            args=["./pants", "--consumer-shlexed=a", "--consumer-string=b", "test", "--", "[bar]"],
        )
        options.register(
            "consumer", "--shlexed", passthrough=True, type=list, member_type=shell_str
        )
        options.register("consumer", "--string", passthrough=True, type=list, member_type=str)
        self.assertEqual(
            ["a", "[bar]"],
            options.for_scope("consumer").shlexed,
        )
        self.assertEqual(
            ["b", "[bar]"],
            options.for_scope("consumer").string,
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
        with pytest.raises(ParseError) as exc:
            options = self._parse(flags="enum-opt --some-enum=invalid-value")
            options.for_scope("enum-opt").some_enum
        assert (
            "Error applying type 'SomeEnumOption' to option value 'invalid-value', for option "
            "'--some_enum' in scope 'enum-opt'"
        ) in str(exc.value)

    def test_deprecated_options(self) -> None:
        def assert_deprecation_triggered(
            *,
            flags: str = "",
            option: str,
            expected: str | bool,
            scope: str | None = None,
            env: dict[str, str] | None = None,
            config: dict[str, dict[str, str]] | None = None,
        ) -> None:
            warnings.simplefilter("always")
            with pytest.warns(DeprecationWarning) as record:
                options = self._parse(flags=flags, env=env, config=config)
                scoped_options = (
                    options.for_global_scope() if not scope else options.for_scope(scope)
                )

            assert getattr(scoped_options, option) == expected
            assert len(record) == 1
            assert "will be removed in version" in str(record[0].message)
            assert option in str(record[0].message)

        assert_deprecation_triggered(
            flags="--global-crufty=crufty1",
            option="global_crufty",
            expected="crufty1",
        )
        assert_deprecation_triggered(
            flags="--global-crufty-boolean",
            option="global_crufty_boolean",
            expected=True,
        )
        assert_deprecation_triggered(
            flags="--no-global-crufty-boolean",
            option="global_crufty_boolean",
            expected=False,
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
            env={"PANTS_GLOBAL_CRUFTY": "crufty1"},
            option="global_crufty",
            expected="crufty1",
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
        with pytest.warns(None) as record:
            self._parse(flags="stale --pants-foo stale --still-good")
        assert len(record) == 0

    @unittest.mock.patch("pants.base.deprecated.PANTS_SEMVER", Version(_FAKE_CUR_VERSION))
    def test_delayed_deprecated_option(self) -> None:
        warnings.simplefilter("always")
        with pytest.warns(None) as record:
            delayed_deprecation_option_value = (
                self._parse(flags="--global-delayed-deprecated-option=xxx")
                .for_global_scope()
                .global_delayed_deprecated_option
            )
            assert delayed_deprecation_option_value == "xxx"
            assert len(record) == 0

        with pytest.warns(DeprecationWarning) as record:
            delayed_passed_option_value = (
                self._parse(flags="--global-delayed-but-already-passed-deprecated-option=xxx")
                .for_global_scope()
                .global_delayed_but_already_passed_deprecated_option
            )
            assert delayed_passed_option_value == "xxx"
            assert len(record) == 1
            assert "will be removed in version" in str(record[0].message)
            assert "global_delayed_but_already_passed_deprecated_option" in str(record[0].message)

    def test_mutually_exclusive_options(self) -> None:
        """Ensure error is raised when mutual exclusive options are given together."""

        def assert_mutually_exclusive_raised(
            *,
            flags: str,
            scope: str | None = None,
            env: dict[str, str] | None = None,
            config: dict[str, dict[str, str]] | None = None,
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
            flags="stale --mutex-a=foo",
            env={"PANTS_STALE_MUTEX_B": "bar"},
            scope="stale",
        )
        assert_mutually_exclusive_raised(
            flags="stale --crufty-new=foo",
            env={"PANTS_STALE_CRUFTY_OLD": "bar"},
            scope="stale",
        )

        assert_mutually_exclusive_raised(
            flags="--mutex-foo=foo",
            config={"GLOBAL": {"mutex_bar": "bar"}},
        )
        assert_mutually_exclusive_raised(
            flags="--new-name=foo",
            config={"GLOBAL": {"old_name": "bar"}},
        )
        assert_mutually_exclusive_raised(
            flags="stale --mutex-a=foo",
            config={"stale": {"mutex_b": "bar"}},
            scope="stale",
        )
        assert_mutually_exclusive_raised(
            flags="stale --crufty-old=foo",
            config={"stale": {"crufty_new": "bar"}},
            scope="stale",
        )

        def assert_other_option_also_set(
            *,
            flags: str = "",
            other_option: str,
            scope: str | None = None,
            env: dict[str, str] | None = None,
            config: dict[str, dict[str, str]] | None = None,
        ) -> None:
            options = self._parse(flags=flags, env=env, config=config)
            scoped_options = options.for_global_scope() if not scope else options.for_scope(scope)
            assert getattr(scoped_options, other_option) == "orz"

        assert_other_option_also_set(flags="--mutex-foo=orz", other_option="mutex")
        assert_other_option_also_set(flags="--old-name=orz", other_option="new_name")
        assert_other_option_also_set(
            flags="stale --mutex-a=orz",
            other_option="crufty_mutex",
            scope="stale",
        )
        assert_other_option_also_set(
            flags="stale --crufty-old=orz",
            other_option="crufty_new",
            scope="stale",
        )
        assert_other_option_also_set(env={"PANTS_GLOBAL_MUTEX_BAZ": "orz"}, other_option="mutex")
        assert_other_option_also_set(env={"PANTS_OLD_NAME": "orz"}, other_option="new_name")
        assert_other_option_also_set(
            env={"PANTS_STALE_MUTEX_B": "orz"},
            other_option="crufty_mutex",
            scope="stale",
        )
        assert_other_option_also_set(
            config={"stale": {"crufty_old": "orz"}},
            other_option="crufty_new",
            scope="stale",
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
        def _do_assert_fromfile(dest, expected, contents, passthru_flags=""):
            with temporary_file(binary_mode=False) as fp:
                fp.write(contents)
                fp.close()
                options = parse_func(dest, fp.name, passthru_flags)
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
        _do_assert_fromfile(
            dest="passthru_listvalue",
            expected=["a", "1", "2", "bob", "@jake"],
            contents=dedent(
                """
                ['a',
                 1,
                 2]
                """
            ),
            passthru_flags="bob @jake",
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
        def parse_func(dest, fromfile, passthru_flags):
            return self._parse(
                flags=f"fromfile --{dest.replace('_', '-')}=@{fromfile} -- {passthru_flags}"
            )

        # You can only append a single item at a time with append flags, ie: we don't override the
        # default list like we do with env of config.  As such, send in a single append value here
        # instead of a whole default list as in `test_fromfile_config` and `test_fromfile_env`.
        self.assert_fromfile(parse_func, expected_append=[42], append_contents="42")

    def test_fromfile_config(self) -> None:
        def parse_func(dest, fromfile, passthru_flags):
            return self._parse(
                flags=f"fromfile -- {passthru_flags}", config={"fromfile": {dest: f"@{fromfile}"}}
            )

        self.assert_fromfile(parse_func)

    def test_fromfile_env(self) -> None:
        def parse_func(dest, fromfile, passthru_flags):
            return self._parse(
                flags=f"fromfile -- {passthru_flags}",
                env={f"PANTS_FROMFILE_{dest.upper()}": f"@{fromfile}"},
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
            flags="--a=1 compile --b=2 compile.java --a=3 --c=4",
            env=env,
            config=config,
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
        warnings.simplefilter("always")

        class DummyOptionable1(Optionable):
            options_scope = "new-scope1"
            deprecated_options_scope = "deprecated-scope"
            deprecated_options_scope_removal_version = "9999.9.9.dev0"

        class DummyOptionable2(Optionable):
            options_scope = "new-scope2"
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

        with pytest.warns(DeprecationWarning) as record:
            vals1 = options.for_scope(DummyOptionable1.options_scope)

        # Check that we got a warning, but not for the inherited option.
        assert len(record) == 1
        assert "inherited" not in str(record[0].message)

        # Check values.
        # Deprecated scope takes precedence at equal rank.
        self.assertEqual("yy", vals1.foo)
        self.assertEqual("zz", vals1.bar)
        # New scope takes precedence at higher rank.
        self.assertEqual("vv", vals1.baz)

        with pytest.warns(DeprecationWarning) as record:
            vals2 = options.for_scope(DummyOptionable2.options_scope)

        # Check that we got a warning.
        assert len(record) == 1
        assert "inherited" not in str(record[0].message)

        # Check values.
        self.assertEqual("uu", vals2.qux)

    def test_scope_deprecation_parent(self) -> None:
        # Note: This test demonstrates that a scope can mark itself as deprecating a subscope of
        # another scope.
        warnings.simplefilter("always")

        class DummyOptionable1(Optionable):
            options_scope = "test"

            @classmethod
            def register_options(cls, register):
                super().register_options(register)
                register("--bar")

        class DummyOptionable2(Optionable):
            options_scope = "lint"
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

        with pytest.warns(DeprecationWarning) as record:
            vals = options.for_scope(DummyOptionable2.options_scope)

        # Check that we got a warning, but also the correct value.
        assert len(record) == 1
        assert vals.foo == "vv"

    def test_scope_deprecation_defaults(self) -> None:
        # Confirms that a DEFAULT option does not trigger deprecation warnings for a deprecated scope.
        warnings.simplefilter("always")

        class DummyOptionable1(Optionable):
            options_scope = "new-scope1"
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

        with pytest.warns(None) as record:
            vals1 = options.for_scope(DummyOptionable1.options_scope)

        # Check that we got no warnings and that the actual scope took precedence.
        assert len(record) == 0
        assert vals1.foo == "xx"

    def test_scope_dependency_deprecation(self) -> None:
        # Test that a dependency scope can be deprecated.
        warnings.simplefilter("always")

        class DummyOptionable1(Optionable):
            options_scope = "scope"

        options = Options.create(
            env={},
            config=self._create_config(),
            known_scope_infos=[
                global_scope(),
                DummyOptionable1.get_scope_info(),
                # A deprecated, scoped dependency on `DummyOptionable1`. This
                # imitates the construction of Subsystem.known_scope_infos.
                ScopeInfo(
                    DummyOptionable1.subscope("sub"),
                    DummyOptionable1,
                    removal_version="9999.9.9.dev0",
                    removal_hint="Sayonara!",
                ),
            ],
            args=shlex.split("./pants --scope-sub-foo=vv"),
        )

        options.register(DummyOptionable1.options_scope, "--foo")

        with pytest.warns(DeprecationWarning) as record:
            vals1 = options.for_scope(DummyOptionable1.subscope("sub"))

        # Check that we got a warning, but also the correct value.
        assert len(record) == 1
        assert vals1.foo == "vv"

    def test_list_of_enum_single_value(self) -> None:
        options = self._parse(flags="other-enum-scope --some-list-enum=another-value")
        assert [self.SomeEnumOption.another_value] == options.for_scope(
            "other-enum-scope"
        ).some_list_enum

    def test_list_of_enum_default_value(self) -> None:
        options = self._parse(flags="other-enum-scope --some-list-enum-with-default=another-value")
        assert [
            self.SomeEnumOption.yet_another,
            self.SomeEnumOption.another_value,
        ] == options.for_scope("other-enum-scope").some_list_enum_with_default
        options = self._parse()
        assert [self.SomeEnumOption.yet_another] == options.for_scope(
            "other-enum-scope"
        ).some_list_enum_with_default

    def test_list_of_enum_from_config(self) -> None:
        options = self._parse(
            config={"other-enum-scope": {"some_list_enum": "['one-more', 'a-value']"}}
        )
        assert [self.SomeEnumOption.one_more, self.SomeEnumOption.a_value] == options.for_scope(
            "other-enum-scope"
        ).some_list_enum

    def test_list_of_enum_duplicates(self) -> None:
        options = self._parse(
            flags="other-enum-scope --some-list-enum=\"['another-value', 'one-more', 'another-value']\""
        )
        with pytest.raises(ParseError, match="Duplicate enum values specified in list"):
            options.for_scope("other-enum-scope")

    def test_list_of_enum_invalid_value(self) -> None:
        options = self._parse(
            flags="other-enum-scope --some-list-enum=\"['another-value', 'not-a-value']\""
        )
        with pytest.raises(ParseError, match="Error computing value for --some-list-enum"):
            options.for_scope("other-enum-scope")

    def test_list_of_enum_set_single_value(self) -> None:
        options = self._parse(
            flags="other-enum-scope --some-list-enum-with-default=\"['another-value']\""
        )
        assert [self.SomeEnumOption.another_value] == options.for_scope(
            "other-enum-scope"
        ).some_list_enum_with_default

    def test_list_of_enum_append(self) -> None:
        options = self._parse(
            flags="other-enum-scope --some-list-enum-with-default=\"+['another-value']\""
        )
        assert [
            self.SomeEnumOption.yet_another,
            self.SomeEnumOption.another_value,
        ] == options.for_scope("other-enum-scope").some_list_enum_with_default

    def test_list_of_enum_remove(self) -> None:
        options = self._parse(
            flags="other-enum-scope --some-list-enum-with-default=\"-['yet-another']\""
        )
        assert [] == options.for_scope("other-enum-scope").some_list_enum_with_default
