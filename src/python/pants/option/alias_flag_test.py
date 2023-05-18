# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import ContextManager

import pytest

from pants.option.alias import CliAliasCycleError, CliAliasFlag, CliAliasInvalidError
from pants.testutil.pytest_util import no_exception
from pants.util.frozendict import FrozenDict


def test_maybe_nothing() -> None:
    cli_alias = CliAliasFlag()
    assert cli_alias.maybe_expand("arg") is None


@pytest.mark.parametrize(
    "alias, expanded",
    [
        ("--arg1", ("--arg1",)),
        ("--arg1 --arg2", ("--arg1", "--arg2")),
        ("--arg=value --option", ("--arg=value", "--option")),
        ("--arg=value --option=flag", ("--arg=value", "--option=flag")),
    ],
)
def test_maybe_expand_alias(alias: str, expanded: tuple[str, ...] | None) -> None:
    cli_alias = CliAliasFlag.from_dict(
        {
            "alias": alias,
        }
    )
    assert cli_alias.maybe_expand("--alias") == expanded


@pytest.mark.parametrize(
    "args, expanded",
    [
        (
            ("some", "--alias", "goal", "target"),
            ("some", "--flag", "goal", "target"),
        ),
        (
            # Don't touch pass through args.
            ("some", "--", "--alias", "target"),
            ("some", "--", "--alias", "target"),
        ),
    ],
)
def test_expand_args(args: tuple[str, ...], expanded: tuple[str, ...]) -> None:
    cli_alias = CliAliasFlag.from_dict(
        {
            "alias": "--flag",
        }
    )
    assert cli_alias.expand_args(args) == expanded


def test_no_expand_when_no_aliases() -> None:
    args = ("./pants",)
    cli_alias = CliAliasFlag()
    assert cli_alias.expand_args(args) is args


@pytest.mark.parametrize(
    "alias, definitions",
    [
        (
            {
                "basic": "--foobar",
                "nested": "--option=advanced",
            },
            {
                "--basic": ("--foobar",),
                "--nested": ("--option=advanced",),
            },
        ),
        (
            {
                "multi-nested": "--nested",
                "basic": "--goal",
                "nested": "--option=advanced --basic",
            },
            {
                "--multi-nested": ("--option=advanced", "--goal"),
                "--basic": ("--goal",),
                "--nested": ("--option=advanced", "--goal"),
            },
        ),
        (
            {
                "cycle": "--other-alias",
                "other-alias": "--cycle",
            },
            pytest.raises(
                CliAliasCycleError,
                match=(
                    r"CLI alias cycle detected in `\[cli\]\.alias_flags` option:\n"
                    + r"--other-alias -> --cycle -> --other-alias"
                ),
            ),
        ),
    ],
)
def test_nested_alias(alias, definitions: dict | ContextManager) -> None:
    expect: ContextManager = no_exception() if isinstance(definitions, dict) else definitions
    with expect:
        cli_alias = CliAliasFlag.from_dict(alias)
        if isinstance(definitions, dict):
            assert cli_alias.definitions == FrozenDict(definitions)


@pytest.mark.parametrize(
    "alias",
    [
        # Check that we do not allow any alias that may resemble a valid option/spec.
        "dir/spec",
        "file.name",
        "target:name",
        "-o",
        "--o",
        "-option",
        "--option",
    ],
)
def test_invalid_alias_name(alias: str) -> None:
    with pytest.raises(
        CliAliasInvalidError,
        match=(f"Invalid alias in `\\[cli\\]\\.alias_flags` option: '--{alias}'\\."),
    ):
        CliAliasFlag.from_dict({alias: ""})


@pytest.mark.parametrize(
    "arg, definitions",
    [
        ("goal", {"alias": "--foobar goal"}),
        ("goal", {"alias": "--foobar=test goal"}),
        ("asd", {"alias": "-x --foobar asd"}),
        ("goal", {"alias": "--foobar goal --baz"}),
    ],
)
def test_invalid_alias_value_(arg: str, definitions: dict[str, str]) -> None:
    with pytest.raises(
        CliAliasInvalidError,
        match=(
            rf"Invalid expansion in `\[cli\].alias_flags` option: {arg!r}. All expanded values must be flags."
        ),
    ):
        CliAliasFlag.from_dict(definitions)


def test_banned_alias_names() -> None:
    cli_alias = CliAliasFlag.from_dict({"print-stacktrace": "-ltrace --keep-sandboxes=always "})
    with pytest.raises(
        CliAliasInvalidError,
        match=(
            r"Invalid alias in `\[cli\].alias_flags` option: '--print-stacktrace'. This is already a registered flag in the 'global' scope."
        ),
    ):
        cli_alias.check_name_conflicts({"global": ["--print-stacktrace"]})
