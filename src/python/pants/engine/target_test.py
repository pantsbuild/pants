# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from collections import OrderedDict
from typing import ClassVar, List, Optional

import pytest

from pants.engine.rules import UnionMembership
from pants.engine.target import PluginField, PrimitiveField, Target
from pants.util.memo import memoized_property
from pants.util.ordered_set import OrderedSet


class HaskellGhcExtensions(PrimitiveField):
    alias: ClassVar = "ghc_extensions"
    raw_value: Optional[List[str]]

    @memoized_property
    def value(self) -> List[str]:
        # Add some arbitrary validation to test that hydration works properly.
        if self.raw_value is None:
            return []
        for extension in self.raw_value:
            if not extension.startswith("Ghc"):
                raise ValueError(
                    f"All elements of `ghc_extensions` must be prefixed by `Ghc`. Received "
                    f"{extension}"
                )
        return self.raw_value


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


def test_get_field() -> None:
    extensions = ["GhcExistentialQuantification"]
    extensions_field = HaskellTarget({HaskellGhcExtensions.alias: extensions}).get(
        HaskellGhcExtensions
    )
    assert extensions_field.raw_value == extensions
    assert extensions_field.value == extensions

    default_extensions_field = HaskellTarget({}).get(HaskellGhcExtensions)
    assert default_extensions_field.raw_value is None
    assert default_extensions_field.value == []


def test_has_fields() -> None:
    class UnrelatedField(PrimitiveField):
        alias: ClassVar = "unrelated"
        raw_value: Optional[bool]

        @memoized_property
        def value(self) -> bool:
            if self.raw_value is None:
                return False
            return self.raw_value

    tgt = HaskellTarget({})
    assert tgt.has_fields([]) is True
    assert tgt.has_fields([HaskellGhcExtensions]) is True
    assert tgt.has_fields([UnrelatedField]) is False
    assert tgt.has_fields([HaskellGhcExtensions, UnrelatedField]) is False


def test_field_hydration_is_lazy() -> None:
    bad_extension = "DoesNotStartWithGhc"
    # No error upon creating the Target because validation does not happen until a call site
    # hydrates the specific field.
    tgt = HaskellTarget(
        {HaskellGhcExtensions.alias: ["GhcExistentialQuantification", bad_extension]}
    )
    # When hydrating, we expect a failure.
    with pytest.raises(ValueError) as exc:
        tgt.get(HaskellGhcExtensions).value
    assert "must be prefixed by `Ghc`" in str(exc)


def test_add_custom_fields() -> None:
    class CustomField(PrimitiveField):
        alias: ClassVar = "custom_field"
        raw_value: Optional[bool]

        @memoized_property
        def value(self) -> bool:
            if self.raw_value is None:
                return False
            return self.raw_value

    union_membership = UnionMembership(OrderedDict({HaskellField: OrderedSet([CustomField])}))
    tgt = HaskellTarget({CustomField.alias: True}, union_membership=union_membership)
    assert tgt.field_types == (HaskellGhcExtensions, CustomField)
    assert tgt.core_fields == (HaskellGhcExtensions,)
    assert tgt.plugin_fields == (CustomField,)
    assert tgt.get(CustomField).value is True

    default_tgt = HaskellTarget({}, union_membership=union_membership)
    assert default_tgt.get(CustomField).value is False
