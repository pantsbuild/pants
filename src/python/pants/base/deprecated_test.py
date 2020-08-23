# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest.mock
import warnings
from contextlib import contextmanager
from functools import partial

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
    resolve_conflicting_options,
    warn_or_error,
)
from pants.option.option_value_container import OptionValueContainer
from pants.option.ranked_value import Rank, RankedValue
from pants.util.collections import assert_single_element

_FAKE_CUR_VERSION = "2.0.0.dev0"
FUTURE_VERSION = "9999.9.9.dev0"


@contextmanager
def assert_deprecation(deprecation_expected=True):
    with warnings.catch_warnings(record=True) as seen_warnings:

        def assert_deprecation_warning():
            if deprecation_expected:
                warning = assert_single_element(seen_warnings)
                assert warning.category == DeprecationWarning
                return warning.message
            else:
                assert len(seen_warnings) == 0

        warnings.simplefilter("always")
        assert len(seen_warnings) == 0
        yield assert_deprecation_warning
        assert_deprecation_warning()


def test_deprecated_function():
    expected_return = "deprecated_function"

    @deprecated(FUTURE_VERSION)
    def deprecated_function():
        return expected_return

    with assert_deprecation():
        assert deprecated_function() == expected_return


def test_deprecated_method():
    expected_return = "deprecated_method"

    class Test:
        @deprecated(FUTURE_VERSION)
        def deprecated_method(self):
            return expected_return

    with assert_deprecation():
        assert Test().deprecated_method() == expected_return


def test_deprecated_conditional_true():
    predicate = lambda: True
    with assert_deprecation():
        deprecated_conditional(predicate, FUTURE_VERSION, "test hint message", stacklevel=0)


def test_deprecated_conditional_false():
    predicate = lambda: False
    with assert_deprecation(deprecation_expected=False):
        deprecated_conditional(predicate, FUTURE_VERSION, "test hint message", stacklevel=0)


def test_deprecated_property():
    expected_return = "deprecated_property"

    class Test:
        @property
        @deprecated(FUTURE_VERSION)
        def deprecated_property(self):
            return expected_return

    with assert_deprecation():
        assert Test().deprecated_property == expected_return


def test_deprecated_module():
    with assert_deprecation() as extract_deprecation_warning:
        # Note: Attempting to import here a dummy module that just calls deprecated_module() does not
        # properly trigger the deprecation, due to a bad interaction with pytest that I've not fully
        # understood.  But we trust python to correctly execute modules on import, so just testing a
        # direct call of deprecated_module() here is fine.
        deprecated_module(FUTURE_VERSION, hint_message="Do not use me.")
        warning_message = str(extract_deprecation_warning())
        assert "module will be removed" in warning_message
        assert "Do not use me" in warning_message


def test_deprecation_hint():
    hint_message = "Find the foos, fast!"
    expected_return = "deprecated_function"

    @deprecated(FUTURE_VERSION, hint_message=hint_message)
    def deprecated_function():
        return expected_return

    with assert_deprecation() as extract_deprecation_warning:
        assert deprecated_function() == expected_return
        assert hint_message in str(extract_deprecation_warning())


def test_deprecation_subject():
    subject = "`./pants blah`"
    expected_return = "deprecated_function"

    @deprecated(FUTURE_VERSION, subject=subject)
    def deprecated_function():
        return expected_return

    with assert_deprecation() as extract_deprecation_warning:
        assert deprecated_function() == expected_return
        assert subject in str(extract_deprecation_warning())


def test_removal_version_required():
    with pytest.raises(MissingSemanticVersionError):

        @deprecated(None)
        def test_func():
            pass


def test_removal_version_bad():
    with pytest.raises(BadSemanticVersionError):
        warn_or_error("a.a.a", "dummy description")

    with pytest.raises(BadSemanticVersionError):

        @deprecated("a.a.a")
        def test_func0():
            pass

    with pytest.raises(BadSemanticVersionError):
        warn_or_error(1.0, "dummy description")

    with pytest.raises(BadSemanticVersionError):

        @deprecated(1.0)
        def test_func1():
            pass

    with pytest.raises(BadSemanticVersionError):
        warn_or_error("1.a.0", "dummy description")

    with pytest.raises(BadSemanticVersionError):

        @deprecated("1.a.0")
        def test_func1a():
            pass


def test_removal_version_non_dev():
    with pytest.raises(NonDevSemanticVersionError):

        @deprecated("1.0.0")
        def test_func1a():
            pass


@unittest.mock.patch("pants.base.deprecated.PANTS_SEMVER", Version(_FAKE_CUR_VERSION))
def test_removal_version_same():
    with pytest.raises(CodeRemovedError):
        warn_or_error(_FAKE_CUR_VERSION, "dummy description")

    @deprecated(_FAKE_CUR_VERSION)
    def test_func():
        pass

    with pytest.raises(CodeRemovedError):
        test_func()


def test_removal_version_lower():
    with pytest.raises(CodeRemovedError):
        warn_or_error("0.0.27.dev0", "dummy description")

    @deprecated("0.0.27.dev0")
    def test_func():
        pass

    with pytest.raises(CodeRemovedError):
        test_func()


def test_bad_decorator_nesting():
    with pytest.raises(BadDecoratorNestingError):

        class Test:
            @deprecated(FUTURE_VERSION)
            @property
            def test_prop(this):
                pass


def test_deprecation_start_version_validation():
    with pytest.raises(BadSemanticVersionError):
        warn_or_error(
            removal_version="1.0.0.dev0",
            deprecated_entity_description="dummy",
            deprecation_start_version="1.a.0",
        )

    with pytest.raises(InvalidSemanticVersionOrderingError):
        warn_or_error(
            removal_version="0.0.0.dev0",
            deprecated_entity_description="dummy",
            deprecation_start_version="1.0.0.dev0",
        )


@unittest.mock.patch("pants.base.deprecated.PANTS_SEMVER", Version(_FAKE_CUR_VERSION))
def test_deprecation_start_period():
    with pytest.raises(CodeRemovedError):
        warn_or_error(
            removal_version=_FAKE_CUR_VERSION,
            deprecated_entity_description="demo",
            deprecation_start_version="1.0.0.dev0",
        )

    warnings.simplefilter("always")
    with pytest.warns(None) as record:
        warn_or_error(
            removal_version="999.999.999.dev999",
            deprecated_entity_description="demo",
            deprecation_start_version=_FAKE_CUR_VERSION,
        )
    assert len(record) == 1
    assert (
        str(record[0].message) == "DEPRECATED: demo will be removed in version 999.999.999.dev999."
    )

    assert (
        warn_or_error(
            removal_version="999.999.999.dev999",
            deprecated_entity_description="demo",
            deprecation_start_version="500.0.0.dev0",
        )
        is None
    )


def test_resolve_conflicting_options() -> None:
    resolve_options = partial(
        resolve_conflicting_options,
        old_option="my_opt",
        new_option="my_opt",
        old_scope="old-scope",
        new_scope="new-scope",
    )
    old_val = "ancient"
    new_val = "modern"
    old_default_rv = RankedValue(Rank.HARDCODED, old_val)
    new_default_rv = RankedValue(Rank.HARDCODED, new_val)
    old_configured_rv = RankedValue(Rank.FLAG, old_val)
    new_configured_rv = RankedValue(Rank.FLAG, new_val)

    def assert_option_resolved(
        *, old_configured: bool = False, new_configured: bool = False, expected: str,
    ) -> None:
        old_container, new_container = OptionValueContainer(), OptionValueContainer()
        old_container.my_opt = old_configured_rv if old_configured else old_default_rv
        new_container.my_opt = new_configured_rv if new_configured else new_default_rv
        assert resolve_options(old_container=old_container, new_container=new_container) == expected

    assert_option_resolved(expected=new_val)
    assert_option_resolved(old_configured=True, expected=old_val)
    assert_option_resolved(new_configured=True, expected=new_val)

    # both configured -> raise an error
    old_container, new_container = OptionValueContainer(), OptionValueContainer()
    old_container.my_opt = old_configured_rv
    new_container.my_opt = new_configured_rv
    with pytest.raises(ValueError) as e:
        resolve_options(old_container=old_container, new_container=new_container)
    assert "--old-scope-my-opt" in str(e.value)
    assert "--new-scope-my-opt" in str(e.value)
