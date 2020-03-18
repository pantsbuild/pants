# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from pathlib import PurePath
from typing import ClassVar, Iterable, List, Optional, Tuple

import pytest
from typing_extensions import final

from pants.base.exceptions import TargetDefinitionException
from pants.build_graph.address import Address
from pants.engine.fs import EMPTY_DIRECTORY_DIGEST, PathGlobs, Snapshot
from pants.engine.rules import UnionMembership, rule
from pants.engine.selectors import Get
from pants.engine.target import AsyncField, BoolField, PrimitiveField, Target
from pants.testutil.engine.util import MockGet, run_rule
from pants.util.collections import ensure_str_list
from pants.util.ordered_set import OrderedSet


class HaskellGhcExtensions(PrimitiveField):
    alias: ClassVar = "ghc_extensions"
    value: Tuple[str, ...]

    def hydrate(self, raw_value: Optional[Iterable[str]], *, address: Address) -> Tuple[str, ...]:
        if raw_value is None:
            return ()
        # Add some arbitrary validation to test that hydration/validation works properly.
        bad_extensions = [extension for extension in raw_value if not extension.startswith("Ghc")]
        if bad_extensions:
            raise TargetDefinitionException(
                address,
                f"All elements of `{self.alias}` must be prefixed by `Ghc`. Received "
                f"{bad_extensions}.",
            )
        return tuple(raw_value)


class UnrelatedField(BoolField):
    alias: ClassVar = "unrelated"
    default: ClassVar = False


class HaskellSources(AsyncField):
    alias: ClassVar = "sources"
    sanitized_raw_value: Optional[Tuple[str, ...]]

    def sanitize_raw_value(self, raw_value: Optional[Iterable[str]]) -> Optional[Tuple[str, ...]]:
        if raw_value is None:
            return None
        return tuple(ensure_str_list(raw_value))

    @final
    @property
    def request(self) -> "HaskellSourcesRequest":
        return HaskellSourcesRequest(self)


@dataclass(frozen=True)
class HaskellSourcesRequest:
    field: HaskellSources


@dataclass(frozen=True)
class HaskellSourcesResult:
    snapshot: Snapshot


@rule
async def hydrate_haskell_sources(request: HaskellSourcesRequest) -> HaskellSourcesResult:
    sources_field = request.field
    result = await Get[Snapshot](PathGlobs(sources_field.sanitized_raw_value))
    # Validate after hydration
    non_haskell_sources = [fp for fp in result.files if PurePath(fp).suffix != ".hs"]
    if non_haskell_sources:
        raise ValueError(
            f"Received non-Haskell sources in {sources_field.alias} for target "
            f"{sources_field.address}: {non_haskell_sources}."
        )
    return HaskellSourcesResult(result)


class HaskellTarget(Target):
    alias: ClassVar = "haskell"
    core_fields: ClassVar = (HaskellGhcExtensions, HaskellSources)


def test_invalid_fields_rejected() -> None:
    with pytest.raises(TargetDefinitionException) as exc:
        HaskellTarget({"invalid_field": True}, address=Address.parse(":lib"))
    assert "Unrecognized field `invalid_field=True`" in str(exc)


def test_get_primitive_field() -> None:
    extensions = ("GhcExistentialQuantification",)
    assert (
        HaskellTarget({HaskellGhcExtensions.alias: extensions}, address=Address.parse(":lib"))
        .get(HaskellGhcExtensions)
        .value
        == extensions
    )

    # Default value
    assert (
        HaskellTarget({}, address=Address.parse(":default")).get(HaskellGhcExtensions).value == ()
    )


def test_get_async_field() -> None:
    def hydrate_field(
        *, raw_source_files: List[str], hydrated_source_files: Tuple[str, ...]
    ) -> HaskellSourcesResult:
        sources_field = HaskellTarget(
            {HaskellSources.alias: raw_source_files}, address=Address.parse(":lib")
        ).get(HaskellSources)
        result: HaskellSourcesResult = run_rule(
            hydrate_haskell_sources,
            rule_args=[HaskellSourcesRequest(sources_field)],
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

    # Test `raw_value` gets sanitized/validated eagerly
    with pytest.raises(ValueError) as exc:
        HaskellTarget({HaskellSources.alias: [0, 1, 2]}, address=Address.parse(":lib")).get(
            HaskellSources
        )
    assert "Not all elements of the iterable have type" in str(exc)

    # Test post-hydration validation
    with pytest.raises(ValueError) as exc:
        hydrate_field(raw_source_files=["*.js"], hydrated_source_files=("not_haskell.js",))
    assert "Received non-Haskell sources" in str(exc)
    assert "//:lib" in str(exc)


def test_maybe_get_field() -> None:
    tgt = HaskellTarget({}, address=Address.parse(":lib"))
    assert tgt.get(HaskellGhcExtensions) == tgt.maybe_get(HaskellGhcExtensions)
    assert tgt.get(HaskellSources) == tgt.maybe_get(HaskellSources)
    assert tgt.maybe_get(UnrelatedField) is None


def test_has_fields() -> None:
    empty_union_membership = UnionMembership({})
    tgt = HaskellTarget({}, address=Address.parse(":lib"))
    assert tgt.has_fields([]) is True
    assert HaskellTarget.class_has_fields([], union_membership=empty_union_membership) is True

    assert tgt.has_fields([HaskellGhcExtensions]) is True
    assert tgt.has_field(HaskellGhcExtensions) is True
    assert (
        HaskellTarget.class_has_fields(
            [HaskellGhcExtensions], union_membership=empty_union_membership
        )
        is True
    )
    assert (
        HaskellTarget.class_has_field(HaskellGhcExtensions, union_membership=empty_union_membership)
        is True
    )

    assert tgt.has_fields([UnrelatedField]) is False
    assert tgt.has_field(UnrelatedField) is False
    assert (
        HaskellTarget.class_has_fields([UnrelatedField], union_membership=empty_union_membership)
        is False
    )
    assert (
        HaskellTarget.class_has_field(UnrelatedField, union_membership=empty_union_membership)
        is False
    )

    assert tgt.has_fields([HaskellGhcExtensions, UnrelatedField]) is False
    assert (
        HaskellTarget.class_has_fields(
            [HaskellGhcExtensions, UnrelatedField], union_membership=empty_union_membership
        )
        is False
    )


def test_primitive_field_hydration_is_eager() -> None:
    with pytest.raises(TargetDefinitionException) as exc:
        HaskellTarget(
            {HaskellGhcExtensions.alias: ["GhcExistentialQuantification", "DoesNotStartWithGhc"]},
            address=Address.parse(":bad_extension"),
        )
    assert "must be prefixed by `Ghc`" in str(exc)
    assert "//:bad_extension" in str(exc)


def test_add_custom_fields() -> None:
    class CustomField(BoolField):
        alias: ClassVar = "custom_field"
        default: ClassVar = False

    union_membership = UnionMembership({HaskellTarget.PluginField: OrderedSet([CustomField])})
    tgt_values = {CustomField.alias: True}
    tgt = HaskellTarget(
        tgt_values, address=Address.parse(":lib"), union_membership=union_membership
    )

    assert tgt.field_types == (HaskellGhcExtensions, HaskellSources, CustomField)
    assert tgt.core_fields == (HaskellGhcExtensions, HaskellSources)
    assert tgt.plugin_fields == (CustomField,)
    assert tgt.has_field(CustomField) is True
    assert HaskellTarget.class_has_field(CustomField, union_membership=union_membership) is True

    assert tgt.get(CustomField).value is True

    default_tgt = HaskellTarget(
        {}, address=Address.parse(":default"), union_membership=union_membership
    )
    assert default_tgt.get(CustomField).value is False


def test_override_preexisting_field_via_new_target() -> None:
    # To change the behavior of a pre-existing field, you must create a new target as it would not
    # be safe to allow plugin authors to change the behavior of core target types.
    #
    # Because the Target API does not care about the actual target type and we only check that the
    # target has the required fields via Target.has_fields(), it is safe to create a new target
    # that still works where the original target was expected.
    #
    # However, this means that we must ensure `Target.get()` and `Target.has_fields()` will work
    # with subclasses of the original `Field`s.

    class CustomHaskellGhcExtensions(HaskellGhcExtensions):
        banned_extensions: ClassVar = ("GhcBanned",)
        default_extensions: ClassVar = ("GhcCustomExtension",)

        def hydrate(
            self, raw_value: Optional[Iterable[str]], *, address: Address
        ) -> Tuple[str, ...]:
            # Ensure that we avoid certain problematic extensions and always use some defaults.
            specified_extensions = super().hydrate(raw_value, address=address)
            banned = [
                extension
                for extension in specified_extensions
                if extension in self.banned_extensions
            ]
            if banned:
                raise TargetDefinitionException(
                    address, f"Banned extensions used for {self.alias}: {banned}."
                )
            return (*specified_extensions, *self.default_extensions)

    class CustomHaskellTarget(Target):
        alias: ClassVar = "custom_haskell"
        core_fields: ClassVar = tuple(
            {*HaskellTarget.core_fields, CustomHaskellGhcExtensions} - {HaskellGhcExtensions}
        )

    custom_tgt = CustomHaskellTarget(
        {HaskellGhcExtensions.alias: ["GhcNormalExtension"]}, address=Address.parse(":custom")
    )

    assert custom_tgt.has_field(HaskellGhcExtensions) is True
    assert custom_tgt.has_field(CustomHaskellGhcExtensions) is True
    assert custom_tgt.has_fields([HaskellGhcExtensions, CustomHaskellGhcExtensions]) is True

    # Ensure that subclasses not defined on a target are not accepted. This allows us to, for
    # example, filter every target with `PythonSources` (or a subclass) and to ignore targets with
    # only `Sources`.
    normal_tgt = HaskellTarget({}, address=Address.parse(":normal"))
    assert normal_tgt.has_field(HaskellGhcExtensions) is True
    assert normal_tgt.has_field(CustomHaskellGhcExtensions) is False

    assert custom_tgt.get(HaskellGhcExtensions) == custom_tgt.get(CustomHaskellGhcExtensions)
    assert custom_tgt.get(HaskellGhcExtensions).value == (
        "GhcNormalExtension",
        *CustomHaskellGhcExtensions.default_extensions,
    )

    # Check custom default value
    assert (
        CustomHaskellTarget({}, address=Address.parse(":default")).get(HaskellGhcExtensions).value
        == CustomHaskellGhcExtensions.default_extensions
    )

    # Custom validation
    with pytest.raises(TargetDefinitionException) as exc:
        CustomHaskellTarget(
            {HaskellGhcExtensions.alias: CustomHaskellGhcExtensions.banned_extensions},
            address=Address.parse(":invalid"),
        )
    assert str(list(CustomHaskellGhcExtensions.banned_extensions)) in str(exc)
    assert "//:invalid" in str(exc)
