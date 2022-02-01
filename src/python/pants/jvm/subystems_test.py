# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.java.target_types import (
    JavaJunitTestSourceField,
    JavaSourceField,
    JavaSourceTarget,
    JunitTestTarget,
)
from pants.core.target_types import GenericTarget
from pants.engine.addresses import Address
from pants.engine.target import InvalidFieldException
from pants.jvm.subsystems import JvmSubsystem
from pants.jvm.target_types import JvmCompatibleResolvesField, JvmResolveField
from pants.testutil.option_util import create_subsystem


def test_resolves_for_targets() -> None:
    jvm = create_subsystem(
        JvmSubsystem, resolves={"a": "", "b": "", "c": "", "default": ""}, default_resolve="default"
    )

    assert jvm.resolves_for_target(
        JavaSourceTarget(
            {JavaSourceField.alias: "foo", JvmCompatibleResolvesField.alias: ["a", "b"]},
            Address("dir"),
        )
    ) == ("a", "b")
    assert jvm.resolves_for_target(
        JavaSourceTarget({JavaSourceField.alias: "foo"}, Address("dir"))
    ) == ("default",)
    with pytest.raises(InvalidFieldException):
        jvm.resolves_for_target(
            JavaSourceTarget(
                {
                    JavaSourceField.alias: "foo",
                    JvmCompatibleResolvesField.alias: ["a", "bad", "malo"],
                },
                Address("dir"),
            )
        )

    assert jvm.resolves_for_target(
        JunitTestTarget(
            {JavaJunitTestSourceField.alias: "foo", JvmResolveField.alias: "a"}, Address("dir")
        )
    ) == ("a",)
    assert jvm.resolves_for_target(
        JunitTestTarget({JavaJunitTestSourceField.alias: "foo"}, Address("dir"))
    ) == ("default",)
    with pytest.raises(InvalidFieldException):
        jvm.resolves_for_target(
            JunitTestTarget(
                {JavaJunitTestSourceField.alias: "foo", JvmResolveField.alias: "bad"},
                Address("dir"),
            )
        )

    with pytest.raises(AssertionError):
        jvm.resolves_for_target(GenericTarget({}, Address("dir")))
