# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Any

import pytest

from pants.core.target_types import GenericTarget
from pants.engine.addresses import Address
from pants.engine.internals.parametrize import (
    Parametrize,
    _concrete_fields_are_equivalent,
    _TargetParametrization,
    _TargetParametrizations,
)
from pants.engine.target import Field, Target
from pants.util.frozendict import FrozenDict


@pytest.mark.parametrize(
    "expected,args,kwargs",
    [
        ({"a": "a"}, ["a"], {}),
        ({"a": "a", "b": "c"}, ["a"], {"b": "c"}),
        ({"b": "c"}, [], {"b": "c"}),
        ({"b": 1}, [], {"b": 1}),
    ],
)
def test_to_parameters_success(
    expected: dict[str, Any], args: list[str], kwargs: dict[str, Any]
) -> None:
    assert expected == Parametrize(*args, **kwargs).to_parameters()


@pytest.mark.parametrize(
    "exception_str,args,kwargs",
    [
        ("Positional arguments must be strings, but `[1]` was a", [[1]], {}),
        (
            "Positional arguments cannot have the same name as keyword arguments",
            ["x"],
            {"x": 1},
        ),
        ("Positional argument `@` contained separator characters", ["@"], {}),
    ],
)
def test_to_parameters_failure(exception_str: str, args: list[Any], kwargs: dict[str, Any]) -> None:
    with pytest.raises(Exception) as exc:
        Parametrize(*args, **kwargs).to_parameters()
    assert exception_str in str(exc.value)


@pytest.mark.parametrize(
    "expected,fields",
    [
        ([("a:a", {"f": "b"})], {"f": "b"}),
        ([("a@f=b", {"f": "b"})], {"f": Parametrize("b")}),
        (
            [
                ("a@f=b", {"f": "b"}),
                ("a@f=c", {"f": "c"}),
            ],
            {"f": Parametrize("b", "c")},
        ),
        (
            [
                ("a@f=b,x=d", {"f": "b", "x": "d"}),
                ("a@f=b,x=e", {"f": "b", "x": "e"}),
                ("a@f=c,x=d", {"f": "c", "x": "d"}),
                ("a@f=c,x=e", {"f": "c", "x": "e"}),
            ],
            {"f": Parametrize("b", "c"), "x": Parametrize("d", "e")},
        ),
    ],
)
def test_expand(
    expected: list[tuple[str, dict[str, Any]]], fields: dict[str, Any | Parametrize]
) -> None:
    assert sorted(expected) == sorted(
        (address.spec, result_fields)
        for address, result_fields in Parametrize.expand(Address("a"), fields)
    )


def test_get_superset_targets() -> None:
    def tgt(addr: Address) -> GenericTarget:
        return GenericTarget({}, addr)

    def parametrization(original: Address | None, params: list[Address]) -> _TargetParametrization:
        return _TargetParametrization(
            tgt(original) if original else None, FrozenDict({a: tgt(a) for a in params})
        )

    dir1 = Address("dir1")
    dir1__k1_v1__k2_v1 = Address("dir1", parameters={"k1": "v1", "k2": "v1"})
    dir1__k1_v1__k2_v2 = Address("dir1", parameters={"k1": "v1", "k2": "v2"})
    dir1__k1_v2__k2_v1 = Address("dir1", parameters={"k1": "v2", "k2": "v1"})
    dir1__k1_v2__k2_v2 = Address("dir1", parameters={"k1": "v2", "k2": "v2"})

    dir2 = Address("dir2")

    dir3 = Address("dir3", parameters={"k": "v"})

    params = _TargetParametrizations(
        [
            parametrization(
                None,
                [dir1__k1_v1__k2_v1, dir1__k1_v1__k2_v2, dir1__k1_v2__k2_v1, dir1__k1_v2__k2_v2],
            ),
            parametrization(dir2, []),
            parametrization(None, []),
            # This is what a target generator looks like in practice.
            parametrization(
                dir3,
                [
                    Address("dir3", generated_name="a", parameters={"k": "v"}),
                    Address("dir3", generated_name="b", parameters={"k": "v"}),
                ],
            ),
        ]
    )

    def assert_gets(addr: Address, expected: set[Address]) -> None:
        assert set(params.get_all_superset_targets(addr)) == expected

    assert_gets(dir2, {dir2})

    assert_gets(dir1__k1_v1__k2_v1, {dir1__k1_v1__k2_v1})
    assert_gets(
        dir1, {dir1__k1_v1__k2_v1, dir1__k1_v1__k2_v2, dir1__k1_v2__k2_v1, dir1__k1_v2__k2_v2}
    )
    assert_gets(Address("dir1", parameters={"k1": "v1"}), {dir1__k1_v1__k2_v1, dir1__k1_v1__k2_v2})
    assert_gets(Address("dir1", parameters={"k1": "v2"}), {dir1__k1_v2__k2_v1, dir1__k1_v2__k2_v2})

    assert_gets(dir3, {dir3})

    assert_gets(Address("fake"), set())
    assert_gets(Address("dir1", parameters={"fake": "a"}), set())
    assert_gets(Address("dir1", parameters={"k1": "fake"}), set())


def test_concrete_fields_are_equivalent() -> None:
    class ParentField(Field):
        alias = "parent"
        help = "foo"

    class ChildField(ParentField):
        alias = "child"
        help = "foo"

    class UnrelatedField(Field):
        alias = "unrelated"
        help = "foo"

    class ParentTarget(Target):
        alias = "parent_tgt"
        help = "foo"
        core_fields = (ParentField,)

    class ChildTarget(Target):
        alias = "child_tgt"
        help = "foo"
        core_fields = (ChildField,)

    parent_tgt = ParentTarget({"parent": "val"}, Address("parent"))
    assert (
        _concrete_fields_are_equivalent(
            consumer=parent_tgt, candidate_field_type=ParentField, candidate_field_value="val"
        )
        is True
    )
    assert (
        _concrete_fields_are_equivalent(
            consumer=parent_tgt, candidate_field_type=ParentField, candidate_field_value="different"
        )
        is False
    )
    assert (
        _concrete_fields_are_equivalent(
            consumer=parent_tgt, candidate_field_type=ChildField, candidate_field_value="val"
        )
        is True
    )
    assert (
        _concrete_fields_are_equivalent(
            consumer=parent_tgt, candidate_field_type=ChildField, candidate_field_value="different"
        )
        is False
    )
    assert (
        _concrete_fields_are_equivalent(
            consumer=parent_tgt, candidate_field_type=UnrelatedField, candidate_field_value="val"
        )
        is False
    )

    child_tgt = ChildTarget({"child": "val"}, Address("child"))
    assert (
        _concrete_fields_are_equivalent(
            consumer=child_tgt, candidate_field_type=ParentField, candidate_field_value="val"
        )
        is True
    )
    assert (
        _concrete_fields_are_equivalent(
            consumer=child_tgt, candidate_field_type=ParentField, candidate_field_value="different"
        )
        is False
    )
    assert (
        _concrete_fields_are_equivalent(
            consumer=child_tgt, candidate_field_type=ChildField, candidate_field_value="val"
        )
        is True
    )
    assert (
        _concrete_fields_are_equivalent(
            consumer=child_tgt, candidate_field_type=ChildField, candidate_field_value="different"
        )
        is False
    )
    assert (
        _concrete_fields_are_equivalent(
            consumer=child_tgt, candidate_field_type=UnrelatedField, candidate_field_value="val"
        )
        is False
    )
