# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

from pants.option.errors import OptionsError
from pants.option.option_value_container import OptionValueContainer
from pants.option.subsystem import Option, Subsystem


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


def test_option() -> None:
    # NB: Option is only valid on Subsystem subclasses, but we won't use any Subsystem machinery for
    # this test.
    class Ghostbusters(Subsystem):
        def __init__(self):
            self.options = SimpleNamespace()
            self.options.peter_venkman = "He slimed me!"
            self.options.egon_spengler = 5000
            self.options.raymond_stantz = ["HOLDIN!", "SMOKIN!", "READY!"]

        cast1 = Option[str]("-p", "--peter-venkman", actor_name="Bill Murray")
        cast2 = Option[int]("--egon-spengler", actor_name="Harold Ramis")
        cast3 = Option["tuple[str, ...]"]("--raymond-stantz", converter=tuple)

    assert Ghostbusters.cast1.args == ("-p", "--peter-venkman")
    assert Ghostbusters.cast1.kwargs == dict(actor_name="Bill Murray")
    assert Ghostbusters.cast2.args == ("--egon-spengler",)
    assert Ghostbusters.cast2.kwargs == dict(actor_name="Harold Ramis")

    who_im_gonna_call = Ghostbusters()
    assert who_im_gonna_call.cast1 == "He slimed me!"
    assert who_im_gonna_call.cast2 == 5000
    assert who_im_gonna_call.cast3 == ("HOLDIN!", "SMOKIN!", "READY!")

    # This "tests" (through mypy) that the property types are what we expect
    s1: str = who_im_gonna_call.cast1  # noqa: F841
    int1: int = who_im_gonna_call.cast2  # noqa: F841
    tuple1: tuple[str, ...] = who_im_gonna_call.cast3  # noqa: F841


def test_option_in_subsystem() -> None:
    class Ghostbusters(Subsystem):
        options_scope = "ghostbusters"

        cast1 = Option[str]("-p", "--peter-venkman", actor_name="Bill Murray")
        cast2 = Option[int]("--egon-spengler", actor_name="Harold Ramis")
        cast3 = Option["tuple[str, ...]"](
            "--raymond-stantz", actor_name="Dan Aykroyd", converter=tuple
        )

    register = Mock()
    Ghostbusters.register_options(register)

    register.assert_has_calls(
        [
            call("-p", "--peter-venkman", actor_name="Bill Murray"),
            call("--egon-spengler", actor_name="Harold Ramis"),
            call("--raymond-stantz", actor_name="Dan Aykroyd"),
        ]
    )
