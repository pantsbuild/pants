# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from collections import OrderedDict
from dataclasses import dataclass
from typing import ClassVar, List, Optional

import pytest

from pants.engine.rules import UnionMembership
from pants.engine.target import PluginField, PrimitiveField, Target
from pants.util.memo import memoized_property
from pants.util.ordered_set import OrderedSet


@dataclass(frozen=True)
class HaskellGhcExtensions(PrimitiveField):
    alias: ClassVar = "ghc_extensions"
    unhydrated: Optional[List[str]] = None

    @memoized_property
    def hydrated(self) -> List[str]:
        # Add some arbitrary validation to test that hydration works properly.
        for extension in self.unhydrated:
            if not extension.startswith("Ghc"):
                raise ValueError(
                    f"All elements of `ghc_extensions` must be prefixed by `Ghc`. Received "
                    f"{extension}"
                )
        return self.unhydrated


class HaskellField(PluginField):
    pass


class HaskellTarget(Target):
    alias: ClassVar = "haskell"
    core_fields: ClassVar = (HaskellGhcExtensions,)
    plugin_field_type: ClassVar = HaskellField


def test_invalid_fields_rejected() -> None:
    with pytest.raises(ValueError) as exc:
        HaskellTarget({"invalid_field": True})
    assert "Unrecognized field `invalid_field=True` for target type `haskell`." in str(exc)


def test_field_hydration_is_lazy() -> None:
    bad_extension = "DoesNotStartWithGhc"
    # No error upon creating the Target because validation does not happen until a call site
    # hydrates the specific field.
    tgt = HaskellTarget(
        {HaskellGhcExtensions.alias: ["GhcExistentialQuantification", bad_extension]}
    )
    # When hydrating, we expect a failure.
    with pytest.raises(ValueError) as exc:
        tgt.get(HaskellGhcExtensions).hydrated
    assert "must be prefixed by `Ghc`" in str(exc)


def test_add_custom_fields() -> None:
    @dataclass(frozen=True)
    class CustomField(PrimitiveField):
        alias: ClassVar = "custom_field"
        unhydrated: bool = False

        @memoized_property
        def hydrated(self) -> bool:
            return self.unhydrated

    union_membership = UnionMembership(OrderedDict({HaskellField: OrderedSet([CustomField])}))
    tgt = HaskellTarget({CustomField.alias: True}, union_membership=union_membership)
    assert tgt.field_types == (HaskellGhcExtensions, CustomField)
    assert tgt.core_fields == (HaskellGhcExtensions,)
    assert tgt.plugin_fields == (CustomField,)
    assert tgt.get(CustomField).hydrated is True

    default_tgt = HaskellTarget({}, union_membership=union_membership)
    assert default_tgt.get(CustomField).hydrated is False
