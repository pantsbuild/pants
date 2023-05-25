# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest.mock

import pytest
from packaging.version import Version

from pants.base.deprecated import (
    BadDecoratorNestingError,
    BadSemanticVersionError,
    CodeRemovedError,
    InvalidSemanticVersionOrderingError,
    MissingSemanticVersionError,
    NonDevSemanticVersionError,
    deprecated,
    deprecated_conditional,
    deprecated_module,
    is_deprecation_active,
    resolve_conflicting_options,
    warn_or_error,
)
from pants.option.option_value_container import OptionValueContainerBuilder
from pants.option.ranked_value import Rank, RankedValue

_FAKE_CUR_VERSION = "2.0.0.dev0"
FUTURE_VERSION = "9999.9.9.dev0"


def test_deprecated_function(caplog) -> None:
    @deprecated(FUTURE_VERSION, "A hint!")
    def deprecated_function():
        return "some val"

    class Foo:
        @deprecated(FUTURE_VERSION)
        def deprecated_method(self):
            return "some val"

        @property
        @deprecated(FUTURE_VERSION)
        def deprecated_property(self):
            return "some val"

    assert not caplog.records
    assert deprecated_function() == "some val"
    assert len(caplog.records) == 1
    assert deprecated_function.__name__ in caplog.text
    assert "A hint!" in caplog.text

    caplog.clear()
    assert Foo().deprecated_method() == "some val"
    assert len(caplog.records) == 1
    assert Foo.deprecated_method.__name__ in caplog.text

    caplog.clear()
    assert Foo().deprecated_property == "some val"
    assert len(caplog.records) == 1
    assert "deprecated_property" in caplog.text


def test_deprecated_function_invalid() -> None:
    with pytest.raises(MissingSemanticVersionError):

        @deprecated(None)  # type: ignore[arg-type]
        def func():
            pass

    with pytest.raises(BadDecoratorNestingError):

        class Test:
            @deprecated(FUTURE_VERSION)  # type: ignore[misc]
            @property
            def prop(this):
                pass


def test_deprecated_conditional(caplog) -> None:
    assert not caplog.records
    deprecated_conditional(lambda: True, FUTURE_VERSION, "deprecated entity", None)
    assert len(caplog.records) == 1
    assert "deprecated entity" in caplog.text

    caplog.clear()
    deprecated_conditional(lambda: False, FUTURE_VERSION, "deprecated entity", None)
    assert not caplog.records


def test_deprecated_module(caplog) -> None:
    assert not caplog.records
    deprecated_module(FUTURE_VERSION, hint="Do not use me.")
    assert len(caplog.records) == 1
    assert "module is scheduled to be removed" in caplog.text
    assert "Do not use me" in caplog.text


def test_removal_version_bad() -> None:
    with pytest.raises(BadSemanticVersionError):
        warn_or_error("a.a.a", "fake description", None)

    with pytest.raises(BadSemanticVersionError):

        @deprecated("a.a.a")
        def test_func0():
            pass

    with pytest.raises(BadSemanticVersionError):
        warn_or_error(1.0, "fake description", None)  # type: ignore[arg-type]

    with pytest.raises(BadSemanticVersionError):

        @deprecated(1.0)  # type: ignore[arg-type]
        def test_func1():
            pass

    with pytest.raises(BadSemanticVersionError):
        warn_or_error("1.a.0", "fake description", None)

    with pytest.raises(BadSemanticVersionError):

        @deprecated("1.a.0")
        def test_func1a():
            pass

    with pytest.raises(NonDevSemanticVersionError):

        @deprecated("1.0.0")
        def test_func1b():
            pass


@unittest.mock.patch("pants.base.deprecated.PANTS_SEMVER", Version(_FAKE_CUR_VERSION))
def test_removal_version_same() -> None:
    with pytest.raises(CodeRemovedError):
        warn_or_error(_FAKE_CUR_VERSION, "fake description", None)

    @deprecated(_FAKE_CUR_VERSION)
    def test_func():
        pass

    with pytest.raises(CodeRemovedError):
        test_func()


def test_removal_version_lower() -> None:
    with pytest.raises(CodeRemovedError):
        warn_or_error("0.0.27.dev0", "fake description", None)

    @deprecated("0.0.27.dev0")
    def test_func():
        pass

    with pytest.raises(CodeRemovedError):
        test_func()


def test_deprecation_start_version_validation() -> None:
    with pytest.raises(BadSemanticVersionError):
        warn_or_error(removal_version="1.0.0.dev0", entity="fake", hint=None, start_version="1.a.0")

    with pytest.raises(InvalidSemanticVersionOrderingError):
        warn_or_error(
            removal_version="0.0.0.dev0", entity="fake", hint=None, start_version="1.0.0.dev0"
        )


@unittest.mock.patch("pants.base.deprecated.PANTS_SEMVER", Version(_FAKE_CUR_VERSION))
def test_deprecation_start_period(caplog) -> None:
    with pytest.raises(CodeRemovedError):
        warn_or_error(
            removal_version=_FAKE_CUR_VERSION, entity="demo", hint=None, start_version="1.0.0.dev0"
        )

    caplog.clear()
    warn_or_error(
        removal_version="999.999.999.dev999",
        entity="demo",
        hint=None,
        start_version=_FAKE_CUR_VERSION,
    )
    assert len(caplog.records) == 1
    assert (
        "DEPRECATED: demo is scheduled to be removed in version 999.999.999.dev999." in caplog.text
    )


@unittest.mock.patch("pants.base.deprecated.PANTS_SEMVER", Version(_FAKE_CUR_VERSION))
def test_deprecation_memoization(caplog) -> None:
    caplog.clear()
    for i in range(3):
        warn_or_error(
            removal_version="999.999.999.dev999",
            entity="memo",
            hint=None,
            start_version=_FAKE_CUR_VERSION,
        )
    assert len(caplog.records) == 1
    warn_or_error(
        removal_version="999.999.999.dev999",
        entity="another",
        hint=None,
        start_version=_FAKE_CUR_VERSION,
    )
    assert len(caplog.records) == 2


def test_resolve_conflicting_options() -> None:
    old_val = "ancient"
    new_val = "modern"
    old_default_rv = RankedValue(Rank.HARDCODED, old_val)
    new_default_rv = RankedValue(Rank.HARDCODED, new_val)
    old_configured_rv = RankedValue(Rank.FLAG, old_val)
    new_configured_rv = RankedValue(Rank.FLAG, new_val)

    def option_resolved(*, old_configured: bool = False, new_configured: bool = False):
        old_container_builder, new_container_builder = (
            OptionValueContainerBuilder(),
            OptionValueContainerBuilder(),
        )
        old_container_builder.my_opt = old_configured_rv if old_configured else old_default_rv
        new_container_builder.my_opt = new_configured_rv if new_configured else new_default_rv
        old_container = old_container_builder.build()
        new_container = new_container_builder.build()
        return resolve_conflicting_options(
            old_option="my_opt",
            new_option="my_opt",
            old_scope="old-scope",
            new_scope="new-scope",
            old_container=old_container,
            new_container=new_container,
        )

    assert option_resolved() == new_val
    assert option_resolved(old_configured=True) == old_val
    assert option_resolved(new_configured=True) == new_val

    # both configured -> raise an error
    with pytest.raises(ValueError) as e:
        option_resolved(old_configured=True, new_configured=True)
    assert "--old-scope-my-opt" in str(e.value)
    assert "--new-scope-my-opt" in str(e.value)


def test_is_deprecation_active() -> None:
    assert is_deprecation_active(start_version=None)
    assert is_deprecation_active(start_version="1.0.0")
    assert not is_deprecation_active(start_version=FUTURE_VERSION)
