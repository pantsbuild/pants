# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
import shlex
import unittest.mock
from contextlib import contextmanager
from enum import Enum
from functools import partial
from pathlib import Path
from textwrap import dedent
from typing import Any, Callable, Dict, cast

import pytest
import toml
import yaml
from packaging.version import Version

from pants.base.build_environment import get_buildroot
from pants.base.deprecated import CodeRemovedError, warn_or_error
from pants.engine.fs import FileContent
from pants.option.config import Config
from pants.option.custom_types import UnsetBool, file_option, shell_str, target_option
from pants.option.errors import (
    BooleanConversionError,
    BooleanOptionNameWithNo,
    DefaultValueType,
    FromfileError,
    HelpType,
    ImplicitValIsNone,
    InvalidKwarg,
    InvalidMemberType,
    MemberTypeNotAllowed,
    MutuallyExclusiveOptionError,
    NoOptionNames,
    OptionAlreadyRegistered,
    OptionNameDoubleDash,
    ParseError,
)
from pants.option.global_options import GlobalOptions
from pants.option.option_types import StrOption
from pants.option.options import Options
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.option.options_fingerprinter import OptionEncoder
from pants.option.parser import Parser
from pants.option.ranked_value import Rank, RankedValue
from pants.option.scope import GLOBAL_SCOPE, ScopeInfo
from pants.option.subsystem import Subsystem
from pants.util.contextutil import pushd, temporary_dir, temporary_file, temporary_file_path

_FAKE_CUR_VERSION = "1.0.0.dev0"


def global_scope() -> ScopeInfo:
    return ScopeInfo(GLOBAL_SCOPE, GlobalOptions)


def task(scope: str) -> ScopeInfo:
    return ScopeInfo(scope, is_goal=True)


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
        config=Config.load([FileContent("pants.toml", toml.dumps(config or {}).encode())]),
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
            dict(type=bool, default=True),
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
        warn_or_error.clear()  # type: ignore[attr-defined]
        opts = create_options([GLOBAL_SCOPE, "scope"], register, args, env=env, config=config)
        assert opts.for_scope(scope)[opt] == expected
        assert len(caplog.records) == 1
        assert "is scheduled to be removed in version" in caplog.text
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
    warn_or_error.clear()  # type: ignore[attr-defined]
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
    assert "is scheduled to be removed in version" in caplog.text
    assert "past_start" in caplog.text


def test_scope_deprecation(caplog) -> None:
    # This test demonstrates that two different new scopes can deprecate the same
    # old scope. I.e., it's possible to split an old scope's options among multiple new scopes.
    class Subsystem1(Subsystem):
        options_scope = "new1"
        deprecated_options_scope = "deprecated"
        deprecated_options_scope_removal_version = "9999.9.9.dev0"

        foo = StrOption(default=None, help="")
        bar = StrOption(default=None, help="")
        baz = StrOption(default=None, help="")

    class Subsystem2(Subsystem):
        options_scope = "new2"
        deprecated_options_scope = "deprecated"
        deprecated_options_scope_removal_version = "9999.9.9.dev0"

        qux = StrOption(default=None, help="")

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


def _create_config(
    config: dict[str, dict[str, str]] | None = None,
    config2: dict[str, dict[str, str]] | None = None,
) -> Config:
    config_content = toml.dumps(config or {}).encode()
    config2_content = toml.dumps(config2 or {}).encode()
    # Write to files, for the Rust parser.
    with open("test_config.toml", "wb") as fp:
        fp.write(config_content)
    with open("test_config2.toml", "wb") as fp:
        fp.write(config2_content)
    # Load in memory, for the Python parser.
    return Config.load(
        [
            FileContent("test_config.toml", config_content),
            FileContent("test_config2.toml", config2_content),
        ]
    )


def _parse(
    *,
    flags: str = "",
    env: dict[str, str] | None = None,
    config: dict[str, dict[str, Any]] | None = None,
    config2: dict[str, dict[str, Any]] | None = None,
    bootstrap_option_values=None,
) -> Options:
    args = ["./pants", *shlex.split(flags)]
    options = Options.create(
        env=env or {},
        config=_create_config(config, config2),
        known_scope_infos=_known_scope_infos,
        args=args,
        bootstrap_option_values=bootstrap_option_values,
    )
    _register(options)
    return options


_known_scope_infos = [
    ScopeInfo(scope)
    for scope in (
        GLOBAL_SCOPE,
        "anotherscope",
        "compile",
        "compile.java",
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


def _register(options):
    def register_global(*args, **kwargs):
        options.register(GLOBAL_SCOPE, *args, **kwargs)

    register_global("--verbose", type=bool, help="Verbose output.")
    register_global("--num", type=int, default=99)

    # NB: `-l` on the global scope is the only short arg we allow. We need to make sure it
    # works.
    register_global("-l", "--level", type=str, help="What level to use.")

    # Test that we can use the same name on the global scope and another scope.
    options.register("anotherscope", "--num", type=int, default=99)

    register_global("--y", type=list, member_type=int)
    register_global(
        "--v2", help="Two-letter long-form option, used to test option name suggestions."
    )
    register_global("--config-override", type=list)

    register_global("--pants-foo")
    register_global("--bar-baz")
    register_global("--store-true-flag", type=bool)

    # Choices.
    register_global("--str-choices", choices=["foo", "bar"])
    register_global("--int-choices", choices=[42, 99], type=list, member_type=int)

    # Custom types.
    register_global("--listy", type=list, member_type=int, default="[1, 2, 3]")
    register_global("--dicty", type=dict, default='{"a": "b"}')
    # register_global(
    #     "--dict-listy", type=list, member_type=dict, default='[{"a": 1, "b": 2}, {"c": 3}]'
    # )
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

    # Mutual Exclusive options
    register_global("--mutex-foo", mutually_exclusive_group="mutex")
    register_global("--mutex-bar", mutually_exclusive_group="mutex")
    register_global("--mutex-baz", mutually_exclusive_group="mutex")

    register_global("--new-name")
    register_global("--old-name", mutually_exclusive_group="new_name")

    # Test mutual exclusive options with a scope
    options.register("stale", "--mutex-a", mutually_exclusive_group="scope_mutex")
    options.register("stale", "--mutex-b", mutually_exclusive_group="scope_mutex")
    options.register("stale", "--crufty-old", mutually_exclusive_group="crufty_new")
    options.register("stale", "--crufty-new")

    # For scoped fingerprintable test
    options.register("compile", "--modifycompile")
    options.register("compile", "--modifylogs", fingerprint=False)
    options.register(
        "compile",
        "--modifypassthrough",
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
    register_global("--implicitly-fingerprinted")
    register_global("--explicitly-fingerprinted", fingerprint=True)
    register_global("--explicitly-not-fingerprinted", fingerprint=False)
    register_global("--implicitly-not-daemoned")
    register_global("--explicitly-not-daemoned", daemon=False)
    register_global("--explicitly-daemoned", daemon=True)

    # For enum tests
    options.register("enum-opt", "--some-enum", type=SomeEnumOption)
    options.register("other-enum-scope", "--some-list-enum", type=list, member_type=SomeEnumOption)
    options.register(
        "other-enum-scope",
        "--some-list-enum-with-default",
        type=list,
        member_type=SomeEnumOption,
        default=[SomeEnumOption.yet_another],
    )

    # For testing the default value
    options.register(
        "separate-enum-opt-scope",
        "--some-enum-with-default",
        default=SomeEnumOption.a_value,
        type=SomeEnumOption,
    )


def test_env_var_of_type_int() -> None:
    create_options_object = partial(
        Options.create,
        config=_create_config(),
        known_scope_infos=_known_scope_infos,
        args=shlex.split("./pants"),
    )
    options = create_options_object(env={"PANTS_FOO_BAR": "123"})
    options.register(GLOBAL_SCOPE, "--foo-bar", type=int)
    assert 123 == options.for_global_scope().foo_bar

    options = create_options_object(env={"PANTS_FOO_BAR": "['123','456']"})
    options.register(GLOBAL_SCOPE, "--foo-bar", type=list, member_type=int)
    assert [123, 456] == options.for_global_scope().foo_bar


def test_arg_scoping() -> None:
    # Some basic smoke tests.
    options = _parse(flags="--verbose")
    assert options.for_global_scope().verbose is True
    options = _parse(flags="--verbose compile path/to/tgt")
    assert ["path/to/tgt"] == options.specs
    assert options.for_global_scope().verbose is True

    options = _parse(flags="-linfo")
    assert options.for_global_scope().level == "info"
    options = _parse(flags="--level=info compile path/to/tgt")
    assert ["path/to/tgt"] == options.specs
    assert options.for_global_scope().level == "info"

    with pytest.raises(ParseError):
        _parse(flags="--unregistered-option compile").for_global_scope()

    # Scoping of different values of options with the same name in different scopes.
    options = _parse(flags="--num=11 anotherscope --num=22")
    assert 11 == options.for_global_scope().num
    assert 22 == options.for_scope("anotherscope").num

    # Test list-typed option.
    global_options = _parse(config={"DEFAULT": {"y": ["88", "-99"]}}).for_global_scope()
    assert [88, -99] == global_options.y

    global_options = _parse(
        flags="--y=5 --y=-6 --y=77", config={"DEFAULT": {"y": ["88", "-99"]}}
    ).for_global_scope()
    assert [88, -99, 5, -6, 77] == global_options.y

    global_options = _parse().for_global_scope()
    assert [] == global_options.y

    global_options = _parse(env={"PANTS_CONFIG_OVERRIDE": "['123','456']"}).for_global_scope()
    assert ["123", "456"] == global_options.config_override

    global_options = _parse(env={"PANTS_CONFIG_OVERRIDE": "['']"}).for_global_scope()
    assert [""] == global_options.config_override

    global_options = _parse(
        flags="--listy='[1, 2]'", config={"DEFAULT": {"listy": "[3, 4]"}}
    ).for_global_scope()
    assert [1, 2] == global_options.listy

    # Test dict-typed option.
    global_options = _parse(flags='--dicty=\'{"c": "d"}\'').for_global_scope()
    assert {"c": "d"} == global_options.dicty

    # Test list-of-dict-typed option.
    # global_options = _parse(flags='--dict-listy=\'[{"c": "d"}, {"e": "f"}]\'').for_global_scope()
    # assert [{"c": "d"}, {"e": "f"}] == global_options.dict_listy

    # Test target-typed option.
    global_options = _parse().for_global_scope()
    assert "//:a" == global_options.targety
    global_options = _parse(flags="--targety=//:foo").for_global_scope()
    assert "//:foo" == global_options.targety

    # Test list-of-target-typed option.
    global_options = _parse(flags='--target-listy=\'["//:foo", "//:bar"]\'').for_global_scope()
    assert ["//:foo", "//:bar"] == global_options.target_listy

    # Test file-typed option.
    with temporary_file_path() as fp:
        global_options = _parse(flags=f'--filey="{fp}"').for_global_scope()
        assert fp == global_options.filey

    # Test list-of-file-typed option.
    with temporary_file_path() as fp1:
        with temporary_file_path() as fp2:
            global_options = _parse(
                flags=f'--file-listy="{fp1}" --file-listy="{fp2}"'
            ).for_global_scope()
            assert [fp1, fp2] == global_options.file_listy


def test_list_option() -> None:
    def check(
        *,
        expected: list[int],
        flags: str = "",
        env_val: str | None = None,
        config_val: str | None = None,
        config2_val: str | None = None,
    ) -> None:
        env = {"PANTS_GLOBAL_LISTY": env_val} if env_val else None
        config = {"GLOBAL": {"listy": config_val}} if config_val else None
        config2 = {"GLOBAL": {"listy": config2_val}} if config2_val else None
        global_options = _parse(
            flags=flags, env=env, config=config, config2=config2
        ).for_global_scope()
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
        config_val="+[4,5],+[45]",
        expected=[*default, 4, 5, 45, 6, 7, 8, 9],
    )
    check(
        config_val="+[4,5],-[4]",
        expected=[*default, 5],
    )

    # Appending and filtering across env, config and flags (in the right order).
    check(
        flags="--listy=-[1,5,6]",
        env_val="+[6,7]",
        config_val="+[4,5]",
        config2_val="+[99]",
        expected=[2, 3, 4, 99, 7],
    )
    check(
        flags="--listy=+[8,9]",
        env_val="-[4,5]",
        config_val="+[4,5],-[3]",
        expected=[1, 2, 8, 9],
    )
    # Appending a value from a fromfile.
    with temporary_file(binary_mode=False) as fp:
        fp.write("-[3]")
        fp.close()
        check(
            flags="--listy=+[8,9]",
            env_val="-[4,5]",
            config_val="+[4,5]",
            config2_val=f"@{fp.name}",
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
        config2_val="-[4]",
        expected=[5, 6, 7, 8, 9],
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


# def test_dict_list_option() -> None:
#     def check(
#         *,
#         expected: list[dict[str, int]],
#         flags: str = "",
#         env_val: str | None = None,
#         config_val: str | None = None,
#     ) -> None:
#         env = {"PANTS_GLOBAL_DICT_LISTY": env_val} if env_val else None
#         config = {"GLOBAL": {"dict_listy": config_val}} if config_val else None
#         global_options = _parse(flags=flags, env=env, config=config).for_global_scope()
#         assert global_options.dict_listy == expected
#
#     default = [{"a": 1, "b": 2}, {"c": 3}]
#     one_element_appended = [*default, {"d": 4, "e": 5}]
#     two_elements_appended = [*one_element_appended, {"f": 6}]
#     replaced = [{"d": 4, "e": 5}, {"f": 6}]
#
#     check(expected=default)
#
#     check(flags='--dict-listy=\'{"d": 4, "e": 5}\'', expected=one_element_appended)
#     check(
#         flags='--dict-listy=\'{"d": 4, "e": 5}\' --dict-listy=\'{"f": 6}\'',
#         expected=two_elements_appended,
#     )
#     check(
#         flags='--dict-listy=\'+[{"d": 4, "e": 5}, {"f": 6}]\'',
#         expected=two_elements_appended,
#     )
#     check(flags='--dict-listy=\'[{"d": 4, "e": 5}, {"f": 6}]\'', expected=replaced)
#
#     check(env_val='{"d": 4, "e": 5}', expected=one_element_appended)
#     check(env_val='+[{"d": 4, "e": 5}, {"f": 6}]', expected=two_elements_appended)
#     check(env_val='[{"d": 4, "e": 5}, {"f": 6}]', expected=replaced)
#
#     check(config_val='{"d": 4, "e": 5}', expected=one_element_appended)
#     check(config_val='+[{"d": 4, "e": 5}, {"f": 6}]', expected=two_elements_appended)
#     check(config_val='[{"d": 4, "e": 5}, {"f": 6}]', expected=replaced)


def test_target_list_option() -> None:
    def check(
        *,
        expected: list[str],
        flags: str = "",
        env_val: str | None = None,
        config_val: str | None = None,
    ) -> None:
        env = {"PANTS_GLOBAL_TARGET_LISTY": env_val} if env_val else None
        config = {"GLOBAL": {"target_listy": config_val}} if config_val else None
        global_options = _parse(flags=flags, env=env, config=config).for_global_scope()
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


def test_shell_str_list() -> None:
    def check(
        *,
        expected: list[str],
        flags: str = "",
        env_val: str | None = None,
        config_val: str | None = None,
    ) -> None:
        env = {"PANTS_GLOBAL_SHELL_STR_LISTY": env_val} if env_val else None
        config = {"GLOBAL": {"shell_str_listy": config_val}} if config_val else None
        global_options = _parse(flags=flags, env=env, config=config).for_global_scope()
        assert global_options.shell_str_listy == expected

    default = ["--default1", "--default2=test"]
    specified_args = ["arg1", "arg2=foo", "--arg3"]
    all_args = [*default, *specified_args]

    check(expected=default)

    check(flags="--shell-str-listy='arg1 arg2=foo' --shell-str-listy='--arg3'", expected=all_args)
    check(flags="""--shell-str-listy='+["arg1 arg2=foo", "--arg3"]'""", expected=all_args)
    check(flags="""--shell-str-listy='["arg1 arg2=foo", "--arg3"]'""", expected=specified_args)

    check(env_val="arg1 arg2=foo --arg3", expected=all_args)
    check(env_val='+["arg1 arg2=foo", "--arg3"]', expected=all_args)
    check(env_val='["arg1 arg2=foo", "--arg3"]', expected=specified_args)

    check(config_val="arg1 arg2=foo --arg3", expected=all_args)
    check(config_val='+["arg1 arg2=foo", "--arg3"]', expected=all_args)
    check(config_val='["arg1 arg2=foo", "--arg3"]', expected=specified_args)


def test_dict_option() -> None:
    def check(
        *,
        expected: dict[str, str],
        flags: str = "",
        config_val: str | None = None,
        config2_val: str | None = None,
    ) -> None:
        config = {"GLOBAL": {"dicty": config_val}} if config_val else None
        config2 = {"GLOBAL": {"dicty": config2_val}} if config2_val else None
        global_options = _parse(flags=flags, config=config, config2=config2).for_global_scope()
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
        config2_val='+{"e": "f"}',
        flags='--dicty=\'+{"g": "h"}\'',
        expected={**all_args, "e": "f", "g": "h"},
    )
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


def test_defaults() -> None:
    # Hard-coded defaults.
    options = _parse(flags="anotherscope")
    assert 99 == options.for_global_scope().num
    assert 99 == options.for_scope("anotherscope").num

    # Get defaults from config and environment.
    config = {"DEFAULT": {"num": "88"}, "anotherscope": {"num": "77"}}
    options = _parse(flags="anotherscope", config=config)
    assert 88 == options.for_global_scope().num
    assert 77 == options.for_scope("anotherscope").num

    env = {"PANTS_ANOTHERSCOPE_NUM": "55"}
    options = _parse(flags="anotherscope", env=env, config=config)
    assert 88 == options.for_global_scope().num
    assert 55 == options.for_scope("anotherscope").num


def test_choices() -> None:
    options = _parse(flags="--str-choices=foo")
    assert "foo" == options.for_global_scope().str_choices
    options = _parse(config={"DEFAULT": {"str_choices": "bar"}})
    assert "bar" == options.for_global_scope().str_choices
    with pytest.raises(ParseError):
        options = _parse(flags="--str-choices=baz")
        options.for_global_scope()
    with pytest.raises(ParseError):
        options = _parse(config={"DEFAULT": {"str_choices": "baz"}})
        options.for_global_scope()

    options = _parse(flags="--int-choices=42 --int-choices=99")
    assert [42, 99] == options.for_global_scope().int_choices


def test_parse_dest() -> None:
    assert "thing" == Parser.parse_dest("--thing")
    assert "other_thing" == Parser.parse_dest("--thing", dest="other_thing")


def test_validation() -> None:
    def assertError(expected_error, *args, **kwargs):
        with pytest.raises(expected_error):
            options = Options.create(
                args=["./pants"],
                env={},
                config=_create_config(),
                known_scope_infos=[global_scope()],
            )
            options.register(GLOBAL_SCOPE, *args, **kwargs)
            options.for_global_scope()

    assertError(NoOptionNames)
    assertError(OptionNameDoubleDash, "badname")
    assertError(OptionNameDoubleDash, "-badname")
    assertError(InvalidKwarg, "--foo", badkwarg=42)
    assertError(ImplicitValIsNone, "--foo", implicit_value=None)
    assertError(BooleanOptionNameWithNo, "--no-foo", type=bool)
    assertError(MemberTypeNotAllowed, "--foo", member_type=int)
    assertError(MemberTypeNotAllowed, "--foo", type=dict, member_type=int)
    assertError(InvalidMemberType, "--foo", type=list, member_type=set)
    assertError(InvalidMemberType, "--foo", type=list, member_type=list)
    assertError(HelpType, "--foo", help=())
    assertError(HelpType, "--foo", help=("Help!",))


def test_implicit_value() -> None:
    def check(*, flag: str = "", expected: str) -> None:
        options = _parse(flags=flag)
        assert options.for_global_scope().implicit_valuey == expected

    check(expected="default")
    check(flag="--implicit-valuey", expected="implicit")
    check(flag="--implicit-valuey=explicit", expected="explicit")


def test_shadowing() -> None:
    options = Options.create(
        env={},
        config=_create_config(),
        known_scope_infos=[global_scope(), task("bar"), intermediate("foo"), task("foo.bar")],
        args=["./pants"],
    )
    options.register("", "--opt1")
    options.register("foo", "-o", "--opt2")


def test_is_known_scope() -> None:
    options = _parse()
    for scope_info in _known_scope_infos:
        assert options.is_known_scope(scope_info.scope)
    assert not options.is_known_scope("nonexistent_scope")


def test_file_spec_args() -> None:
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
        options = _parse(flags=flags, bootstrap_option_values=bootstrap_options)
        sorted_specs = sorted(options.specs)
        assert ["bar", "fleem:tgt", "foo", "morx:tgt"] == sorted_specs


def test_passthru_args_subsystems_and_goals():
    # Test that passthrough args are applied.
    options = Options.create(
        env={},
        config=_create_config(),
        known_scope_infos=[global_scope(), task("test"), subsystem("passconsumer")],
        args=["./pants", "test", "target", "--", "bar", "--baz", "@dont_fromfile_expand_me"],
    )
    options.register("passconsumer", "--passthing", passthrough=True, type=list, member_type=str)

    assert ["bar", "--baz", "@dont_fromfile_expand_me"] == options.for_scope(
        "passconsumer"
    ).passthing


def test_at_most_one_goal_with_passthru_args():
    with pytest.raises(Options.AmbiguousPassthroughError) as exc:
        Options.create(
            env={},
            config=_create_config(),
            known_scope_infos=[global_scope(), task("test"), task("fmt")],
            args=["./pants", "test", "fmt", "target", "--", "bar", "--baz"],
        )
    assert (
        "Specifying multiple goals (in this case: ['test', 'fmt']) along with passthrough args"
        + " (args after `--`) is ambiguous."
    ) in str(exc.value)


def test_passthru_args_not_interpreted():
    # Test that passthrough args are not interpreted.
    options = Options.create(
        env={},
        config=_create_config(
            {"consumer": {"shlexed": ["from config"], "string": ["from config"]}}
        ),
        known_scope_infos=[global_scope(), task("test"), subsystem("consumer")],
        args=[
            "./pants",
            "--consumer-shlexed=a",
            "--consumer-string=b",
            "test",
            "--",
            "[bar]",
            "multi token from passthrough",
        ],
    )
    options.register("consumer", "--shlexed", passthrough=True, type=list, member_type=shell_str)
    options.register("consumer", "--string", passthrough=True, type=list, member_type=str)

    assert [
        "from",
        "config",
        "a",
        "[bar]",
        "multi token from passthrough",
    ] == options.for_scope("consumer").shlexed
    assert ["from config", "b", "[bar]", "multi token from passthrough"] == options.for_scope(
        "consumer"
    ).string


def test_global_scope_env_vars():
    def check_pants_foo(expected_val, env):
        val = _parse(env=env).for_global_scope().pants_foo
        assert expected_val == val

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
        val = _parse(env=env).for_global_scope().bar_baz
        assert expected_val == val

    check_bar_baz("AAA", {"PANTS_GLOBAL_BAR_BAZ": "AAA", "PANTS_BAR_BAZ": "BBB", "BAR_BAZ": "CCC"})
    check_bar_baz("BBB", {"PANTS_BAR_BAZ": "BBB", "BAR_BAZ": "CCC"})
    check_bar_baz(None, {"BAR_BAZ": "CCC"})
    check_bar_baz(None, {})


def test_scoped_env_vars() -> None:
    def check_scoped_spam(scope, expected_val, env):
        val = _parse(env=env).for_scope(scope).spam
        assert expected_val == val

    check_scoped_spam("simple", "value", {"PANTS_SIMPLE_SPAM": "value"})
    check_scoped_spam("simple-dashed", "value", {"PANTS_SIMPLE_DASHED_SPAM": "value"})
    check_scoped_spam("scoped.a.bit", "value", {"PANTS_SCOPED_A_BIT_SPAM": "value"})
    check_scoped_spam("scoped.and-dashed", "value", {"PANTS_SCOPED_AND_DASHED_SPAM": "value"})


def test_enum_option_type_parse_error() -> None:
    with pytest.raises(ParseError) as exc:
        options = _parse(flags="enum-opt --some-enum=invalid-value")
        options.for_scope("enum-opt")

    assert (
        "Invalid choice 'invalid-value'."
        + " Choose from: a-value, another-value, yet-another, one-more"
    ) in str(exc.value)


def test_non_enum_option_type_parse_error() -> None:
    with pytest.raises(ParseError) as exc:
        options = _parse(flags="--num=not-a-number")
        options.for_global_scope()

    assert (
        "Error applying type 'int' to option value 'not-a-number': invalid literal for int()"
    ) in str(exc.value)


def test_mutually_exclusive_options() -> None:
    """Ensure error is raised when mutual exclusive options are given together."""

    def assert_mutually_exclusive_raised(
        *,
        flags: str,
        scope: str | None = None,
        env: dict[str, str] | None = None,
        config: dict[str, dict[str, str]] | None = None,
    ) -> None:
        with pytest.raises(MutuallyExclusiveOptionError):
            options = _parse(flags=flags, env=env, config=config)
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
    assert_mutually_exclusive_raised(flags="stale --crufty-new=foo --crufty-old=bar", scope="stale")

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
        options = _parse(flags=flags).for_global_scope()
        assert getattr(options, option) == expected

    assert_option_set("--mutex-foo=orz", "mutex_foo", "orz")
    assert_option_set("--mutex-foo=orz", "mutex_bar", None)
    assert_option_set("--mutex-foo=orz", "mutex_baz", None)
    assert_option_set("--mutex-bar=orz", "mutex_bar", "orz")


def test_complete_scopes() -> None:
    class OptCls:
        deprecated_options_scope = "deprecated"

    assert {ScopeInfo("foo"), ScopeInfo("bar")} == set(
        Options.complete_scopes([ScopeInfo("foo"), ScopeInfo("bar")])
    )

    assert {ScopeInfo("foo"), ScopeInfo("bar", OptCls), ScopeInfo("deprecated", OptCls)} == set(
        Options.complete_scopes([ScopeInfo("foo"), ScopeInfo("bar", OptCls)])
    )

    with pytest.raises(Options.DuplicateScopeError):
        Options.complete_scopes([ScopeInfo("foo"), ScopeInfo("bar"), ScopeInfo("foo")])


def test_get_fingerprintable_for_scope() -> None:
    options = _parse(
        flags='--store-true-flag --num=88 compile --modifycompile="blah blah blah" '
        '--modifylogs="durrrr" -- -d -v'
    )

    # NB: Passthrough args end up on our `--modifypassthrough` arg.
    pairs = options.get_fingerprintable_for_scope("compile")
    assert [
        ("modifycompile", str, "blah blah blah"),
        ("modifypassthrough", str, ["-d", "-v"]),
    ] == pairs


def test_fingerprintable() -> None:
    options = _parse(
        flags="--implicitly-fingerprinted=shall_be_fingerprinted"
        + " --explicitly-fingerprinted=also_shall_be_fingerprinted"
        + " --explicitly-not-fingerprinted=shant_be_fingerprinted"
    )
    pairs = options.get_fingerprintable_for_scope(GLOBAL_SCOPE)
    assert ("implicitly_fingerprinted", str, "shall_be_fingerprinted") in pairs
    assert ("explicitly_fingerprinted", str, "also_shall_be_fingerprinted") in pairs
    assert not any(value == "shant_be_fingerprinted" for _, _, value in pairs)


def test_fingerprintable_daemon_only() -> None:
    options = _parse(
        flags="--explicitly-daemoned=shall_be_fingerprinted"
        + " --explicitly-not-daemoned=shant_be_fingerprinted"
        + " --implicitly-not-daemoned=also_shant_be_fingerprinted"
    )
    pairs = options.get_fingerprintable_for_scope(GLOBAL_SCOPE, daemon_only=True)
    assert [("explicitly_daemoned", str, "shall_be_fingerprinted")] == pairs


def assert_fromfile(parse_func, expected_append=None, append_contents=None):
    def _do_assert_fromfile(dest, expected, contents, passthru_flags=""):
        with temporary_file(binary_mode=False) as fp:
            fp.write(contents)
            fp.close()
            options = parse_func(dest, fp.name, passthru_flags)
            assert expected == options.for_scope("fromfile")[dest]

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
             '1',
             '2']
            """
        ),
    )
    _do_assert_fromfile(
        dest="passthru_listvalue",
        expected=["a", "1", "2", "bob", "@jake"],
        contents=dedent(
            """
            ['a',
             '1',
             '2']
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


def test_fromfile_flags() -> None:
    def parse_func(dest, fromfile, passthru_flags):
        return _parse(flags=f"fromfile --{dest.replace('_', '-')}=@{fromfile} -- {passthru_flags}")

    # You can only append a single item at a time with append flags, ie: we don't override the
    # default list like we do with env of config.  As such, send in a single append value here
    # instead of a whole default list as in `test_fromfile_config` and `test_fromfile_env`.
    assert_fromfile(parse_func, expected_append=[42], append_contents="42")


def test_fromfile_config() -> None:
    def parse_func(dest, fromfile, passthru_flags):
        return _parse(
            flags=f"fromfile -- {passthru_flags}", config={"fromfile": {dest: f"@{fromfile}"}}
        )

    assert_fromfile(parse_func)


def test_fromfile_env() -> None:
    def parse_func(dest, fromfile, passthru_flags):
        return _parse(
            flags=f"fromfile -- {passthru_flags}",
            env={f"PANTS_FROMFILE_{dest.upper()}": f"@{fromfile}"},
        )

    assert_fromfile(parse_func)


def test_fromfile_json() -> None:
    val = {"a": {"b": 1}, "c": [2, 3]}
    with temporary_file(suffix=".json", binary_mode=False) as fp:
        json.dump(val, fp)
        fp.close()
        options = _parse(flags=f"fromfile --{'dictvalue'}=@{fp.name}")
        assert val == options.for_scope("fromfile")["dictvalue"]


def test_fromfile_yaml() -> None:
    val = {"a": {"b": 1}, "c": [2, 3]}
    with temporary_file(suffix=".yaml", binary_mode=False) as fp:
        yaml.safe_dump(val, fp)
        fp.close()
        options = _parse(flags=f"fromfile --{'dictvalue'}=@{fp.name}")
        assert val == options.for_scope("fromfile")["dictvalue"]


def test_fromfile_yaml_trailing_newlines_matter() -> None:
    with temporary_file(suffix=".yaml", binary_mode=False) as fp:
        fp.write(
            dedent(
                """\
                    a: |+
                      multiline
                """
            )
        )
        fp.close()
        options = _parse(flags=f"fromfile --{'dictvalue'}=@{fp.name}")
        assert {"a": "multiline\n"} == options.for_scope("fromfile")["dictvalue"]


def test_fromfile_relative_to_build_root() -> None:
    with temporary_dir(root_dir=get_buildroot()) as tempdir:
        dirname = tempdir.split("/")[-1]
        tempfile = Path(tempdir, "config")
        tempfile.write_text("{'a': 'multiline\\n'}")
        with pushd(tempdir):
            options = _parse(flags=f"fromfile --dictvalue=@{dirname}/config")
            assert {"a": "multiline\n"} == options.for_scope("fromfile")["dictvalue"]


def test_fromfile_error() -> None:
    options = _parse(flags="fromfile --string=@/does/not/exist")
    with pytest.raises(FromfileError):
        options.for_scope("fromfile")


def test_fromfile_escape() -> None:
    options = _parse(flags=r"fromfile --string=@@/does/not/exist")
    assert "@/does/not/exist" == options.for_scope("fromfile").string


def test_fromfile_config_with_optional() -> None:
    def parse_func(dest, fromfile, passthru_flags):
        return _parse(
            flags=f"fromfile -- {passthru_flags}",
            config={"fromfile": {dest: f"@?{fromfile}"}},
        )

    assert_fromfile(parse_func)


def test_fromfile_with_optional_string() -> None:
    options = _parse(flags=r"fromfile --string=@?/does/not/exist")
    assert options.for_scope("fromfile").string is None


def test_fromfile_with_optional_dict() -> None:
    options = _parse(flags=r"fromfile --dictvalue=@?/does/not/exist")
    assert options.for_scope("fromfile").dictvalue == {}


def test_fromfile_with_optional_list() -> None:
    options = _parse(flags=r"fromfile --listvalue=@?/does/not/exist")
    assert options.for_scope("fromfile").listvalue == []


def test_ranked_value_equality() -> None:
    none = RankedValue(Rank.NONE, None)
    some = RankedValue(Rank.HARDCODED, "some")
    assert RankedValue(Rank.NONE, None) == none
    assert RankedValue(Rank.HARDCODED, "some") == some
    assert some != none
    assert some == RankedValue(Rank.HARDCODED, "some")
    assert some != RankedValue(Rank.HARDCODED, "few")
    assert some != RankedValue(Rank.CONFIG, "some")


def test_pants_global_with_default() -> None:
    """This test makes sure values under [DEFAULT] still gets read."""
    # This cast shouldn't be necessary - likely a bug in MyPy. Once this gets fixed, MyPy will
    # tell us that we can remove the cast.
    config = cast(
        Dict[str, Dict[str, Any]],
        {"DEFAULT": {"num": "99"}, "GLOBAL": {"store_true_flag": True}},
    )
    global_options = _parse(config=config).for_global_scope()
    assert 99 == global_options.num
    assert global_options.store_true_flag


def test_double_registration() -> None:
    options = Options.create(
        env={},
        config=_create_config(),
        known_scope_infos=_known_scope_infos,
        args=shlex.split("./pants"),
    )
    options.register(GLOBAL_SCOPE, "--foo-bar")
    with pytest.raises(OptionAlreadyRegistered):
        options.register(GLOBAL_SCOPE, "--foo-bar")


def test_enum_serializability() -> None:
    # We serialize options to JSON e.g., when uploading stats.
    # This test spot-checks that enum types can be serialized.
    options = _parse(flags="enum-opt --some-enum=another-value")
    json.dumps({"foo": [options.for_scope("enum-opt").as_dict()]}, cls=OptionEncoder)


def test_list_of_enum_single_value() -> None:
    options = _parse(flags="other-enum-scope --some-list-enum=another-value")
    assert [SomeEnumOption.another_value] == options.for_scope("other-enum-scope").some_list_enum


def test_list_of_enum_default_value() -> None:
    options = _parse(flags="other-enum-scope --some-list-enum-with-default=another-value")
    assert [
        SomeEnumOption.yet_another,
        SomeEnumOption.another_value,
    ] == options.for_scope("other-enum-scope").some_list_enum_with_default
    options = _parse()
    assert [SomeEnumOption.yet_another] == options.for_scope(
        "other-enum-scope"
    ).some_list_enum_with_default


def test_list_of_enum_from_config() -> None:
    options = _parse(config={"other-enum-scope": {"some_list_enum": "['one-more', 'a-value']"}})
    assert [SomeEnumOption.one_more, SomeEnumOption.a_value] == options.for_scope(
        "other-enum-scope"
    ).some_list_enum


def test_list_of_enum_duplicates() -> None:
    options = _parse(
        flags="other-enum-scope --some-list-enum=\"['another-value', 'one-more', 'another-value']\""
    )
    with pytest.raises(ParseError, match="Duplicate enum values specified in list"):
        options.for_scope("other-enum-scope")


def test_list_of_enum_invalid_value() -> None:
    options = _parse(flags="other-enum-scope --some-list-enum=\"['another-value', 'not-a-value']\"")
    with pytest.raises(ParseError, match="Error computing value for --some-list-enum"):
        options.for_scope("other-enum-scope")


def test_list_of_enum_set_single_value() -> None:
    options = _parse(flags="other-enum-scope --some-list-enum-with-default=\"['another-value']\"")
    assert [SomeEnumOption.another_value] == options.for_scope(
        "other-enum-scope"
    ).some_list_enum_with_default


def test_list_of_enum_append() -> None:
    options = _parse(flags="other-enum-scope --some-list-enum-with-default=\"+['another-value']\"")
    assert [
        SomeEnumOption.yet_another,
        SomeEnumOption.another_value,
    ] == options.for_scope("other-enum-scope").some_list_enum_with_default


def test_list_of_enum_remove() -> None:
    options = _parse(flags="other-enum-scope --some-list-enum-with-default=\"-['yet-another']\"")
    assert [] == options.for_scope("other-enum-scope").some_list_enum_with_default
