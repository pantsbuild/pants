# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.option.alias import OptionAlias


def test_maybe_nothing() -> None:
    alias = OptionAlias()
    assert alias.maybe_expand("arg") is None


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
    option_alias = OptionAlias.from_dict(
        {
            "alias": alias,
        }
    )
    assert option_alias.maybe_expand("alias") == expanded


def test_expand_args() -> None:
    option_alias = OptionAlias.from_dict(
        {
            "alias": "--flag value",
        }
    )
    args = ("some", "alias", "here")
    expanded = ("some", "--flag", "value", "here")
    assert option_alias.expand_args(args) == expanded


def test_no_expand_when_no_aliases() -> None:
    args = ("./pants",)
    option_alias = OptionAlias()
    assert option_alias.expand_args(args) is args
