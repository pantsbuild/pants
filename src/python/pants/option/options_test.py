# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
import os
import shlex
import unittest.mock
from contextlib import contextmanager
from enum import Enum
from functools import partial
from textwrap import dedent
from typing import Any, Callable, Dict, List, cast

import pytest
import toml
import yaml
from packaging.version import Version

from pants.base.deprecated import CodeRemovedError
from pants.base.hash_utils import CoercingEncoder
from pants.engine.fs import FileContent
from pants.option.config import Config
from pants.option.custom_types import UnsetBool, file_option, shell_str, target_option
from pants.option.errors import (
    BooleanConversionError,
    BooleanOptionNameWithNo,
    DefaultValueType,
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
from pants.option.options import Options
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.option.parser import Parser
from pants.option.ranked_value import Rank, RankedValue
from pants.option.scope import GLOBAL_SCOPE, ScopeInfo
from pants.option.subsystem import Subsystem
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


def create_options(
    scopes: list[str],
    register_fn: Callable[[Options], None],
    args: list[str] | None = None,
    *,
    env: dict[str, str] | None = None,
    config: dict[str, dict[str, Any]] | None = None,
    extra_scope_infos: list[ScopeInfo] | None = None,
) -> Options:
    options = Options.create(
        env=env or {},
        config=Config.load_file_contents(
            [FileContent("pants.toml", toml.dumps(config or {}).encode())]
        ),
        known_scope_infos=[*(ScopeInfo(scope) for scope in scopes), *(extra_scope_infos or ())],
        args=["./pants", *(args or ())],
    )
    register_fn(options)
    return options


# ----------------------------------------------------------------------------------------
# Boolean handling.
# ----------------------------------------------------------------------------------------


def register_bool_opts(opts: Options) -> None:
    opts.register(GLOBAL_SCOPE, "--default-missing", type=bool)
    opts.register(GLOBAL_SCOPE, "--default-true", type=bool, default=True)
    opts.register(GLOBAL_SCOPE, "--default-false", type=bool, default=False)
    opts.register(GLOBAL_SCOPE, "--unset", type=bool, default=UnsetBool)
    opts.register(GLOBAL_SCOPE, "--implicit-true", type=bool, implicit_value=True)
    opts.register(GLOBAL_SCOPE, "--implicit-false", type=bool, implicit_value=False)
    opts.register(
        GLOBAL_SCOPE,
        "--implicit-false-default-false",
        type=bool,
        implicit_value=False,
        default=False,
    )
    opts.register(
        GLOBAL_SCOPE, "--implicit-false-default-true", type=bool, implicit_value=False, default=True
    )


def test_bool_explicit_values() -> None:
    def register(opt: Options) -> None:
        opt.register(GLOBAL_SCOPE, "--opt", type=bool)

    def assert_val(arg: str, expected: bool) -> None:
        global_options = create_options(
            [GLOBAL_SCOPE], register, [f"--opt={arg}"]
        ).for_global_scope()
        assert global_options.opt is expected

    assert_val("false", False)
    assert_val("False", False)
    assert_val("true", True)
    assert_val("True", True)


def test_bool_defaults() -> None:
    opts = create_options([GLOBAL_SCOPE], register_bool_opts).for_global_scope()
    assert opts.default_missing is False
    assert opts.default_true is True
    assert opts.default_false is False

    assert opts.unset is None

    assert opts.implicit_true is False
    assert opts.implicit_false is True
    assert opts.implicit_false_default_false is False
    assert opts.implicit_false_default_true is True


def test_bool_args() -> None:
    opts = create_options(
        [GLOBAL_SCOPE],
        register_bool_opts,
        [
            "--default-missing",
            "--default-true",
            "--default-false",
            "--unset",
            "--implicit-true",
            "--implicit-false",
            "--implicit-false-default-false",
            "--implicit-false-default-true",
        ],
    ).for_global_scope()
    assert opts.default_missing is True
    assert opts.default_true is True
    assert opts.default_false is True

    assert opts.unset is True

    assert opts.implicit_true is True
    assert opts.implicit_false is False
    assert opts.implicit_false_default_false is False
    assert opts.implicit_false_default_true is False


def test_bool_negate() -> None:
    opts = create_options(
        [GLOBAL_SCOPE],
        register_bool_opts,
        [
            "--no-default-missing",
            "--no-default-true",
            "--no-default-false",
            "--no-unset",
            "--no-implicit-true",
            "--no-implicit-false",
            "--no-implicit-false-default-false",
            "--no-implicit-false-default-true",
        ],
    ).for_global_scope()
    assert opts.default_missing is False
    assert opts.default_true is False
    assert opts.default_false is False

    assert opts.unset is False

    assert opts.implicit_true is False
    assert opts.implicit_false is True
    assert opts.implicit_false_default_false is True
    assert opts.implicit_false_default_true is True


@pytest.mark.parametrize("val", [False, True])
def test_bool_config(val: bool) -> None:
    opt_names = (
        "default_missing",
        "default_true",
        "default_false",
        "implicit_true",
        "implicit_false",
        "implicit_false_default_false",
        "implicit_false_default_true",
    )
    opts = create_options(
        [GLOBAL_SCOPE], register_bool_opts, config={"GLOBAL": {opt: val for opt in opt_names}}
    ).for_global_scope()
    for opt in opt_names:
        assert opts[opt] is val, f"option {opt} has value {opts[opt]} but expected {val}"


@pytest.mark.parametrize("val", (11, "AlmostTrue"))
def test_bool_invalid_value(val: Any) -> None:
    def register(opts: Options) -> None:
        opts.register(GLOBAL_SCOPE, "--opt", type=bool)

    with pytest.raises(BooleanConversionError):
        create_options([GLOBAL_SCOPE], register, config={"GLOBAL": {"opt": val}}).for_global_scope()


# ----------------------------------------------------------------------------------------
# Type checks
# ----------------------------------------------------------------------------------------


@contextmanager
def no_exception():
    """use in tests as placeholder for a pytest.raises, when no exception is expected."""
    yield None


@pytest.mark.parametrize(
    "option_kwargs, assert_expected",
    [
        (
            dict(type=str, default=""),
            no_exception(),
        ),
        (
            dict(type=str, default=42),
            pytest.raises(
                DefaultValueType, match=r"Default value int\(42\) does not match option type str\."
            ),
        ),
        (
            dict(type=bool, default="True"),
            no_exception(),
        ),
        (
            dict(type=bool, default=True),
            no_exception(),
        ),
        (
            dict(type=bool, default="not a bool"),
            pytest.raises(
                BooleanConversionError, match=r'Got "not a bool"\. Expected "True" or "False"\.'
            ),
        ),
        (
            dict(type=int, default=1.0),
            pytest.raises(
                DefaultValueType,
                match=r"Default value float\(1\.0\) does not match option type int\. \[option --opt in global scope\]\.",
            ),
        ),
        (
            dict(type=list, member_type=int, default="[1, 2, 3]"),
            no_exception(),
        ),
        (
            dict(type=list, member_type=int, default="[1, 2.1, 3]"),
            pytest.raises(
                DefaultValueType,
                match=r"Default member value type mismatch\.\n\n    Member value float\(2\.1\) does not match list option type int\.",
            ),
        ),
        (
            dict(type=list, member_type=float, default="[1.1, 2.0, 3.3]"),
            no_exception(),
        ),
        (
            dict(type=list, member_type=float, default="[1.1, 2.2, '3.3']"),
            pytest.raises(
                DefaultValueType,
                match=r"Member value str\('3\.3'\) does not match list option type float\.",
            ),
        ),
        (
            dict(type=dict, default="{'foo': 'bar'}"),
            no_exception(),
        ),
        (
            dict(type=dict, default="['foo', 'bar']"),
            pytest.raises(ParseError, match=r"Invalid dict value: \['foo', 'bar'\]"),
        ),
    ],
)
def test_default_value_type_assert(option_kwargs, assert_expected):
    def register(opts: Options) -> None:
        opts.register(GLOBAL_SCOPE, "--opt", **option_kwargs)

    with assert_expected:
        create_options([GLOBAL_SCOPE], register).for_scope(GLOBAL_SCOPE)


# ----------------------------------------------------------------------------------------
# Deprecations.
# ----------------------------------------------------------------------------------------


def test_deprecated_options(caplog) -> None:
    def register(opts: Options) -> None:
        opts.register(
            GLOBAL_SCOPE, "--old1", removal_version="999.99.9.dev0", removal_hint="Stop it."
        )
        opts.register(
            GLOBAL_SCOPE,
            "--bool1",
            type=bool,
            removal_version="999.99.9.dev0",
            removal_hint="¡Basta!",
        )
        opts.register("scope", "--valid")
        opts.register(
            "scope", "--old2", removal_version="999.99.9.dev0", removal_hint="Stop with the scope."
        )
        opts.register(
            "scope",
            "--bool2",
            type=bool,
            removal_version="999.99.9.dev0",
            removal_hint="¡Basta but scoped!",
        )

    def assert_deprecated(
        scope: str,
        opt: str,
        args: list[str],
        *,
        expected: str | bool,
        env: dict[str, str] | None = None,
        config: dict[str, dict[str, str]] | None = None,
    ) -> None:
        caplog.clear()
        opts = create_options([GLOBAL_SCOPE, "scope"], register, args, env=env, config=config)
        assert opts.for_scope(scope)[opt] == expected
        assert len(caplog.records) == 1
        assert "will be removed in version" in caplog.text
        assert opt in caplog.text

    assert_deprecated(GLOBAL_SCOPE, "old1", ["--old1=x"], expected="x")
    assert_deprecated(GLOBAL_SCOPE, "bool1", ["--bool1"], expected=True)
    assert_deprecated(GLOBAL_SCOPE, "bool1", ["--no-bool1"], expected=False)
    assert_deprecated("scope", "old2", ["scope", "--old2=x"], expected="x")
    assert_deprecated("scope", "old2", ["--scope-old2=x"], expected="x")
    assert_deprecated("scope", "bool2", ["scope", "--bool2"], expected=True)
    assert_deprecated("scope", "bool2", ["scope", "--no-bool2"], expected=False)
    assert_deprecated("scope", "bool2", ["--scope-bool2"], expected=True)
    assert_deprecated("scope", "bool2", ["--no-scope-bool2"], expected=False)

    assert_deprecated(GLOBAL_SCOPE, "old1", [], env={"PANTS_GLOBAL_OLD1": "x"}, expected="x")
    assert_deprecated("scope", "old2", [], env={"PANTS_SCOPE_OLD2": "x"}, expected="x")

    assert_deprecated(GLOBAL_SCOPE, "old1", [], config={"GLOBAL": {"old1": "x"}}, expected="x")
    assert_deprecated("scope", "old2", [], config={"scope": {"old2": "x"}}, expected="x")

    # Make sure the warnings don't come out for regular options.
    caplog.clear()
    assert (
        create_options([GLOBAL_SCOPE, "scope"], register, ["--scope-valid=x"])
        .for_scope("scope")
        .valid
        == "x"
    )
    assert not caplog.records


def test_deprecated_options_error() -> None:
    def register(opts: Options) -> None:
        opts.register(GLOBAL_SCOPE, "--expired", removal_version="0.0.1.dev0")

    with pytest.raises(CodeRemovedError):
        create_options([GLOBAL_SCOPE], register, [])


@unittest.mock.patch("pants.base.deprecated.PANTS_SEMVER", Version(_FAKE_CUR_VERSION))
def test_deprecated_options_start_version(caplog) -> None:
    def register(opts: Options) -> None:
        opts.register(
            GLOBAL_SCOPE,
            "--delayed",
            removal_version="999.99.9.dev0",
            deprecation_start_version="500.0.0.dev0",
        )
        opts.register(
            GLOBAL_SCOPE,
            "--past-start",
            removal_version="999.99.9.dev0",
            deprecation_start_version=_FAKE_CUR_VERSION,
        )

    caplog.clear()
    assert (
        create_options([GLOBAL_SCOPE], register, ["--delayed=x"]).for_global_scope().delayed == "x"
    )
    assert not caplog.records

    assert (
        create_options([GLOBAL_SCOPE], register, ["--past-start=x"]).for_global_scope().past_start
        == "x"
    )
    assert len(caplog.records) == 1
    assert "will be removed in version" in caplog.text
    assert "past_start" in caplog.text


def test_scope_deprecation(caplog) -> None:
    # This test demonstrates that two different new scopes can deprecate the same
    # old scope. I.e., it's possible to split an old scope's options among multiple new scopes.
    class Subsystem1(Subsystem):
        options_scope = "new1"
        deprecated_options_scope = "deprecated"
        deprecated_options_scope_removal_version = "9999.9.9.dev0"

        @classmethod
        def register_options(cls, register):
            super().register_options(register)
            register("--foo")
            register("--bar")
            register("--baz")

    class Subsystem2(Subsystem):
        options_scope = "new2"
        deprecated_options_scope = "deprecated"
        deprecated_options_scope_removal_version = "9999.9.9.dev0"

        @classmethod
        def register_options(cls, register):
            super().register_options(register)
            register("--qux")

    def register(opts: Options) -> None:
        opts.register(Subsystem1.options_scope, "--foo")
        opts.register(Subsystem1.options_scope, "--bar")
        opts.register(Subsystem1.options_scope, "--baz")
        opts.register(Subsystem2.options_scope, "--qux")

    opts = create_options(
        [GLOBAL_SCOPE],
        register,
        ["--new1-baz=vv"],
        extra_scope_infos=[Subsystem1.get_scope_info(), Subsystem2.get_scope_info()],
        config={
            Subsystem1.options_scope: {"foo": "xx"},
            Subsystem1.deprecated_options_scope: {
                "foo": "yy",
                "bar": "zz",
                "baz": "ww",
                "qux": "uu",
            },
        },
    )

    caplog.clear()
    vals1 = opts.for_scope(Subsystem1.options_scope)
    assert len(caplog.records) == 1
    assert Subsystem1.deprecated_options_scope in caplog.text
    assert "foo" in caplog.text
    # Deprecated scope takes precedence at equal rank, but new scope takes precedence at higher
    # rank.
    assert vals1.foo == "yy"
    assert vals1.bar == "zz"
    assert vals1.baz == "vv"

    caplog.clear()
    vals2 = opts.for_scope(Subsystem2.options_scope)
    assert len(caplog.records) == 1
    assert Subsystem1.deprecated_options_scope in caplog.text
    assert "qux" in caplog.text
    assert vals2.qux == "uu"


def test_scope_deprecation_parent(caplog) -> None:
    # This test demonstrates that a scope can mark itself as deprecating a subscope of
    # another scope.
    class Subsystem1(Subsystem):
        options_scope = "test"

    class Subsystem2(Subsystem):
        options_scope = "lint"
        deprecated_options_scope = "test.a-bit-linty"
        deprecated_options_scope_removal_version = "9999.9.9.dev0"

    def register(opts: Options) -> None:
        opts.register(Subsystem1.options_scope, "--bar")
        opts.register(Subsystem2.options_scope, "--foo")

    opts = create_options(
        [GLOBAL_SCOPE],
        register,
        ["--test-a-bit-linty-foo=vv"],
        extra_scope_infos=[Subsystem1.get_scope_info(), Subsystem2.get_scope_info()],
    )

    # NB: Order matters here because Subsystems are typically registered in sorted order.
    Subsystem2.register_options_on_scope(opts)
    Subsystem1.register_options_on_scope(opts)

    caplog.clear()
    assert opts.for_scope(Subsystem2.options_scope).foo == "vv"
    assert len(caplog.records) == 1
    assert "test.a-bit-linty" in caplog.text


def test_scope_deprecation_default_config_section(caplog) -> None:
    # Confirms that a DEFAULT option does not trigger deprecation warnings for a deprecated scope.
    class Subsystem1(Subsystem):
        options_scope = "new"
        deprecated_options_scope = "deprecated"
        deprecated_options_scope_removal_version = "9999.9.9.dev0"

    def register(opts: Options) -> None:
        opts.register(Subsystem1.options_scope, "--foo")

    opts = create_options(
        [GLOBAL_SCOPE],
        register,
        [],
        extra_scope_infos=[Subsystem1.get_scope_info()],
        config={"DEFAULT": {"foo": "aa"}, Subsystem1.options_scope: {"foo": "xx"}},
    )
    caplog.clear()
    assert opts.for_scope(Subsystem1.options_scope).foo == "xx"
    assert not caplog.records


def test_scope_deprecation_dependency(caplog) -> None:
    # Test that a dependency scope can be deprecated.
    class Subsystem1(Subsystem):
        options_scope = "scope"

    def register(opts: Options) -> None:
        opts.register(Subsystem1.options_scope, "--foo")

    opts = create_options(
        [GLOBAL_SCOPE],
        register,
        ["--scope-sub-foo=vv"],
        extra_scope_infos=[
            Subsystem1.get_scope_info(),
            # A deprecated, scoped dependency on `Subsystem1`. This
            # imitates the construction of Subsystem.known_scope_infos.
            ScopeInfo(
                Subsystem1.subscope("sub"),
                Subsystem1,
                removal_version="9999.9.9.dev0",
                removal_hint="Sayonara!",
            ),
        ],
    )

    caplog.clear()
    assert opts.for_scope(Subsystem1.subscope("sub")).foo == "vv"
    assert len(caplog.records) == 1
    assert Subsystem1.subscope("sub") in caplog.text


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
        ScopeInfo(scope)
        for scope in (
            GLOBAL_SCOPE,
            "compile",
            "compile.java",
            "compile.scala",
            "cache.compile.scala",
            "stale",
            "test",
            "test.junit",
            "passconsumer",
            "simple",
            "simple-dashed",
            "scoped.a.bit",
            "scoped.and-dashed",
            "fromfile",
            "fingerprinting",
            "enum-opt",
            "separate-enum-opt-scope",
            "other-enum-scope",
        )
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

        # Mutual Exclusive options
        register_global("--mutex-foo", mutually_exclusive_group="mutex")
        register_global("--mutex-bar", mutually_exclusive_group="mutex")
        register_global("--mutex-baz", mutually_exclusive_group="mutex")

        register_global("--new-name")
        register_global("--old-name", mutually_exclusive_group="new_name")

        # For the design doc example test.
        options.register("compile", "--c", type=int)

        # Test mutual exclusive options with a scope
        options.register("stale", "--mutex-a", mutually_exclusive_group="scope_mutex")
        options.register("stale", "--mutex-b", mutually_exclusive_group="scope_mutex")
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
        with pytest.raises(ParseError) as exc:
            options = self._parse(flags="enum-opt --some-enum=invalid-value")
            options.for_scope("enum-opt")

        assert (
            "Invalid choice 'invalid-value'. "
            "Choose from: a-value, another-value, yet-another, one-more"
        ) in str(exc.value)

    def test_non_enum_option_type_parse_error(self) -> None:
        with pytest.raises(ParseError) as exc:
            options = self._parse(flags="--a=not-a-number")
            options.for_global_scope()

        assert (
            "Error applying type 'int' to option value 'not-a-number': invalid literal for int()"
        ) in str(exc.value)

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

        # Mutexes should not impact the `dest`. We spot check that here.
        def assert_option_set(
            flags: str,
            option: str,
            expected: str | None,
        ) -> None:
            options = self._parse(flags=flags).for_global_scope()
            assert getattr(options, option) == expected

        assert_option_set("--mutex-foo=orz", "mutex_foo", "orz")
        assert_option_set("--mutex-foo=orz", "mutex_bar", None)
        assert_option_set("--mutex-foo=orz", "mutex_baz", None)
        assert_option_set("--mutex-bar=orz", "mutex_bar", "orz")

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
