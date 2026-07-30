# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import threading

import pytest

from pants.engine.unions import UnionMembership, UnionRule
from pants.option.errors import OptionsError
from pants.option.option_types import BoolOption, StrListOption
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

    check_false("pants")
    check_false("Foo")
    check_false("fOo")
    check_false("foo.bar")
    check_false("foo..bar")
    check_false(".foo.bar")
    check_false("foo.bar.")
    check_false("foo--bar")
    check_false("foo-bar-")


def test_register_options_blessed(caplog) -> None:
    class GoodToGo(Subsystem):
        options_scope = "good-to-go"

    options = Options.create(
        args=["./pants"],
        env={},
        config_sources=[],
        known_scope_infos=[GoodToGo.get_scope_info()],
    )
    GoodToGo.register_options_on_scope(options, UnionMembership.empty())

    assert not caplog.records, "The current blessed means of registering options should never warn."


def test_register_plugin_options() -> None:
    class Electrical(Subsystem):
        options_scope = "electrical"

    class LampPlugin:
        is_on = BoolOption(default=False, help="Luxo Jr.")

    class Blender:
        contents = StrListOption(help="brrrrr")

    options = Options.create(
        args=["./pants"],
        env={},
        config_sources=[],
        known_scope_infos=[Electrical.get_scope_info()],
    )
    Electrical.register_options_on_scope(
        options,
        UnionMembership.from_rules(
            {
                UnionRule(Electrical.PluginOption, LampPlugin),
                UnionRule(Electrical.PluginOption, Blender),
            }
        ),
    )

    electrical_subsystem = Electrical(options.for_scope(Electrical.options_scope))
    assert not electrical_subsystem.options.is_on
    assert electrical_subsystem.options.contents == []


def test_rules_memo_is_published_once_under_concurrency() -> None:
    class Concurrent(Subsystem):
        options_scope = "concurrent"
        help = "Racing rules()."

    entered = threading.Event()
    resume = threading.Event()
    original = Concurrent._construct_subsystem_rule
    gated: list[threading.Thread] = []
    gated_rules: list[object] = []

    def gated_construct_subsystem_rule():
        if threading.current_thread() is gated[0]:
            entered.set()
            assert resume.wait(timeout=60)
        return original()

    Concurrent._construct_subsystem_rule = gated_construct_subsystem_rule  # type: ignore[method-assign]
    gated.append(threading.Thread(target=lambda: gated_rules.append(Concurrent.rules())))

    try:
        gated[0].start()
        assert entered.wait(timeout=60)
        # The gated thread is parked past its `_rules is None` check, so this call races it.
        published = Concurrent.rules()
    finally:
        resume.set()
        gated[0].join(timeout=60)

    assert gated_rules[0] is published
    assert Concurrent.rules() is published
