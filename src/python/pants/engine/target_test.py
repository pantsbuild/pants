# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from pathlib import PurePath
from typing import ClassVar, Iterable, List, Optional, Tuple

import pytest
from typing_extensions import final

from pants.build_graph.address import Address
from pants.engine.fs import EMPTY_DIRECTORY_DIGEST, PathGlobs, Snapshot
from pants.engine.rules import UnionMembership, rule
from pants.engine.selectors import Get
from pants.engine.target import AsyncField, BoolField, InvalidFieldException, PrimitiveField, Target
from pants.testutil.engine.util import MockGet, run_rule
from pants.util.collections import ensure_str_list
from pants.util.ordered_set import OrderedSet


class FortranExtensions(PrimitiveField):
    alias: ClassVar = "fortran_extensions"
    value: Tuple[str, ...]
    default: ClassVar[Tuple[str, ...]] = ()

    def compute_value(
        self, raw_value: Optional[Iterable[str]], *, address: Address
    ) -> Tuple[str, ...]:
        value_or_default = super().compute_value(raw_value, address=address)
        # Add some arbitrary validation to test that hydration/validation works properly.
        bad_extensions = [
            extension for extension in value_or_default if not extension.startswith("Fortran")
        ]
        if bad_extensions:
            raise InvalidFieldException(
                f"The {repr(self.alias)} field in target {address} expects all elements to be "
                f"prefixed by `Fortran`. Received {bad_extensions}.",
            )
        return tuple(value_or_default)


class UnrelatedField(BoolField):
    alias: ClassVar = "unrelated"
    default: ClassVar = False


class FortranSources(AsyncField):
    alias: ClassVar = "sources"
    sanitized_raw_value: Optional[Tuple[str, ...]]
    default = None

    @classmethod
    def sanitize_raw_value(
        cls, raw_value: Optional[Iterable[str]], address: Address
    ) -> Optional[Tuple[str, ...]]:
        value_or_default = super().sanitize_raw_value(raw_value, address=address)
        if value_or_default is None:
            return None
        return tuple(ensure_str_list(value_or_default))

    @final
    @property
    def request(self) -> "FortranSourcesRequest":
        return FortranSourcesRequest(self)


@dataclass(frozen=True)
class FortranSourcesRequest:
    field: FortranSources


@dataclass(frozen=True)
class FortranSourcesResult:
    snapshot: Snapshot


@rule
async def hydrate_fortran_sources(request: FortranSourcesRequest) -> FortranSourcesResult:
    sources_field = request.field
    result = await Get[Snapshot](PathGlobs(sources_field.sanitized_raw_value))
    # Validate after hydration
    non_fortran_sources = [
        fp for fp in result.files if PurePath(fp).suffix not in (".f95", ".f03", ".f08")
    ]
    if non_fortran_sources:
        raise ValueError(
            f"Received non-Fortran sources in {sources_field.alias} for target "
            f"{sources_field.address}: {non_fortran_sources}."
        )
    return FortranSourcesResult(result)


class FortranTarget(Target):
    alias: ClassVar = "fortran"
    core_fields: ClassVar = (FortranExtensions, FortranSources)


def test_invalid_fields_rejected() -> None:
    with pytest.raises(InvalidFieldException) as exc:
        FortranTarget({"invalid_field": True}, address=Address.parse(":lib"))
    assert "Unrecognized field `invalid_field=True`" in str(exc)
    assert "//:lib" in str(exc)


def test_get_field() -> None:
    extensions = ("FortranExt1",)
    tgt = FortranTarget({FortranExtensions.alias: extensions}, address=Address.parse(":lib"))

    assert tgt[FortranExtensions].value == extensions
    assert tgt.get(FortranExtensions).value == extensions
    assert tgt.get(FortranExtensions, default_raw_value=["FortranExt2"]).value == extensions

    # Default field value. This happens when the field is registered on the target type, but the
    # user does not explicitly set the field in the BUILD file.
    #
    # NB: `default_raw_value` is not used in this case - that parameter is solely used when
    # the field is not registered on the target type. To override the default field value, either
    # subclass the Field and create a new target, or, in your call site, interpret the result and
    # and apply your default.
    default_field_tgt = FortranTarget({}, address=Address.parse(":default"))
    assert default_field_tgt[FortranExtensions].value == ()
    assert default_field_tgt.get(FortranExtensions).value == ()
    assert default_field_tgt.get(FortranExtensions, default_raw_value=["FortranExt2"]).value == ()
    # Example of a call site applying its own default value instead of the field's default value.
    assert default_field_tgt[FortranExtensions].value or 123 == 123

    # Field is not registered on the target.
    with pytest.raises(KeyError) as exc:
        default_field_tgt[UnrelatedField]
    assert UnrelatedField.__name__ in str(exc)
    assert default_field_tgt.get(UnrelatedField).value == UnrelatedField.default
    assert default_field_tgt.get(
        UnrelatedField, default_raw_value=not UnrelatedField.default
    ).value == (not UnrelatedField.default)


def test_primitive_field_hydration_is_eager() -> None:
    with pytest.raises(InvalidFieldException) as exc:
        FortranTarget(
            {FortranExtensions.alias: ["FortranExt1", "DoesNotStartWithFortran"]},
            address=Address.parse(":bad_extension"),
        )
    assert "DoesNotStartWithFortran" in str(exc)
    assert "//:bad_extension" in str(exc)


def test_has_fields() -> None:
    empty_union_membership = UnionMembership({})
    tgt = FortranTarget({}, address=Address.parse(":lib"))

    assert tgt.field_types == (FortranExtensions, FortranSources)
    assert tgt.class_field_types(union_membership=empty_union_membership) == (
        FortranExtensions,
        FortranSources,
    )

    assert tgt.has_fields([]) is True
    assert FortranTarget.class_has_fields([], union_membership=empty_union_membership) is True

    assert tgt.has_fields([FortranExtensions]) is True
    assert tgt.has_field(FortranExtensions) is True
    assert (
        FortranTarget.class_has_fields([FortranExtensions], union_membership=empty_union_membership)
        is True
    )
    assert (
        FortranTarget.class_has_field(FortranExtensions, union_membership=empty_union_membership)
        is True
    )

    assert tgt.has_fields([UnrelatedField]) is False
    assert tgt.has_field(UnrelatedField) is False
    assert (
        FortranTarget.class_has_fields([UnrelatedField], union_membership=empty_union_membership)
        is False
    )
    assert (
        FortranTarget.class_has_field(UnrelatedField, union_membership=empty_union_membership)
        is False
    )

    assert tgt.has_fields([FortranExtensions, UnrelatedField]) is False
    assert (
        FortranTarget.class_has_fields(
            [FortranExtensions, UnrelatedField], union_membership=empty_union_membership
        )
        is False
    )


def test_async_field() -> None:
    def hydrate_field(
        *, raw_source_files: List[str], hydrated_source_files: Tuple[str, ...]
    ) -> FortranSourcesResult:
        sources_field = FortranTarget(
            {FortranSources.alias: raw_source_files}, address=Address.parse(":lib")
        )[FortranSources]
        result: FortranSourcesResult = run_rule(
            hydrate_fortran_sources,
            rule_args=[FortranSourcesRequest(sources_field)],
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
    expected_files = ("important.f95", "big_banks.f08", "big_loans.f08")
    assert (
        hydrate_field(
            raw_source_files=["important.f95", "big_*.f08"], hydrated_source_files=expected_files
        ).snapshot.files
        == expected_files
    )

    # Test that `raw_value` gets sanitized/validated eagerly.
    with pytest.raises(ValueError) as exc:
        FortranTarget({FortranSources.alias: [0, 1, 2]}, address=Address.parse(":lib"))
    assert "Not all elements of the iterable have type" in str(exc)

    # Test post-hydration validation.
    with pytest.raises(ValueError) as exc:
        hydrate_field(raw_source_files=["*.js"], hydrated_source_files=("not_fortran.js",))
    assert "Received non-Fortran sources" in str(exc)
    assert "//:lib" in str(exc)


def test_add_custom_fields() -> None:
    class CustomField(BoolField):
        alias: ClassVar = "custom_field"
        default: ClassVar = False

    union_membership = UnionMembership({FortranTarget.PluginField: OrderedSet([CustomField])})
    tgt_values = {CustomField.alias: True}
    tgt = FortranTarget(
        tgt_values, address=Address.parse(":lib"), union_membership=union_membership
    )

    assert tgt.field_types == (FortranExtensions, FortranSources, CustomField)
    assert tgt.core_fields == (FortranExtensions, FortranSources)
    assert tgt.plugin_fields == (CustomField,)
    assert tgt.has_field(CustomField) is True

    assert FortranTarget.class_field_types(union_membership=union_membership) == (
        FortranExtensions,
        FortranSources,
        CustomField,
    )
    assert FortranTarget.class_has_field(CustomField, union_membership=union_membership) is True

    assert tgt[CustomField].value is True

    default_tgt = FortranTarget(
        {}, address=Address.parse(":default"), union_membership=union_membership
    )
    assert default_tgt[CustomField].value is False


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

    class CustomFortranExtensions(FortranExtensions):
        banned_extensions: ClassVar = ("FortranBannedExt",)
        default_extensions: ClassVar = ("FortranCustomExt",)

        def compute_value(
            self, raw_value: Optional[Iterable[str]], *, address: Address
        ) -> Tuple[str, ...]:
            # Ensure that we avoid certain problematic extensions and always use some defaults.
            specified_extensions = super().compute_value(raw_value, address=address)
            banned = [
                extension
                for extension in specified_extensions
                if extension in self.banned_extensions
            ]
            if banned:
                raise InvalidFieldException(
                    f"The {repr(self.alias)} field in target {address} is using banned "
                    f"extensions: {banned}"
                )
            return (*specified_extensions, *self.default_extensions)

    class CustomFortranTarget(Target):
        alias: ClassVar = "custom_fortran"
        core_fields: ClassVar = tuple(
            {*FortranTarget.core_fields, CustomFortranExtensions} - {FortranExtensions}
        )

    custom_tgt = CustomFortranTarget(
        {FortranExtensions.alias: ["FortranExt1"]}, address=Address.parse(":custom")
    )

    assert custom_tgt.has_field(FortranExtensions) is True
    assert custom_tgt.has_field(CustomFortranExtensions) is True
    assert custom_tgt.has_fields([FortranExtensions, CustomFortranExtensions]) is True

    # Ensure that subclasses not defined on a target are not accepted. This allows us to, for
    # example, filter every target with `PythonSources` (or a subclass) and to ignore targets with
    # only `Sources`.
    normal_tgt = FortranTarget({}, address=Address.parse(":normal"))
    assert normal_tgt.has_field(FortranExtensions) is True
    assert normal_tgt.has_field(CustomFortranExtensions) is False

    assert custom_tgt[FortranExtensions] == custom_tgt[CustomFortranExtensions]
    assert custom_tgt[FortranExtensions].value == (
        "FortranExt1",
        *CustomFortranExtensions.default_extensions,
    )

    # Check custom default value
    assert (
        CustomFortranTarget({}, address=Address.parse(":default"))[FortranExtensions].value
        == CustomFortranExtensions.default_extensions
    )

    # Custom validation
    with pytest.raises(InvalidFieldException) as exc:
        CustomFortranTarget(
            {FortranExtensions.alias: CustomFortranExtensions.banned_extensions},
            address=Address.parse(":invalid"),
        )
    assert str(list(CustomFortranExtensions.banned_extensions)) in str(exc)
    assert "//:invalid" in str(exc)
