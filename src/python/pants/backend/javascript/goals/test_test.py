# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from typing import Any
from unittest.mock import Mock, sentinel

import pytest

from pants.backend.javascript.goals.test import (
    JSTestFieldSet,
    JSTestRequest,
    partition_nodejs_tests,
)
from pants.backend.javascript.package_json import OwningNodePackage, OwningNodePackageRequest
from pants.backend.javascript.target_types import (
    JSTestBatchCompatibilityTagField,
    JSTestExtraEnvVarsField,
)
from pants.build_graph.address import Address
from pants.testutil.rule_runner import MockGet, run_rule_with_mocks


def given_field_set(
    address: Any, *, env_vars: tuple[str, ...] = tuple(), batch_compatibility_tag: str | None
) -> Mock:
    field_set = Mock(JSTestFieldSet)
    field_set.extra_env_vars = Mock(JSTestExtraEnvVarsField)
    field_set.extra_env_vars.sorted.return_value = env_vars
    field_set.batch_compatibility_tag = JSTestBatchCompatibilityTagField(
        batch_compatibility_tag, address
    )
    field_set.address = address
    return field_set


def test_batches_are_seperated_on_owning_packages() -> None:
    field_set_1 = given_field_set(Address("1"), batch_compatibility_tag="default")
    field_set_2 = given_field_set(Address("2"), batch_compatibility_tag="default")

    request = JSTestRequest.PartitionRequest(field_sets=(field_set_1, field_set_2))

    def mocked_owning_node_package(r: OwningNodePackageRequest) -> Any:
        if r.address == Address("1"):
            return OwningNodePackage(sentinel.owning_package_1)
        else:
            return OwningNodePackage(sentinel.owning_package_2)

    parititions = run_rule_with_mocks(
        partition_nodejs_tests,
        rule_args=(request,),
        mock_gets=[
            MockGet(OwningNodePackage, (OwningNodePackageRequest,), mocked_owning_node_package),
        ],
    )

    assert len(parititions) == 2


@pytest.mark.parametrize(
    "field_set_1, field_set_2",
    [
        pytest.param(
            given_field_set(Address("1"), batch_compatibility_tag="1"),
            given_field_set(Address("2"), batch_compatibility_tag="2"),
            id="compatibility_tag",
        ),
        pytest.param(
            given_field_set(Address("1"), batch_compatibility_tag="default"),
            given_field_set(
                Address("2"), batch_compatibility_tag="default", env_vars=("NODE_ENV=dev",)
            ),
            id="extra_env_vars",
        ),
        pytest.param(
            given_field_set(Address("1"), batch_compatibility_tag=None),
            given_field_set(Address("2"), batch_compatibility_tag=None),
            id="no_compatibility_tag",
        ),
    ],
)
def test_batches_are_seperated_on_metadata(field_set_1: Mock, field_set_2: Mock) -> None:
    request = JSTestRequest.PartitionRequest(field_sets=(field_set_1, field_set_2))

    def mocked_owning_node_package(_: OwningNodePackageRequest) -> Any:
        return OwningNodePackage(sentinel.same_owning_package)

    parititions = run_rule_with_mocks(
        partition_nodejs_tests,
        rule_args=(request,),
        mock_gets=[
            MockGet(OwningNodePackage, (OwningNodePackageRequest,), mocked_owning_node_package),
        ],
    )

    assert len(parititions) == 2


def test_batches_are_the_same_for_same_compat_and_package() -> None:
    field_set_1 = given_field_set(Address("1"), batch_compatibility_tag="default")

    field_set_2 = given_field_set(Address("2"), batch_compatibility_tag="default")
    request = JSTestRequest.PartitionRequest(field_sets=(field_set_1, field_set_2))

    def mocked_owning_node_package(_: OwningNodePackageRequest) -> Any:
        return OwningNodePackage(sentinel.same_owning_package)

    parititions = run_rule_with_mocks(
        partition_nodejs_tests,
        rule_args=(request,),
        mock_gets=[
            MockGet(OwningNodePackage, (OwningNodePackageRequest,), mocked_owning_node_package),
        ],
    )

    assert len(parititions) == 1
