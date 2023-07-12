# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import ContextManager

import pytest

from pants.option.alias import CliAlias, CliAliasCycleError, CliAliasInvalidError
from pants.option.scope import ScopeInfo
from pants.testutil.pytest_util import no_exception
from pants.util.frozendict import FrozenDict


def test_maybe_nothing() -> None:
    cli_alias = CliAlias()
    assert cli_alias.maybe_expand("arg") is None


@pytest.mark.parametrize(
    "alias, expanded",
    [
        ("--arg1", ("--arg1",)),
        ("--arg1 --arg2", ("--arg1", "--arg2")),
        ("--arg=value --option", ("--arg=value", "--option")),
        ("--arg=value --option flag", ("--arg=value", "--option", "flag")),
        ("--arg 'quoted value'", ("--arg", "quoted value")),
    ],
)
def test_maybe_expand_alias(alias: str, expanded: tuple[str, ...] | None) -> None:
    cli_alias = CliAlias.from_dict(
        {
            "alias": alias,
        }
    )
    assert cli_alias.maybe_expand("alias") == expanded

    cli_alias = CliAlias.from_dict(
        {
            "--alias": alias,
        }
    )
    assert cli_alias.maybe_expand("--alias") == expanded


@pytest.mark.parametrize(
    "args, expanded",
    [
        (
            ("some", "alias", "target"),
            ("some", "--flag", "goal", "target"),
        ),
        (
            # Don't touch pass through args.
            ("some", "--", "alias", "target"),
            ("some", "--", "alias", "target"),
        ),
    ],
)
def test_expand_args(args: tuple[str, ...], expanded: tuple[str, ...]) -> None:
    cli_alias = CliAlias.from_dict(
        {
            "alias": "--flag goal",
        }
    )
    assert cli_alias.expand_args(args) == expanded


@pytest.mark.parametrize(
    "args, expanded",
    [
        (
            ("some", "--alias", "target"),
            ("some", "--flag", "goal", "target"),
        ),
        (
            # Don't touch pass through args.
            ("some", "--", "--alias", "target"),
            ("some", "--", "--alias", "target"),
        ),
    ],
)
def test_expand_args_flag(args: tuple[str, ...], expanded: tuple[str, ...]) -> None:
    cli_alias = CliAlias.from_dict(
        {
            "--alias": "--flag goal",
        }
    )
    assert cli_alias.expand_args(args) == expanded


def test_no_expand_when_no_aliases() -> None:
    args = ("./pants",)
    cli_alias = CliAlias()
    assert cli_alias.expand_args(args) is args


@pytest.mark.parametrize(
    "alias, definitions",
    [
        (
            {
                "basic": "goal",
                "nested": "--option=advanced basic",
            },
            {
                "basic": ("goal",),
                "nested": (
                    "--option=advanced",
                    "goal",
                ),
            },
        ),
        (
            {
                "multi-nested": "deep nested",
                "basic": "goal",
                "nested": "--option=advanced basic",
            },
            {
                "multi-nested": ("deep", "--option=advanced", "goal"),
                "basic": ("goal",),
                "nested": (
                    "--option=advanced",
                    "goal",
                ),
            },
        ),
        (
            {
                "cycle": "other-alias",
                "other-alias": "cycle",
            },
            pytest.raises(
                CliAliasCycleError,
                match=(
                    r"CLI alias cycle detected in `\[cli\]\.alias` option:\n"
                    + r"other-alias -> cycle -> other-alias"
                ),
            ),
        ),
        (
            {
                "cycle": "--other-alias",
                "--other-alias": "cycle",
            },
            pytest.raises(
                CliAliasCycleError,
                match=(
                    r"CLI alias cycle detected in `\[cli\]\.alias` option:\n"
                    + r"--other-alias -> cycle -> --other-alias"
                ),
            ),
        ),
        (
            {
                "--cycle": "--other-alias",
                "--other-alias": "--cycle",
            },
            pytest.raises(
                CliAliasCycleError,
                match=(
                    r"CLI alias cycle detected in `\[cli\]\.alias` option:\n"
                    + r"--other-alias -> --cycle -> --other-alias"
                ),
            ),
        ),
    ],
)
def test_nested_alias(alias, definitions: dict | ContextManager) -> None:
    expect: ContextManager = no_exception() if isinstance(definitions, dict) else definitions
    with expect:
        cli_alias = CliAlias.from_dict(alias)
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
        "-option",
    ],
)
def test_invalid_alias_name(alias: str) -> None:
    with pytest.raises(
        CliAliasInvalidError, match=(f"Invalid alias in `\\[cli\\]\\.alias` option: {alias!r}\\.")
    ):
        CliAlias.from_dict({alias: ""})


def test_banned_alias_names() -> None:
    cli_alias = CliAlias.from_dict({"fmt": "--cleverness format"})
    with pytest.raises(
        CliAliasInvalidError,
        match=(
            r"Invalid alias in `\[cli\]\.alias` option: 'fmt'\. This is already a registered goal\."
        ),
    ):
        cli_alias.check_name_conflicts({"fmt": ScopeInfo("fmt", is_goal=True)}, {})


@pytest.mark.parametrize(
    "alias, info, expected",
    [
        (
            {"--keep-sandboxes": "--foobar"},
            {"": "--keep-sandboxes"},
            pytest.raises(
                CliAliasInvalidError,
                match=(
                    r"Invalid flag-like alias in `\[cli\]\.alias` option: '--keep-sandboxes'\. This is already a registered flag in the 'global' scope\."
                ),
            ),
        ),
        (
            {"--changed-since": "--foobar"},
            {"changed": "--changed-since"},
            pytest.raises(
                CliAliasInvalidError,
                match=(
                    r"Invalid flag-like alias in `\[cli\]\.alias` option: '--changed-since'\. This is already a registered flag in the 'changed' scope\."
                ),
            ),
        ),
    ],
)
def test_banned_alias_flag_names(alias, info, expected) -> None:
    cli_alias = CliAlias.from_dict(alias)
    with expected:
        cli_alias.check_name_conflicts({}, info)
