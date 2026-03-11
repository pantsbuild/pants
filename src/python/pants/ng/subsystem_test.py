# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# mypy: disable-error-code=empty-body

import re
import textwrap

import pytest

from pants.engine.internals.native_engine import PyConfigSource, PyNgOptionsReader
from pants.ng.subsystem import OptionDescriptor, SubsystemNg, option
from pants.util.frozendict import FrozenDict


def test_collect_options() -> None:
    class NoOptionsScope(SubsystemNg):
        pass

    with pytest.raises(
        ValueError,
        match="Subsystem class NoOptionsScope must set the options_scope classvar.",
    ):
        NoOptionsScope._initialize_()

    class NoHelp(SubsystemNg):
        options_scope = "no_help"

    with pytest.raises(
        ValueError,
        match="Subsystem class NoHelp must set the help classvar.",
    ):
        NoHelp._initialize_()

    class Empty(SubsystemNg):
        options_scope = "empty"
        help = "empty help"

        def not_an_option(self) -> str:
            return ""

    assert getattr(Empty, "_option_descriptors_", None) is None
    Empty._initialize_()
    assert getattr(Empty, "_option_descriptors_") == tuple()

    class SomeOptions(SubsystemNg):
        options_scope = "some_options"
        help = "some_options help"

        @option(help="foo help")
        def foo(self) -> str: ...

        @option(default=42, help="bar help")
        def bar(self) -> int: ...

        def not_an_option(self) -> str:
            return ""

        @option(help="baz help")
        def baz(self) -> bool: ...

        @option(default=3.14, help="qux help")
        def qux(self) -> float: ...

        @option(help="str tuple help")
        def str_tuple(self) -> tuple[str, ...]: ...

        @option(help="int tuple help", default=(0, 1, 2))
        def int_tuple(self) -> tuple[int, ...]: ...

        @option(help="dict help")
        def dict(self) -> FrozenDict[str, str]: ...

    assert getattr(SomeOptions, "_option_descriptors_", None) is None
    SomeOptions._initialize_()
    assert getattr(SomeOptions, "_option_descriptors_") == (
        OptionDescriptor("foo", str, None, "foo help"),
        OptionDescriptor("bar", int, 42, "bar help"),
        OptionDescriptor("baz", bool, None, "baz help"),
        OptionDescriptor("qux", float, 3.14, "qux help"),
        OptionDescriptor("str_tuple", tuple[str, ...], None, "str tuple help"),
        OptionDescriptor("int_tuple", tuple[int, ...], (0, 1, 2), "int tuple help"),
        OptionDescriptor("dict", FrozenDict[str, str], None, "dict help"),
    )

    class NotAMethod(SubsystemNg):
        options_scope = "not_a_method"
        help = "not_a_method help"

        @option(help="not a method")
        class Inner:
            pass

    with pytest.raises(
        ValueError,
        match="The @option decorator expects to be placed on a no-arg instance method, but "
        "NotAMethod.Inner does not have this signature.",
    ):
        NotAMethod._initialize_()

    class NoSelfArg(SubsystemNg):
        options_scope = "no_self_arg"
        help = "no_self_arg help"

        @option(help="no self arg")
        def no_self_arg() -> str: ...

    with pytest.raises(
        ValueError,
        match="The @option decorator expects to be placed on a no-arg instance method, but "
        "NoSelfArg.no_self_arg does not have this signature.",
    ):
        NoSelfArg._initialize_()

    class BadDefault(SubsystemNg):
        options_scope = "bad_default"
        help = "bad_default help"

        @option(default=42, help="bad default")
        def bad_default(self) -> str: ...

    with pytest.raises(
        ValueError,
        match=re.escape(
            r"The default for option BadDefault.bad_default must be of type str (or None)."
        ),
    ):
        BadDefault._initialize_()

    class BadTupleDefault(SubsystemNg):
        options_scope = "bad_tuple_default"
        help = "bad_tuple_default help"

        @option(default=(0, "1", 2), help="bad tuple default")
        def bad_default(self) -> tuple[int, ...]: ...

    with pytest.raises(
        ValueError,
        match=re.escape(
            r"The default for option BadTupleDefault.bad_default must be of type tuple[int, ...] (or None)."
        ),
    ):
        BadTupleDefault._initialize_()


def test_option_value_getters_implicit_defaults(tmp_path) -> None:
    class Dummy(SubsystemNg):
        options_scope = "dummy"
        help = "dummy help"

        @option(help="bool help")
        def bool_opt(self) -> bool: ...

        @option(help="str help")
        def str_opt(self) -> str: ...

        @option(help="int help")
        def int_opt(self) -> int: ...

        @option(help="float help")
        def float_opt(self) -> float: ...

        @option(help="bool tuple help")
        def bool_tuple_opt(self) -> tuple[bool, ...]: ...

        @option(help="str tuple help")
        def str_tuple_opt(self) -> tuple[str, ...]: ...

        @option(help="int tuple help")
        def int_tuple_opt(self) -> tuple[int, ...]: ...

        @option(help="float tuple help")
        def float_tuple_opt(self) -> tuple[float, ...]: ...

        @option(help="frozendict help")
        def frozendict_opt(self) -> FrozenDict[str, str]: ...

    Dummy._initialize_()

    subsys = Dummy(
        PyNgOptionsReader(
            buildroot=tmp_path,
            flags={},
            env={},
            configs=[],
        )
    )

    assert not subsys.bool_opt
    assert subsys.str_opt is None
    assert subsys.int_opt is None
    assert subsys.float_opt is None
    assert subsys.bool_tuple_opt == tuple()
    assert subsys.str_tuple_opt == tuple()
    assert subsys.int_tuple_opt == tuple()
    assert subsys.float_tuple_opt == tuple()
    assert subsys.frozendict_opt == FrozenDict()


def test_option_value_getters_explicit_defaults(tmp_path) -> None:
    class Dummy(SubsystemNg):
        options_scope = "dummy"
        help = "dummy help"

        @option(default=True, help="bool help")
        def bool_opt(self) -> bool: ...

        @option(default="hello world", help="str help")
        def str_opt(self) -> str: ...

        @option(default=42, help="int help")
        def int_opt(self) -> int: ...

        @option(default=3.14, help="float help")
        def float_opt(self) -> float: ...

        @option(default=(True, False), help="bool tuple help")
        def bool_tuple_opt(self) -> tuple[bool, ...]: ...

        @option(default=("hello", "world"), help="str tuple help")
        def str_tuple_opt(self) -> tuple[str, ...]: ...

        @option(default=(0, 1, 2), help="int tuple help")
        def int_tuple_opt(self) -> tuple[int, ...]: ...

        @option(default=(0.1, 1.2, 2.3), help="float tuple help")
        def float_tuple_opt(self) -> tuple[float, ...]: ...

        @option(default=FrozenDict(foo="bar"), help="frozendict help")
        def frozendict_opt(self) -> FrozenDict[str, str]: ...

    Dummy._initialize_()

    subsys = Dummy(
        PyNgOptionsReader(
            buildroot=tmp_path,
            flags={},
            env={},
            configs=[],
        )
    )

    assert subsys.bool_opt
    assert subsys.str_opt == "hello world"
    assert subsys.int_opt == 42
    assert subsys.float_opt == 3.14
    assert subsys.bool_tuple_opt == (True, False)
    assert subsys.str_tuple_opt == ("hello", "world")
    assert subsys.int_tuple_opt == (0, 1, 2)
    assert subsys.float_tuple_opt == (0.1, 1.2, 2.3)
    assert subsys.frozendict_opt == FrozenDict(foo="bar")


def test_option_callable_args(tmp_path) -> None:
    class Dummy(SubsystemNg):
        options_scope = "dummy"
        help = "dummy help"

        _bool_opt_help = "bool help"

        @option(default=True, help=lambda cls: cls._bool_opt_help)
        def bool_opt(self) -> bool: ...

        _str_default = "hello world"

        @option(default=lambda cls: cls._str_default, help="str help")
        def str_opt(self) -> str: ...

    Dummy._initialize_()

    assert getattr(Dummy, "_option_descriptors_") == (
        OptionDescriptor("bool_opt", bool, True, "bool help"),
        OptionDescriptor("str_opt", str, "hello world", "str help"),
    )


def test_option_value_getters_from_options(tmp_path) -> None:
    class Dummy(SubsystemNg):
        options_scope = "dummy"
        help = "dummy help"

        @option(default=True, help="bool help")
        def bool_opt(self) -> bool: ...

        @option(help="str help")
        def str_opt(self) -> str: ...

        @option(default=42, help="int help")
        def int_opt(self) -> int: ...

        @option(help="float help")
        def float_opt(self) -> float: ...

        @option(help="bool tuple help")
        def bool_tuple_opt(self) -> tuple[bool, ...]: ...

        @option(help="str tuple help")
        def str_tuple_opt(self) -> tuple[str, ...]: ...

        @option(default=(0, 1, 2), help="int tuple help")
        def int_tuple_opt(self) -> tuple[int, ...]: ...

        @option(default=(1.2, 2.3), help="float tuple help")
        def float_tuple_opt(self) -> tuple[float, ...]: ...

        @option(default=FrozenDict(foo="bar"), help="frozendict help")
        def frozendict_opt(self) -> FrozenDict[str, str]: ...

    Dummy._initialize_()

    # Options parsing is comprehensively tested elswhere, so we just spot-check
    # the plumbing here.

    config = textwrap.dedent("""\
    [dummy]
    bool_opt = false
    str_opt = "hello world"
    int_opt = 53
    float_opt = 5.6
    bool_tuple_opt = [true, false]
    str_tuple_opt = ["hello", "world"]
    int_tuple_opt.add = [3, 4, 5]
    float_tuple_opt = []
    frozendict_opt.add = {baz="qux"}
    """)
    config_source = PyConfigSource("pantsng.toml", config.encode())

    subsys = Dummy(
        PyNgOptionsReader(
            buildroot=tmp_path,
            flags={},
            env={},
            configs=[config_source],
        )
    )

    assert not subsys.bool_opt
    assert subsys.str_opt == "hello world"
    assert subsys.int_opt == 53
    assert subsys.float_opt == 5.6
    assert subsys.bool_tuple_opt == (True, False)
    assert subsys.str_tuple_opt == ("hello", "world")
    assert subsys.int_tuple_opt == (0, 1, 2, 3, 4, 5)
    assert subsys.float_tuple_opt == tuple()
    assert subsys.frozendict_opt == FrozenDict(foo="bar", baz="qux")


def test_required_options(tmp_path) -> None:
    class Dummy1(SubsystemNg):
        options_scope = "dummy1"
        help = "dummy1 help"

        @option(required=True, help="bool help")
        def bool_opt(self) -> bool: ...

    Dummy1._initialize_()

    with pytest.raises(
        ValueError, match=re.escape(r"No value provided for required option [dummy1].bool_opt.")
    ):
        Dummy1(
            PyNgOptionsReader(
                buildroot=tmp_path,
                flags={},
                env={},
                configs=[],
            )
        )

    class Dummy2(SubsystemNg):
        options_scope = "dummy2"
        help = "dummy2 help"

        @option(required=True, help="str tuple help")
        def str_tuple_opt(self) -> tuple[str, ...]: ...

    Dummy2._initialize_()

    with pytest.raises(
        ValueError,
        match=re.escape(r"No value provided for required option [dummy2].str_tuple_opt."),
    ):
        Dummy2(
            PyNgOptionsReader(
                buildroot=tmp_path,
                flags={},
                env={},
                configs=[],
            )
        )

    class Dummy3(SubsystemNg):
        options_scope = "dummy3"
        help = "dummy3 help"

        @option(required=True, help="dict help")
        def dict_opt(self) -> FrozenDict[str, str]: ...

    Dummy3._initialize_()

    with pytest.raises(
        ValueError, match=re.escape(r"No value provided for required option [dummy3].dict_opt.")
    ):
        Dummy3(
            PyNgOptionsReader(
                buildroot=tmp_path,
                flags={},
                env={},
                configs=[],
            )
        )
