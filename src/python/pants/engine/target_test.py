# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from enum import Enum
from pathlib import PurePath
from typing import Any, ClassVar, Dict, Iterable, List, Optional, Tuple, Type

import pytest
from typing_extensions import final

from pants.base.specs import FilesystemLiteralSpec
from pants.engine.addresses import Address
from pants.engine.fs import EMPTY_DIRECTORY_DIGEST, PathGlobs, Snapshot
from pants.engine.rules import RootRule, rule
from pants.engine.scheduler import ExecutionError
from pants.engine.selectors import Get
from pants.engine.target import (
    AsyncField,
    BoolField,
    Configuration,
    ConfigurationWithOrigin,
    DictStringToStringField,
    DictStringToStringSequenceField,
    HydratedSources,
    HydrateSourcesRequest,
    InvalidFieldChoiceException,
    InvalidFieldException,
    InvalidFieldTypeException,
    PrimitiveField,
    RequiredFieldMissingException,
    ScalarField,
    SequenceField,
    Sources,
    StringField,
    StringOrStringSequenceField,
    StringSequenceField,
    Target,
    TargetWithOrigin,
)
from pants.engine.target import rules as target_rules
from pants.engine.unions import UnionMembership
from pants.testutil.engine.util import MockGet, run_rule
from pants.testutil.test_base import TestBase
from pants.util.collections import ensure_str_list
from pants.util.frozendict import FrozenDict
from pants.util.ordered_set import OrderedSet

# -----------------------------------------------------------------------------------------------
# Test core Field and Target abstractions
# -----------------------------------------------------------------------------------------------


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

    address = Address.parse(":lib")

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
# Test Configuration
# -----------------------------------------------------------------------------------------------


def test_configuration() -> None:
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
    class FortranConfiguration(Configuration):
        required_fields = (FortranSources,)

        sources: FortranSources
        unrelated_field: UnrelatedField

    @dataclass(frozen=True)
    class UnrelatedFieldConfiguration(ConfigurationWithOrigin):
        required_fields = ()

        unrelated_field: UnrelatedField

    fortran_addr = Address.parse(":fortran")
    fortran_tgt = FortranTarget({}, address=fortran_addr)
    unrelated_addr = Address.parse(":unrelated")
    unrelated_tgt = UnrelatedTarget({UnrelatedField.alias: "configured"}, address=unrelated_addr)
    no_fields_addr = Address.parse(":no_fields")
    no_fields_tgt = NoFieldsTarget({}, address=no_fields_addr)

    assert FortranConfiguration.is_valid(fortran_tgt) is True
    assert FortranConfiguration.is_valid(unrelated_tgt) is False
    assert FortranConfiguration.is_valid(no_fields_tgt) is False
    # When no fields are required, every target is valid.
    for tgt in [fortran_tgt, unrelated_tgt, no_fields_tgt]:
        assert UnrelatedFieldConfiguration.is_valid(tgt) is True

    valid_fortran_config = FortranConfiguration.create(fortran_tgt)
    assert valid_fortran_config.address == fortran_addr
    assert valid_fortran_config.unrelated_field.value == UnrelatedField.default
    with pytest.raises(KeyError):
        FortranConfiguration.create(unrelated_tgt)

    origin = FilesystemLiteralSpec("f.txt")
    assert (
        UnrelatedFieldConfiguration.create(TargetWithOrigin(fortran_tgt, origin)).origin == origin
    )
    assert (
        UnrelatedFieldConfiguration.create(
            TargetWithOrigin(unrelated_tgt, origin)
        ).unrelated_field.value
        == "configured"
    )
    assert (
        UnrelatedFieldConfiguration.create(
            TargetWithOrigin(no_fields_tgt, origin)
        ).unrelated_field.value
        == UnrelatedField.default
    )


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

    addr = Address.parse(":example")

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

    addr = Address.parse(":example")
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

    addr = Address.parse(":example")

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

    addr = Address.parse(":example")
    assert Example(["hello", "world"], address=addr).value == ("hello", "world")
    assert Example(None, address=addr).value is None
    with pytest.raises(InvalidFieldTypeException):
        Example("strings are technically iterable...", address=addr)
    with pytest.raises(InvalidFieldTypeException):
        Example(["hello", 0, "world"], address=addr)


def test_string_or_string_sequence_field() -> None:
    class Example(StringOrStringSequenceField):
        alias = "example"

    addr = Address.parse(":example")
    assert Example(["hello", "world"], address=addr).value == ("hello", "world")
    assert Example("hello world", address=addr).value == ("hello world",)
    with pytest.raises(InvalidFieldTypeException):
        Example(["hello", 0, "world"], address=addr)


def test_dict_string_to_string_field() -> None:
    class Example(DictStringToStringField):
        alias = "example"

    addr = Address.parse(":example")

    assert Example({"hello": "world"}, address=addr).value == FrozenDict({"hello": "world"})

    def assert_invalid_type(raw_value: Any) -> None:
        with pytest.raises(InvalidFieldTypeException):
            Example(raw_value, address=addr)

    for v in [0, object(), "hello", ["hello"], {"hello": 0}, {0: "world"}]:
        assert_invalid_type(v)


def test_dict_string_to_string_sequence_field() -> None:
    class Example(DictStringToStringSequenceField):
        alias = "example"

    addr = Address.parse(":example")

    def assert_flexible_constructor(raw_value: Dict[str, Iterable[str]]) -> None:
        assert Example(raw_value, address=addr).value == FrozenDict(
            {k: tuple(v) for k, v in raw_value.items()}
        )

    for v in [("hello", "world"), ["hello", "world"], OrderedSet(["hello", "world"])]:
        assert_flexible_constructor({"greeting": v})

    def assert_invalid_type(raw_value: Any) -> None:
        with pytest.raises(InvalidFieldTypeException):
            Example(raw_value, address=addr)

    for v in [0, object(), "hello", ["hello"], {"hello": "world"}, {0: ["world"]}]:
        assert_invalid_type(v)


# -----------------------------------------------------------------------------------------------
# Test common fields
# -----------------------------------------------------------------------------------------------


class TestSources(TestBase):
    @classmethod
    def rules(cls):
        return (*super().rules(), *target_rules(), RootRule(HydrateSourcesRequest))

    def test_raw_value_sanitation(self) -> None:
        addr = Address.parse(":test")

        def assert_flexible_constructor(raw_value: Iterable[str]) -> None:
            assert Sources(raw_value, address=addr).sanitized_raw_value == tuple(raw_value)

        for v in [("f1.txt", "f2.txt"), ["f1.txt", "f2.txt"], OrderedSet(["f1.txt", "f2.txt"])]:
            assert_flexible_constructor(v)

        def assert_invalid_type(raw_value: Any) -> None:
            with pytest.raises(InvalidFieldTypeException):
                Sources(raw_value, address=addr)

        for v in [0, object(), "f1.txt"]:
            assert_invalid_type(v)

    def test_normal_hydration(self) -> None:
        addr = Address.parse("src/fortran:lib")
        self.create_files("src/fortran", files=["f1.f95", "f2.f95", "f1.f03", "ignored.f03"])
        sources = Sources(["f1.f95", "*.f03", "!ignored.f03", "!**/ignore*"], address=addr)
        hydrated_sources = self.request_single_product(HydratedSources, sources.request)
        assert hydrated_sources.snapshot.files == ("src/fortran/f1.f03", "src/fortran/f1.f95")

        # Also test that the Filespec is correct. This does not need hydration to be calculated.
        assert sources.filespec == {
            "globs": ["src/fortran/*.f03", "src/fortran/f1.f95"],
            "exclude": [{"globs": ["src/fortran/**/ignore*", "src/fortran/ignored.f03"]}],
        }

    def test_unmatched_globs(self) -> None:
        self.create_files("", files=["f1.f95"])
        sources = Sources(["non_existent.f95"], address=Address.parse(":lib"))
        with pytest.raises(ExecutionError) as exc:
            self.request_single_product(HydratedSources, sources.request)
        assert "Unmatched glob" in str(exc.value)
        assert "//:lib" in str(exc.value)
        assert "non_existent.f95" in str(exc.value)

    def test_default_globs(self) -> None:
        class DefaultSources(Sources):
            default = ("default.f95", "default.f03", "*.f08", "!ignored.f08")

        addr = Address.parse("src/fortran:lib")
        # NB: Not all globs will be matched with these files, specifically `default.f03` will not
        # be matched. This is intentional to ensure that we use `any` glob conjunction rather
        # than the normal `all` conjunction.
        self.create_files("src/fortran", files=["default.f95", "f1.f08", "ignored.f08"])
        sources = DefaultSources(None, address=addr)
        assert set(sources.sanitized_raw_value) == set(DefaultSources.default)

        hydrated_sources = self.request_single_product(HydratedSources, sources.request)
        assert hydrated_sources.snapshot.files == ("src/fortran/default.f95", "src/fortran/f1.f08")

    def test_expected_file_extensions(self) -> None:
        class ExpectedExtensionsSources(Sources):
            expected_file_extensions = (".f95", ".f03")

        addr = Address.parse("src/fortran:lib")
        self.create_files("src/fortran", files=["s.f95", "s.f03", "s.f08"])
        sources = ExpectedExtensionsSources(["s.f*"], address=addr)
        with pytest.raises(ExecutionError) as exc:
            self.request_single_product(HydratedSources, sources.request)
        assert "s.f08" in str(exc.value)
        assert str(addr) in str(exc.value)

        # Also check that we support valid sources
        valid_sources = ExpectedExtensionsSources(["s.f95"], address=addr)
        assert self.request_single_product(
            HydratedSources, valid_sources.request
        ).snapshot.files == ("src/fortran/s.f95",)

    def test_expected_num_files(self) -> None:
        class ExpectedNumber(Sources):
            expected_num_files = 2

        class ExpectedRange(Sources):
            # We allow for 1 or 3 files
            expected_num_files = range(1, 4, 2)

        self.create_files("", files=["f1.txt", "f2.txt", "f3.txt", "f4.txt"])

        def hydrate(sources_cls: Type[Sources], sources: Iterable[str]) -> HydratedSources:
            return self.request_single_product(
                HydratedSources, sources_cls(sources, address=Address.parse(":example")).request
            )

        with pytest.raises(ExecutionError) as exc:
            hydrate(ExpectedNumber, [])
        assert "must have 2 files" in str(exc.value)
        with pytest.raises(ExecutionError) as exc:
            hydrate(ExpectedRange, ["f1.txt", "f2.txt"])
        assert "must have 1 or 3 files" in str(exc.value)

        # Also check that we support valid # files.
        assert hydrate(ExpectedNumber, ["f1.txt", "f2.txt"]).snapshot.files == ("f1.txt", "f2.txt")
        assert hydrate(ExpectedRange, ["f1.txt"]).snapshot.files == ("f1.txt",)
        assert hydrate(ExpectedRange, ["f1.txt", "f2.txt", "f3.txt"]).snapshot.files == (
            "f1.txt",
            "f2.txt",
            "f3.txt",
        )
