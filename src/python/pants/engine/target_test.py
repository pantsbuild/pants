# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from collections import OrderedDict
from dataclasses import dataclass
from pathlib import PurePath
from typing import ClassVar, List, Optional, Tuple

import pytest

from pants.engine.fs import EMPTY_DIRECTORY_DIGEST, PathGlobs, Snapshot
from pants.engine.rules import UnionMembership, rule
from pants.engine.selectors import Get
from pants.engine.target import AsyncField, PrimitiveField, Target
from pants.testutil.engine.util import MockGet, run_rule
from pants.util.collections import ensure_str_list
from pants.util.memo import memoized_property
from pants.util.ordered_set import OrderedSet


class HaskellGhcExtensions(PrimitiveField):
    alias: ClassVar = "ghc_extensions"
    raw_value: Optional[List[str]]

    @memoized_property
    def value(self) -> List[str]:
        if self.raw_value is None:
            return []
        # Add some arbitrary validation to test that hydration works properly.
        bad_extensions = [
            extension for extension in self.raw_value if not extension.startswith("Ghc")
        ]
        if bad_extensions:
            raise ValueError(
                f"All elements of `{self.alias}` must be prefixed by `Ghc`. Received "
                f"{bad_extensions}."
            )
        return self.raw_value


class HaskellSources(AsyncField):
    alias: ClassVar = "sources"
    raw_value: Optional[List[str]]

    def validate_pre_hydration(self) -> None:
        ensure_str_list(self.raw_value)

    def validate_post_hydration(self, result: Snapshot) -> None:
        non_haskell_sources = [fp for fp in result.files if PurePath(fp).suffix != ".hs"]
        if non_haskell_sources:
            raise ValueError(
                f"Received non-Haskell sources in {self.alias}: {non_haskell_sources}."
            )


@dataclass(frozen=True)
class HaskellSourcesResult:
    snapshot: Snapshot


@rule
async def hydrate_haskell_sources(sources: HaskellSources) -> HaskellSourcesResult:
    sources.validate_pre_hydration()
    result = await Get[Snapshot](PathGlobs("*.hs"))
    sources.validate_post_hydration(result)
    return HaskellSourcesResult(result)


class HaskellTarget(Target):
    alias: ClassVar = "haskell"
    core_fields: ClassVar = (HaskellGhcExtensions, HaskellSources)


def test_invalid_fields_rejected() -> None:
    with pytest.raises(ValueError) as exc:
        HaskellTarget({"invalid_field": True})
    assert "Unrecognized field `invalid_field=True` for target type `haskell`." in str(exc)


def test_get_primitive_field() -> None:
    extensions = ["GhcExistentialQuantification"]
    extensions_field = HaskellTarget({HaskellGhcExtensions.alias: extensions}).get(
        HaskellGhcExtensions
    )
    assert extensions_field.raw_value == extensions
    assert extensions_field.value == extensions

    default_extensions_field = HaskellTarget({}).get(HaskellGhcExtensions)
    assert default_extensions_field.raw_value is None
    assert default_extensions_field.value == []


def test_get_async_field() -> None:
    def hydrate_field(
        *, raw_source_files: List[str], hydrated_source_files: Tuple[str, ...]
    ) -> HaskellSourcesResult:
        sources_field = HaskellTarget({HaskellSources.alias: raw_source_files}).get(HaskellSources)
        assert sources_field.raw_value == raw_source_files
        result: HaskellSourcesResult = run_rule(
            hydrate_haskell_sources,
            rule_args=[sources_field],
            mock_gets=[
                MockGet(
                    product_type=Snapshot,
                    subject_type=PathGlobs,
                    mock=lambda _: Snapshot(
                        directory_digest=EMPTY_DIRECTORY_DIGEST,
                        files=hydrated_source_files,
                        dirs=(),
                    ),
                )
            ],
        )
        return result

    # Normal field
    expected_files = ("monad.hs", "abstract_art.hs", "abstract_algebra.hs")
    assert (
        hydrate_field(
            raw_source_files=["monad.hs", "abstract_*.hs"], hydrated_source_files=expected_files
        ).snapshot.files
        == expected_files
    )

    # Test pre-hydration validation
    with pytest.raises(ValueError) as exc:
        hydrate_field(raw_source_files=[0, 1, 2], hydrated_source_files=())  # type: ignore[call-arg]
    assert "Not all elements of the iterable have type" in str(exc)

    # Test post-hydration validation
    with pytest.raises(ValueError) as exc:
        hydrate_field(raw_source_files=["*.js"], hydrated_source_files=("not_haskell.js",))
    assert "Received non-Haskell sources" in str(exc)


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
    # No error upon creating the Target because validation does not happen until a call site
    # hydrates the specific field.
    tgt = HaskellTarget(
        {HaskellGhcExtensions.alias: ["GhcExistentialQuantification", "DoesNotStartWithGhc"]}
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

    union_membership = UnionMembership(OrderedDict({HaskellTarget: OrderedSet([CustomField])}))
    tgt_values = {CustomField.alias: True}
    tgt = HaskellTarget(tgt_values, union_membership=union_membership)
    assert tgt.field_types == (HaskellGhcExtensions, HaskellSources, CustomField)
    assert tgt.core_fields == (HaskellGhcExtensions, HaskellSources)
    assert tgt.plugin_fields == (CustomField,)
    assert tgt.get(CustomField).value is True

    default_tgt = HaskellTarget({}, union_membership=union_membership)
    assert default_tgt.get(CustomField).value is False
