# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

from pants.option.custom_types import shell_str
from pants.option.errors import OptionsError
from pants.option.option_value_container import OptionValueContainer
from pants.option.subsystem import ArgsOption, BoolOption, IntOption, Option, StrOption, Subsystem


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
    var1: str = who_im_gonna_call.cast1  # noqa: F841
    var2: int = who_im_gonna_call.cast2  # noqa: F841
    var3: tuple[str, ...] = who_im_gonna_call.cast3  # noqa: F841


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
        ],
        any_order=True,
    )


def test_option_typeclasses() -> None:
    # NB: Option is only valid on Subsystem subclasses, but we won't use any Subsystem machinery for
    # this test.
    class SubmarineSystems(Subsystem):
        def __init__(self):
            self.options = SimpleNamespace()
            self.options.propulsion = False
            self.options.hydraulic = ""
            self.options.radar = 0
            self.options.args = ["looky"]

        bool_opt = BoolOption("--propulsion", help="propulsion")
        str_opt = StrOption("--hydraulic", help="hydraulic")
        int_opt = IntOption("--radar", help="radar")
        args_opt = ArgsOption(help="periscope")

    register = Mock()
    SubmarineSystems.register_options(register)

    register.assert_has_calls(
        [
            call("--propulsion", type=bool, help="propulsion"),
            call("--hydraulic", type=str, help="hydraulic"),
            call("--radar", type=int, help="radar"),
            call("--args", type=list, member_type=shell_str, passthrough=True, help="periscope"),
        ],
        any_order=True,
    )

    systems = SubmarineSystems()
    assert not systems.bool_opt
    assert systems.str_opt == ""
    assert systems.int_opt == 0
    assert systems.args_opt == ("looky",)

    # This "tests" (through mypy) that the property types are what we expect
    var1: bool = systems.bool_opt  # noqa: F841
    var2: str = systems.str_opt  # noqa: F841
    var3: int = systems.int_opt  # noqa: F841
    var4: tuple[str, ...] = systems.args_opt  # noqa: F841
