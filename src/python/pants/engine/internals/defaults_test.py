# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.core.target_types import GenericTarget
from pants.engine.internals.defaults import BuildFileDefaultsProvider
from pants.engine.target import RegisteredTargetTypes
from pants.engine.unions import UnionMembership
from pants.util.frozendict import FrozenDict


@pytest.fixture
def provider() -> BuildFileDefaultsProvider:
    return BuildFileDefaultsProvider(
        RegisteredTargetTypes({GenericTarget.alias: GenericTarget}),
        UnionMembership({}),
    )


def test_simple_update(provider: BuildFileDefaultsProvider) -> None:
    mutable = provider.get_defaults_for("test").as_mutable()
    assert mutable.provider is provider

    mutable.set_defaults({"target": dict(tags=["foo", "bar"])})
    assert set(provider.defaults.keys()) == {"", "test"}
    assert provider.defaults["test"].defaults == FrozenDict({})

    mutable.commit()
    assert set(provider.defaults.keys()) == {"", "test"}
    assert provider.defaults["test"].defaults == FrozenDict(
        {
            "target": FrozenDict({"tags": ("foo", "bar")}),
        }
    )
