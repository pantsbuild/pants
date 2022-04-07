# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.option.config import Config
from pants.option.errors import OptionsError
from pants.option.option_value_container import OptionValueContainer
from pants.option.options import Options
from pants.option.subsystem import Subsystem


def test_scope_existence() -> None:
    class NoScope(Subsystem):
        pass

    with pytest.raises(OptionsError) as excinfo:
        NoScope.get_scope_info()
    assert "NoScope must set options_scope" in str(excinfo.value)

    with pytest.raises(OptionsError) as excinfo:
        NoScope(OptionValueContainer({}))
    assert "NoScope must set options_scope" in str(excinfo.value)

    class StringScope(Subsystem):
        options_scope = "good"

    assert "good" == StringScope.options_scope

    class Intermediate(Subsystem):
        pass

    class Indirect(Intermediate):
        options_scope = "good"

    assert "good" == Indirect.options_scope


def test_is_valid_scope_name() -> None:
    def check_true(s: str) -> None:
        assert Subsystem.is_valid_scope_name(s)

    def check_false(s: str) -> None:
        assert not Subsystem.is_valid_scope_name(s)

    check_true("")
    check_true("foo")
    check_true("foo-bar0")
    check_true("foo-bar0-1ba22z")
    check_true("foo_bar")

    check_false("Foo")
    check_false("fOo")
    check_false("foo.bar")
    check_false("foo..bar")
    check_false(".foo.bar")
    check_false("foo.bar.")
    check_false("foo--bar")
    check_false("foo-bar-")


def test_deprecated_register_options(caplog) -> None:
    class GoodToGo(Subsystem):
        options_scope = "good-to-go"

    options = Options.create(
        env={},
        config=Config.load([]),
        known_scope_infos=[GoodToGo.get_scope_info()],
        args=["./pants"],
        bootstrap_option_values=None,
    )
    GoodToGo.register_options_on_scope(options)

    assert not caplog.records

    class OldAndDusty(Subsystem):
        options_scope = "good-to-go"

        @classmethod
        def register_options(cls, register):
            return super().register_options(register)

    options = Options.create(
        env={},
        config=Config.load([]),
        known_scope_infos=[OldAndDusty.get_scope_info()],
        args=["./pants"],
        bootstrap_option_values=None,
    )
    OldAndDusty.register_options_on_scope(options)

    assert (
        "DEPRECATED: pants.option.subsystem.register_options() is scheduled to be removed"
        in caplog.text
    )
