# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.option.alias import CliAlias


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


def test_no_expand_when_no_aliases() -> None:
    args = ("./pants",)
    cli_alias = CliAlias()
    assert cli_alias.expand_args(args) is args
