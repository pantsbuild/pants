# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re
from collections.abc import Callable
from dataclasses import dataclass

import pytest

from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.unions import union

pytestmark = pytest.mark.call_by_type


class AClass:
    pass


@dataclass(frozen=True)
class BClass:
    pass


def test_create_get() -> None:
    get1 = Get(AClass)
    assert get1.output_type is AClass
    assert get1.input_types == []
    assert get1.inputs == []

    get2 = Get(AClass, int, 42)
    assert get2.output_type is AClass
    assert get2.input_types == [int]
    assert get2.inputs == [42]

    # Also test the equivalence of the 1-arg and 2-arg versions.
    get3 = Get(AClass, int(42))
    assert get2.output_type == get3.output_type
    assert get2.input_types == get3.input_types
    assert get2.inputs == get3.inputs

    # And finally the multiple parameter syntax.
    get4 = Get(AClass, {42: int, "hello": str})
    assert get4.output_type is AClass
    assert get4.input_types == [int, str]
    assert get4.inputs == [42, "hello"]


def assert_invalid_get(create_get: Callable[[], Get], *, expected: str) -> None:
    with pytest.raises(TypeError) as exc:
        create_get()
    assert str(exc.value) == expected


def test_invalid_get() -> None:
    # Bad output type.
    assert_invalid_get(
        lambda: Get(1, str, "bob"),  # type: ignore[call-overload]
        expected=(
            "Invalid Get. The first argument (the output type) must be a type, but given "
            f"`1` with type {int}."
        ),
    )

    # Bad second argument.
    assert_invalid_get(
        lambda: Get(AClass, BClass),
        expected=(
            "Invalid Get. Because you are using the shorthand form "
            "Get(OutputType, InputType(constructor args)), the second argument should be "
            f"a constructor call, rather than a type, but given {BClass}."
        ),
    )
    assert_invalid_get(
        lambda: Get(AClass, 1, BClass),
        expected=(
            "Invalid Get. Because you are using the longhand form Get(OutputType, InputType, "
            "input), the second argument must be a type, but given `1` of type "
            f"{int}."
        ),
    )

    # Bad third argument.
    assert_invalid_get(
        lambda: Get(AClass, BClass, BClass),
        expected=(
            "Invalid Get. Because you are using the longhand form Get(OutputType, InputType, "
            "input), the third argument should be an object, rather than a type, but given "
            f"{BClass}."
        ),
    )


def test_invalid_get_input_does_not_match_type() -> None:
    assert_invalid_get(
        lambda: Get(AClass, str, 1),
        expected=(
            f"Invalid Get. The third argument `1` must have the exact same type as the "
            f"second argument, {str}, but had the type {int}."
        ),
    )

    # However, if the `input_type` is a `@union`, then we do not eagerly validate.
    @union
    class UnionBase:
        pass

    union_get = Get(AClass, UnionBase, 1)
    assert union_get.input_types == [UnionBase]
    assert union_get.inputs == [1]


def test_multiget_invalid_types() -> None:
    with pytest.raises(
        expected_exception=TypeError,
        match=re.escape("Unexpected MultiGet argument types: Get(AClass, BClass, BClass()), 'bob'"),
    ):
        next(MultiGet(Get(AClass, BClass()), "bob").__await__())  # type: ignore[call-overload]


def test_multiget_invalid_Nones() -> None:
    with pytest.raises(
        expected_exception=ValueError,
        match=re.escape("Unexpected MultiGet None arguments: None, Get(AClass, BClass, BClass())"),
    ):
        next(
            MultiGet(None, Get(AClass, BClass()), None, None).__await__()  # type: ignore[call-overload]
        )


# N.B.: MultiGet takes either:
# 1. One homogenous Get collection.
# 2. Up to 10 homogeneous or heterogeneous Gets
# 3. 11 or more homogenous Gets.
#
# Here we test that the runtime actually accepts 11 or more Gets. This is really just a regression
# test that checks MultiGet retains a trailing *args slot.
@pytest.mark.parametrize("count", list(range(1, 20)))
def test_homogenous(count) -> None:
    gets = tuple(Get(AClass, BClass()) for _ in range(count))
    assert gets == next(MultiGet(*gets).__await__())
