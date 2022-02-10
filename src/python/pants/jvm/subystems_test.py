# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.java.target_types import JavaSourceField, JavaSourceTarget
from pants.core.target_types import GenericTarget
from pants.engine.addresses import Address
from pants.engine.target import InvalidFieldException
from pants.jvm.subsystems import JvmSubsystem
from pants.jvm.target_types import JvmResolveField
from pants.testutil.option_util import create_subsystem


def test_resolve_for_target() -> None:
    jvm = create_subsystem(
        JvmSubsystem, resolves={"a": "", "b": "", "c": "", "default": ""}, default_resolve="default"
    )

    assert (
        jvm.resolve_for_target(
            JavaSourceTarget(
                {JavaSourceField.alias: "foo", JvmResolveField.alias: "a"},
                Address("dir"),
            )
        )
        == "a"
    )

    assert (
        jvm.resolve_for_target(JavaSourceTarget({JavaSourceField.alias: "foo"}, Address("dir")))
        == "default"
    )

    with pytest.raises(InvalidFieldException):
        jvm.resolve_for_target(
            JavaSourceTarget(
                {
                    JavaSourceField.alias: "foo",
                    JvmResolveField.alias: "malo",
                },
                Address("dir"),
            )
        )

    with pytest.raises(AssertionError):
        jvm.resolve_for_target(GenericTarget({}, Address("dir")))
