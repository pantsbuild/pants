# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re
import warnings
from typing import Any

import pytest

from pants.engine.selectors import Get, MultiGet


class AClass:
    pass


class BClass:
    def __eq__(self, other: Any):
        return type(self) == type(other)


def test_create() -> None:
    get = Get[AClass](BClass, 42)
    assert get.product_type is AClass
    assert get.subject_declared_type is BClass
    assert get.subject == 42


def test_create_abbreviated() -> None:
    # Test the equivalence of the 1-arg and 2-arg versions.
    assert Get[AClass](BClass()) == Get[AClass](BClass, BClass())


def test_invalid_abbreviated() -> None:
    with pytest.raises(
        expected_exception=TypeError,
        match=re.escape(f"The subject argument cannot be a type, given {BClass}."),
    ):
        Get[AClass](BClass)


def test_invalid_subject() -> None:
    with pytest.raises(
        expected_exception=TypeError,
        match=re.escape(f"The subject argument cannot be a type, given {BClass}."),
    ):
        Get[AClass](BClass, BClass)


def test_invalid_subject_declared_type() -> None:
    with pytest.raises(
        expected_exception=TypeError,
        match=re.escape(
            f"The subject declared type argument must be a type, given {1} of type {type(1)}."
        ),
    ):
        Get[AClass](1, BClass)


def test_invalid_product_type() -> None:
    with pytest.raises(
        expected_exception=TypeError,
        match=re.escape(f"The product type argument must be a type, given {1} of type {type(1)}."),
    ):
        Get[1]("bob")


def test_multiget_invalid_types() -> None:
    with pytest.raises(
        expected_exception=TypeError,
        match=re.escape("Unexpected MultiGet argument types: Get(AClass, BClass, ...), 'bob'"),
    ):
        next(MultiGet(Get[AClass](BClass()), "bob").__await__())


def test_multiget_invalid_Nones() -> None:
    with pytest.raises(
        expected_exception=ValueError,
        match=re.escape("Unexpected MultiGet None arguments: None, Get(AClass, BClass, ...)"),
    ):
        next(MultiGet(None, Get[AClass](BClass()), None, None).__await__())


def test_depcated_indexed_form() -> None:
    pytest.xfail(
        "This should fail until deprecations are switched on: "
        "https://github.com/pantsbuild/pants/issues/9899"
    )
    with warnings.catch_warnings(record=True) as emitted_warnings:
        deprecated_get = Get[AClass](BClass())

    assert Get(AClass, BClass()) == deprecated_get

    assert len(emitted_warnings) == 1
    emitted_warning = emitted_warnings[0]

    assert emitted_warning.category == DeprecationWarning
    assert str(emitted_warning.message).endswith(
        "Use Get(AClass, ...) instead of Get[AClass](...)."
    )
