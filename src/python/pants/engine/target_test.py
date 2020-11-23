# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from enum import Enum
from pathlib import PurePath
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pytest
from typing_extensions import final

from pants.engine.addresses import Address
from pants.engine.fs import EMPTY_DIGEST, PathGlobs, Snapshot
from pants.engine.rules import Get, rule
from pants.engine.target import (
    AsyncField,
    AsyncStringSequenceField,
    BoolField,
    Dependencies,
    DictStringToStringField,
    DictStringToStringSequenceField,
    Field,
    FieldSet,
    InvalidFieldChoiceException,
    InvalidFieldException,
    InvalidFieldTypeException,
    RequiredFieldMissingException,
    ScalarField,
    SequenceField,
    Sources,
    StringField,
    StringOrStringSequenceField,
    StringSequenceField,
    Tags,
    Target,
    generate_subtarget,
    generate_subtarget_address,
)
from pants.engine.unions import UnionMembership
from pants.testutil.rule_runner import MockGet, run_rule_with_mocks
from pants.util.collections import ensure_str_list
from pants.util.frozendict import FrozenDict
from pants.util.ordered_set import OrderedSet

# -----------------------------------------------------------------------------------------------
# Test core Field and Target abstractions
# -----------------------------------------------------------------------------------------------


class FortranExtensions(Field):
    alias = "fortran_extensions"
    value: Tuple[str, ...]
    default = ()

    @classmethod
    def compute_value(
        cls, raw_value: Optional[Iterable[str]], *, address: Address
    ) -> Tuple[str, ...]:
        value_or_default = super().compute_value(raw_value, address=address)
        # Add some arbitrary validation to test that hydration/validation works properly.
        bad_extensions = [
            extension for extension in value_or_default if not extension.startswith("Fortran")
        ]
        if bad_extensions:
            raise InvalidFieldException(
                f"The {repr(cls.alias)} field in target {address} expects all elements to be "
                f"prefixed by `Fortran`. Received {bad_extensions}.",
            )
        return tuple(value_or_default)


class UnrelatedField(BoolField):
    alias = "unrelated"
    default = False


class FortranSources(AsyncField):
    alias = "sources"
    value: Optional[Tuple[str, ...]]
    default = None

    @classmethod
    def compute_value(
        cls, raw_value: Optional[Iterable[str]], address: Address
    ) -> Optional[Tuple[str, ...]]:
        value_or_default = super().compute_value(raw_value, address=address)
        if value_or_default is None:
            return None
        return tuple(ensure_str_list(value_or_default))


@dataclass(frozen=True)
class FortranSourcesRequest:
    field: FortranSources


@dataclass(frozen=True)
class FortranSourcesResult:
    snapshot: Snapshot


@rule
async def hydrate_fortran_sources(request: FortranSourcesRequest) -> FortranSourcesResult:
    sources_field = request.field
    result = await Get(Snapshot, PathGlobs(sources_field.value or ()))
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
    alias = "fortran"
    core_fields = (FortranExtensions, FortranSources)


def test_invalid_fields_rejected() -> None:
    with pytest.raises(InvalidFieldException) as exc:
        FortranTarget({"invalid_field": True}, address=Address("", target_name="lib"))
    assert "Unrecognized field `invalid_field=True`" in str(exc)
    assert "//:lib" in str(exc)


def test_get_field() -> None:
    extensions = ("FortranExt1",)
    tgt = FortranTarget(
        {FortranExtensions.alias: extensions}, address=Address("", target_name="lib")
    )

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
    default_field_tgt = FortranTarget({}, address=Address("", target_name="default"))
    assert default_field_tgt[FortranExtensions].value == ()
    assert default_field_tgt.get(FortranExtensions).value == ()
    assert default_field_tgt.get(FortranExtensions, default_raw_value=["FortranExt2"]).value == ()
    # Example of a call site applying its own default value instead of the field's default value.
    assert default_field_tgt[FortranExtensions].value or 123 == 123

    assert (
        FortranTarget.class_get_field(FortranExtensions, union_membership=UnionMembership({}))
        is FortranExtensions
    )

    # Field is not registered on the target.
    with pytest.raises(KeyError) as exc:
        default_field_tgt[UnrelatedField]
    assert UnrelatedField.__name__ in str(exc)

    with pytest.raises(KeyError) as exc:
        FortranTarget.class_get_field(UnrelatedField, union_membership=UnionMembership({}))
    assert UnrelatedField.__name__ in str(exc)

    assert default_field_tgt.get(UnrelatedField).value == UnrelatedField.default
    assert default_field_tgt.get(
        UnrelatedField, default_raw_value=not UnrelatedField.default
    ).value == (not UnrelatedField.default)


def test_field_hydration_is_eager() -> None:
    with pytest.raises(InvalidFieldException) as exc:
        FortranTarget(
            {FortranExtensions.alias: ["FortranExt1", "DoesNotStartWithFortran"]},
            address=Address("", target_name="bad_extension"),
        )
    assert "DoesNotStartWithFortran" in str(exc)
    assert "//:bad_extension" in str(exc)


def test_has_fields() -> None:
    empty_union_membership = UnionMembership({})
    tgt = FortranTarget({}, address=Address("", target_name="lib"))

    assert tgt.field_types == (FortranExtensions, FortranSources)
    assert FortranTarget.class_field_types(union_membership=empty_union_membership) == (
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
            {FortranSources.alias: raw_source_files}, address=Address("", target_name="lib")
        )[FortranSources]
        result: FortranSourcesResult = run_rule_with_mocks(
            hydrate_fortran_sources,
            rule_args=[FortranSourcesRequest(sources_field)],
            mock_gets=[
                MockGet(
                    output_type=Snapshot,
                    input_type=PathGlobs,
                    mock=lambda _: Snapshot(EMPTY_DIGEST, files=hydrated_source_files, dirs=()),
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

    # Test that `raw_value` gets hydrated/validated eagerly.
    with pytest.raises(ValueError) as exc:
        FortranTarget({FortranSources.alias: [0, 1, 2]}, address=Address("", target_name="lib"))
    assert "Not all elements of the iterable have type" in str(exc)

    # Test post-hydration validation.
    with pytest.raises(ValueError) as exc:
        hydrate_field(raw_source_files=["*.js"], hydrated_source_files=("not_fortran.js",))
    assert "Received non-Fortran sources" in str(exc)
    assert "//:lib" in str(exc)


def test_add_custom_fields() -> None:
    class CustomField(BoolField):
        alias = "custom_field"
        default = False

    union_membership = UnionMembership.from_rules(
        [FortranTarget.register_plugin_field(CustomField)]
    )
    tgt_values = {CustomField.alias: True}
    tgt = FortranTarget(
        tgt_values, address=Address("", target_name="lib"), union_membership=union_membership
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
    assert (
        FortranTarget.class_get_field(CustomField, union_membership=union_membership) is CustomField
    )

    assert tgt[CustomField].value is True

    default_tgt = FortranTarget(
        {}, address=Address("", target_name="default"), union_membership=union_membership
    )
    assert default_tgt[CustomField].value is False

    # Ensure that the `PluginField` is not being registered on other target types.
    class OtherTarget(Target):
        alias = "other_target"
        core_fields = ()

    other_tgt = OtherTarget({}, address=Address("", target_name="other"))
    assert other_tgt.plugin_fields == ()
    assert other_tgt.has_field(CustomField) is False


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
        banned_extensions = ("FortranBannedExt",)
        default_extensions = ("FortranCustomExt",)

        @classmethod
        def compute_value(
            cls, raw_value: Optional[Iterable[str]], *, address: Address
        ) -> Tuple[str, ...]:
            # Ensure that we avoid certain problematic extensions and always use some defaults.
            specified_extensions = super().compute_value(raw_value, address=address)
            banned = [
                extension
                for extension in specified_extensions
                if extension in cls.banned_extensions
            ]
            if banned:
                raise InvalidFieldException(
                    f"The {repr(cls.alias)} field in target {address} is using banned "
                    f"extensions: {banned}"
                )
            return (*specified_extensions, *cls.default_extensions)

    class CustomFortranTarget(Target):
        alias = "custom_fortran"
        core_fields = tuple(
            {*FortranTarget.core_fields, CustomFortranExtensions} - {FortranExtensions}
        )

    custom_tgt = CustomFortranTarget(
        {FortranExtensions.alias: ["FortranExt1"]}, address=Address("", target_name="custom")
    )

    assert custom_tgt.has_field(FortranExtensions) is True
    assert custom_tgt.has_field(CustomFortranExtensions) is True
    assert custom_tgt.has_fields([FortranExtensions, CustomFortranExtensions]) is True
    assert (
        CustomFortranTarget.class_get_field(FortranExtensions, union_membership=UnionMembership({}))
        is CustomFortranExtensions
    )

    # Ensure that subclasses not defined on a target are not accepted. This allows us to, for
    # example, filter every target with `PythonSources` (or a subclass) and to ignore targets with
    # only `Sources`.
    normal_tgt = FortranTarget({}, address=Address("", target_name="normal"))
    assert normal_tgt.has_field(FortranExtensions) is True
    assert normal_tgt.has_field(CustomFortranExtensions) is False

    assert custom_tgt[FortranExtensions] == custom_tgt[CustomFortranExtensions]
    assert custom_tgt[FortranExtensions].value == (
        "FortranExt1",
        *CustomFortranExtensions.default_extensions,
    )

    # Check custom default value
    assert (
        CustomFortranTarget({}, address=Address("", target_name="default"))[FortranExtensions].value
        == CustomFortranExtensions.default_extensions
    )

    # Custom validation
    with pytest.raises(InvalidFieldException) as exc:
        CustomFortranTarget(
            {FortranExtensions.alias: CustomFortranExtensions.banned_extensions},
            address=Address("", target_name="invalid"),
        )
    assert str(list(CustomFortranExtensions.banned_extensions)) in str(exc)
    assert "//:invalid" in str(exc)


def test_required_field() -> None:
    class RequiredPrimitiveField(StringField):
        alias = "primitive"
        required = True

    class RequiredAsyncField(AsyncField):
        alias = "async"
        required = True

        @final
        @property
        def request(self):
            raise NotImplementedError

    class RequiredTarget(Target):
        alias = "required_target"
        core_fields = (RequiredPrimitiveField, RequiredAsyncField)

    address = Address("", target_name="lib")

    # No errors when all defined
    RequiredTarget({"primitive": "present", "async": 0}, address=address)

    with pytest.raises(RequiredFieldMissingException) as exc:
        RequiredTarget({"primitive": "present"}, address=address)
    assert str(address) in str(exc.value)
    assert "async" in str(exc.value)

    with pytest.raises(RequiredFieldMissingException) as exc:
        RequiredTarget({"async": 0}, address=address)
    assert str(address) in str(exc.value)
    assert "primitive" in str(exc.value)


# -----------------------------------------------------------------------------------------------
# Test generated subtargets
# -----------------------------------------------------------------------------------------------


def test_generate_subtarget() -> None:
    class MockTarget(Target):
        alias = "mock_target"
        core_fields = (Dependencies, Tags, Sources)

    # When the target already only has a single source, the result should be the same, except for a
    # different address.
    single_source_tgt = MockTarget(
        {Sources.alias: ["demo.f95"], Tags.alias: ["demo"]},
        address=Address("src/fortran", target_name="demo"),
    )
    expected_single_source_address = Address(
        "src/fortran", relative_file_path="demo.f95", target_name="demo"
    )
    assert generate_subtarget(
        single_source_tgt, full_file_name="src/fortran/demo.f95"
    ) == MockTarget(
        {Sources.alias: ["demo.f95"], Tags.alias: ["demo"]}, address=expected_single_source_address
    )
    assert (
        generate_subtarget_address(single_source_tgt.address, full_file_name="src/fortran/demo.f95")
        == expected_single_source_address
    )

    subdir_tgt = MockTarget(
        {Sources.alias: ["demo.f95", "subdir/demo.f95"]},
        address=Address("src/fortran", target_name="demo"),
    )
    expected_subdir_address = Address(
        "src/fortran", relative_file_path="subdir/demo.f95", target_name="demo"
    )
    assert generate_subtarget(
        subdir_tgt, full_file_name="src/fortran/subdir/demo.f95"
    ) == MockTarget({Sources.alias: ["subdir/demo.f95"]}, address=expected_subdir_address)
    assert (
        generate_subtarget_address(subdir_tgt.address, full_file_name="src/fortran/subdir/demo.f95")
        == expected_subdir_address
    )

    # The full_file_name must match the filespec of the BUILD target's Sources field.
    with pytest.raises(ValueError) as exc:
        generate_subtarget(single_source_tgt, full_file_name="src/fortran/fake_file.f95")
    assert "does not match a file src/fortran/fake_file.f95" in str(exc.value)

    class MissingFieldsTarget(Target):
        alias = "missing_fields_tgt"
        core_fields = (Tags,)

    missing_fields_tgt = MissingFieldsTarget(
        {Tags.alias: ["demo"]}, address=Address("", target_name="missing_fields")
    )
    with pytest.raises(ValueError) as exc:
        generate_subtarget(missing_fields_tgt, full_file_name="fake.txt")
    assert "does not have both a `dependencies` and `sources` field" in str(exc.value)


# -----------------------------------------------------------------------------------------------
# Test FieldSet. Also see engine/internals/graph_test.py.
# -----------------------------------------------------------------------------------------------


def test_field_set() -> None:
    class UnrelatedField(StringField):
        alias = "unrelated_field"
        default = "default"
        value: str

    class UnrelatedTarget(Target):
        alias = "unrelated_target"
        core_fields = (UnrelatedField,)

    class NoFieldsTarget(Target):
        alias = "no_fields_target"
        core_fields = ()

    @dataclass(frozen=True)
    class FortranFieldSet(FieldSet):
        required_fields = (FortranSources,)

        sources: FortranSources
        unrelated_field: UnrelatedField

    @dataclass(frozen=True)
    class UnrelatedFieldSet(FieldSet):
        required_fields = ()

        unrelated_field: UnrelatedField

    fortran_addr = Address("", target_name="fortran")
    fortran_tgt = FortranTarget({}, address=fortran_addr)
    unrelated_addr = Address("", target_name="unrelated")
    unrelated_tgt = UnrelatedTarget({UnrelatedField.alias: "configured"}, address=unrelated_addr)
    no_fields_addr = Address("", target_name="no_fields")
    no_fields_tgt = NoFieldsTarget({}, address=no_fields_addr)

    assert FortranFieldSet.is_applicable(fortran_tgt) is True
    assert FortranFieldSet.is_applicable(unrelated_tgt) is False
    assert FortranFieldSet.is_applicable(no_fields_tgt) is False
    # When no fields are required, every target is applicable.
    for tgt in [fortran_tgt, unrelated_tgt, no_fields_tgt]:
        assert UnrelatedFieldSet.is_applicable(tgt) is True

    valid_fortran_field_set = FortranFieldSet.create(fortran_tgt)
    assert valid_fortran_field_set.address == fortran_addr
    assert valid_fortran_field_set.unrelated_field.value == UnrelatedField.default
    with pytest.raises(KeyError):
        FortranFieldSet.create(unrelated_tgt)

    assert UnrelatedFieldSet.create(unrelated_tgt).unrelated_field.value == "configured"
    assert UnrelatedFieldSet.create(no_fields_tgt).unrelated_field.value == UnrelatedField.default


# -----------------------------------------------------------------------------------------------
# Test Field templates
# -----------------------------------------------------------------------------------------------


def test_scalar_field() -> None:
    @dataclass(frozen=True)
    class CustomObject:
        pass

    class Example(ScalarField):
        alias = "example"
        expected_type = CustomObject
        expected_type_description = "a `CustomObject` instance"

        @classmethod
        def compute_value(
            cls, raw_value: Optional[CustomObject], *, address: Address
        ) -> Optional[CustomObject]:
            return super().compute_value(raw_value, address=address)

    addr = Address("", target_name="example")

    with pytest.raises(InvalidFieldTypeException) as exc:
        Example(1, address=addr)
    assert Example.expected_type_description in str(exc.value)

    assert Example(CustomObject(), address=addr).value == CustomObject()
    assert Example(None, address=addr).value is None


def test_string_field_valid_choices() -> None:
    class GivenStrings(StringField):
        alias = "example"
        valid_choices = ("kale", "spinach")

    class LeafyGreens(Enum):
        KALE = "kale"
        SPINACH = "spinach"

    class GivenEnum(StringField):
        alias = "example"
        valid_choices = LeafyGreens
        default = LeafyGreens.KALE.value

    addr = Address("", target_name="example")
    assert GivenStrings("spinach", address=addr).value == "spinach"
    assert GivenEnum("spinach", address=addr).value == "spinach"

    assert GivenStrings(None, address=addr).value is None
    assert GivenEnum(None, address=addr).value == "kale"

    with pytest.raises(InvalidFieldChoiceException):
        GivenStrings("carrot", address=addr)
    with pytest.raises(InvalidFieldChoiceException):
        GivenEnum("carrot", address=addr)


def test_sequence_field() -> None:
    @dataclass(frozen=True)
    class CustomObject:
        pass

    class Example(SequenceField):
        alias = "example"
        expected_element_type = CustomObject
        expected_type_description = "an iterable of `CustomObject` instances"

        @classmethod
        def compute_value(
            cls, raw_value: Optional[Iterable[CustomObject]], *, address: Address
        ) -> Optional[Tuple[CustomObject, ...]]:
            return super().compute_value(raw_value, address=address)

    addr = Address("", target_name="example")

    def assert_flexible_constructor(raw_value: Iterable[CustomObject]) -> None:
        assert Example(raw_value, address=addr).value == tuple(raw_value)

    assert_flexible_constructor([CustomObject(), CustomObject()])
    assert_flexible_constructor((CustomObject(), CustomObject()))
    assert_flexible_constructor(OrderedSet([CustomObject(), CustomObject()]))

    # Must be given a sequence, not a single element.
    with pytest.raises(InvalidFieldTypeException) as exc:
        Example(CustomObject(), address=addr)
    assert Example.expected_type_description in str(exc.value)

    # All elements must be the expected type.
    with pytest.raises(InvalidFieldTypeException):
        Example([CustomObject(), 1, CustomObject()], address=addr)


def test_string_sequence_field() -> None:
    class Example(StringSequenceField):
        alias = "example"

    addr = Address("", target_name="example")
    assert Example(["hello", "world"], address=addr).value == ("hello", "world")
    assert Example(None, address=addr).value is None
    with pytest.raises(InvalidFieldTypeException):
        Example("strings are technically iterable...", address=addr)
    with pytest.raises(InvalidFieldTypeException):
        Example(["hello", 0, "world"], address=addr)


def test_string_or_string_sequence_field() -> None:
    class Example(StringOrStringSequenceField):
        alias = "example"

    addr = Address("", target_name="example")
    assert Example(["hello", "world"], address=addr).value == ("hello", "world")
    assert Example("hello world", address=addr).value == ("hello world",)
    with pytest.raises(InvalidFieldTypeException):
        Example(["hello", 0, "world"], address=addr)


def test_dict_string_to_string_field() -> None:
    class Example(DictStringToStringField):
        alias = "example"

    addr = Address("", target_name="example")

    assert Example(None, address=addr).value is None
    assert Example({}, address=addr).value == FrozenDict()
    assert Example({"hello": "world"}, address=addr).value == FrozenDict({"hello": "world"})

    def assert_invalid_type(raw_value: Any) -> None:
        with pytest.raises(InvalidFieldTypeException):
            Example(raw_value, address=addr)

    for v in [0, object(), "hello", ["hello"], {"hello": 0}, {0: "world"}]:
        assert_invalid_type(v)

    # Regression test that a default can be set.
    class ExampleDefault(DictStringToStringField):
        alias = "example"
        # Note that we use `FrozenDict` so that the object can be hashable.
        default = FrozenDict({"default": "val"})

    assert ExampleDefault(None, address=addr).value == FrozenDict({"default": "val"})


def test_dict_string_to_string_sequence_field() -> None:
    class Example(DictStringToStringSequenceField):
        alias = "example"

    addr = Address("", target_name="example")

    def assert_flexible_constructor(raw_value: Dict[str, Iterable[str]]) -> None:
        assert Example(raw_value, address=addr).value == FrozenDict(
            {k: tuple(v) for k, v in raw_value.items()}
        )

    for v in [("hello", "world"), ["hello", "world"], OrderedSet(["hello", "world"])]:
        assert_flexible_constructor({"greeting": v})

    def assert_invalid_type(raw_value: Any) -> None:
        with pytest.raises(InvalidFieldTypeException):
            Example(raw_value, address=addr)

    for v in [  # type: ignore[assignment]
        0,
        object(),
        "hello",
        ["hello"],
        {"hello": "world"},
        {0: ["world"]},
    ]:
        assert_invalid_type(v)

    # Regression test that a default can be set.
    class ExampleDefault(DictStringToStringSequenceField):
        alias = "example"
        # Note that we use `FrozenDict` so that the object can be hashable.
        default = FrozenDict({"default": ("val",)})

    assert ExampleDefault(None, address=addr).value == FrozenDict({"default": ("val",)})


def test_async_string_sequence_field() -> None:
    class Example(AsyncStringSequenceField):
        alias = "example"

    addr = Address("", target_name="example")
    assert Example(["hello", "world"], address=addr).value == ("hello", "world")
    assert Example(None, address=addr).value is None
    with pytest.raises(InvalidFieldTypeException):
        Example("strings are technically iterable...", address=addr)
    with pytest.raises(InvalidFieldTypeException):
        Example(["hello", 0, "world"], address=addr)
