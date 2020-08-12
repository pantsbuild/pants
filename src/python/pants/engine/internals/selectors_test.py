# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import ast
import re
from typing import Any, Tuple

import pytest

from pants.engine.internals.selectors import Get, GetConstraints, GetParseError, MultiGet


def parse_get_types(get: str) -> Tuple[str, str]:
    get_args = ast.parse(get).body[0].value.args  # type: ignore[attr-defined]
    return GetConstraints.parse_product_and_subject_types(get_args, source_file_name="test.py")


def test_parse_get_types_valid() -> None:
    assert parse_get_types("Get(P, S, subject)") == ("P", "S")
    assert parse_get_types("Get(P, S())") == ("P", "S")


def assert_parse_get_types_fails(get: str, *, expected_explanation: str) -> None:
    with pytest.raises(GetParseError) as exc:
        parse_get_types(get)
    assert str(exc.value) == f"Invalid Get. {expected_explanation} Failed for {get} in test.py."


def test_parse_get_types_wrong_number_args() -> None:
    assert_parse_get_types_fails(
        "Get()",
        expected_explanation="Expected either two or three arguments, but got 0 arguments.",
    )
    assert_parse_get_types_fails(
        "Get(P, S1, S2(), S3.create())",
        expected_explanation="Expected either two or three arguments, but got 4 arguments.",
    )


def test_parse_get_types_invalid_product() -> None:
    assert_parse_get_types_fails(
        "Get(P(), S, subject)",
        expected_explanation=(
            "The first argument should be the type of the product, like `Digest` or "
            "`ProcessResult`."
        ),
    )


def test_parse_get_types_invalid_subject() -> None:
    assert_parse_get_types_fails(
        "Get(P, S)",
        expected_explanation=(
            "Because you are using the shorthand form Get(ProductType, SubjectType(constructor "
            "args), the second argument should be a constructor call, like `MergeDigest(...)` or "
            "`Process(...)`."
        ),
    )
    assert_parse_get_types_fails(
        "Get(P, Subject.create())",
        expected_explanation=(
            "Because you are using the shorthand form Get(ProductType, SubjectType(constructor "
            "args), the second argument should be a top-level constructor function call, like "
            "`MergeDigest(...)` or `Process(...)`, rather than a method call."
        ),
    )
    assert_parse_get_types_fails(
        "Get(P, Subject(), subject)",
        expected_explanation=(
            "Because you are using the longhand form Get(ProductType, SubjectType, "
            "subject_instance), the second argument should be a type, like `MergeDigests` or "
            "`Process`."
        ),
    )


class AClass:
    pass


class BClass:
    def __eq__(self, other: Any):
        return type(self) == type(other)


def test_create_get() -> None:
    get = Get(AClass, BClass, 42)
    assert get.product_type is AClass
    assert get.subject_declared_type is BClass
    assert get.subject == 42


def test_create_get_abbreviated() -> None:
    # Test the equivalence of the 1-arg and 2-arg versions.
    assert Get(AClass, BClass()) == Get(AClass, BClass, BClass())


def test_invalid_get_abbreviated() -> None:
    with pytest.raises(
        expected_exception=TypeError,
        match=re.escape(f"The subject argument cannot be a type, given {BClass}."),
    ):
        Get(AClass, BClass)


def test_invalid_get_subject() -> None:
    with pytest.raises(
        expected_exception=TypeError,
        match=re.escape(f"The subject argument cannot be a type, given {BClass}."),
    ):
        Get(AClass, BClass, BClass)


def test_invalid_get_subject_declared_type() -> None:
    with pytest.raises(
        expected_exception=TypeError,
        match=re.escape(
            f"The subject declared type argument must be a type, given {1} of type {type(1)}."
        ),
    ):
        Get(AClass, 1, BClass)  # type: ignore[call-overload]


def test_invalid_get_product_type() -> None:
    with pytest.raises(
        expected_exception=TypeError,
        match=re.escape(f"The product type argument must be a type, given {1} of type {type(1)}."),
    ):
        Get(1, "bob")  # type: ignore[call-overload]


def test_multiget_invalid_types() -> None:
    with pytest.raises(
        expected_exception=TypeError,
        match=re.escape("Unexpected MultiGet argument types: Get(AClass, BClass, ...), 'bob'"),
    ):
        next(
            MultiGet(Get(AClass, BClass()), "bob").__await__()  # type: ignore[call-overload]
        )


def test_multiget_invalid_Nones() -> None:
    with pytest.raises(
        expected_exception=ValueError,
        match=re.escape("Unexpected MultiGet None arguments: None, Get(AClass, BClass, ...)"),
    ):
        next(
            MultiGet(None, Get(AClass, BClass()), None, None).__await__()  # type: ignore[call-overload]
        )
