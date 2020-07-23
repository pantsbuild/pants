# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
from dataclasses import dataclass
from pathlib import PurePath
from textwrap import dedent
from typing import Iterable, List, Tuple, Type

import pytest

from pants.base.specs import (
    FilesystemGlobSpec,
    FilesystemLiteralSpec,
    FilesystemMergedSpec,
    FilesystemResolvedGlobSpec,
    FilesystemSpecs,
    SingleAddress,
)
from pants.engine.addresses import Address, Addresses, AddressesWithOrigins, AddressWithOrigin
from pants.engine.fs import (
    CreateDigest,
    Digest,
    DigestContents,
    FileContent,
    Snapshot,
    SourcesSnapshot,
)
from pants.engine.internals.graph import (
    AmbiguousCodegenImplementationsException,
    AmbiguousImplementationsException,
    CycleException,
    NoValidTargetsException,
    Owners,
    OwnersRequest,
    TooManyTargetsException,
    parse_dependencies_field,
)
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Get, Params
from pants.engine.target import (
    Dependencies,
    DependenciesRequest,
    FieldSet,
    FieldSetWithOrigin,
    GeneratedSources,
    GenerateSourcesRequest,
    HydratedSources,
    HydrateSourcesRequest,
    InferDependenciesRequest,
    InferredDependencies,
    InjectDependenciesRequest,
    InjectedDependencies,
    Sources,
    Tags,
    Target,
    Targets,
    TargetsToValidFieldSets,
    TargetsToValidFieldSetsRequest,
    TargetsWithOrigins,
    TargetWithOrigin,
    TransitiveTargets,
    WrappedTarget,
)
from pants.engine.unions import UnionMembership, UnionRule, union
from pants.init.specs_calculator import SpecsCalculator
from pants.testutil.option.util import create_options_bootstrapper
from pants.testutil.test_base import TestBase
from pants.util.ordered_set import FrozenOrderedSet


class MockTarget(Target):
    alias = "target"
    core_fields = (Dependencies, Sources)


class GraphTest(TestBase):
    @classmethod
    def rules(cls):
        return (*super().rules(), RootRule(Addresses), RootRule(WrappedTarget))

    @classmethod
    def target_types(cls):
        return (MockTarget,)

    def test_transitive_targets(self) -> None:
        self.add_to_build_file(
            "",
            dedent(
                """\
                target(name='t1')
                target(name='t2', dependencies=[':t1'])
                target(name='d1', dependencies=[':t1'])
                target(name='d2', dependencies=[':t2'])
                target(name='d3')
                target(name='root', dependencies=[':d1', ':d2', ':d3'])
                """
            ),
        )

        def get_target(name: str) -> Target:
            return self.request_single_product(WrappedTarget, Address.parse(f"//:{name}")).target

        t1 = get_target("t1")
        t2 = get_target("t2")
        d1 = get_target("d1")
        d2 = get_target("d2")
        d3 = get_target("d3")
        root = get_target("root")

        direct_deps = self.request_single_product(
            Targets, Params(DependenciesRequest(root[Dependencies]), create_options_bootstrapper())
        )
        assert direct_deps == Targets([d1, d2, d3])

        transitive_targets = self.request_single_product(
            TransitiveTargets,
            Params(Addresses([root.address, d2.address]), create_options_bootstrapper()),
        )
        assert transitive_targets.roots == (root, d2)
        # NB: `//:d2` is both a target root and a dependency of `//:root`.
        assert transitive_targets.dependencies == FrozenOrderedSet([d1, d2, d3, t2, t1])
        assert transitive_targets.closure == FrozenOrderedSet([root, d2, d1, d3, t2, t1])

    def assert_failed_cycle(
        self, root_addr: str, subject_addr: str, path_addrs: Tuple[str, ...]
    ) -> None:
        with self.assertRaises(ExecutionError) as e:
            self.request_single_product(
                TransitiveTargets,
                Params(Addresses([Address.parse(root_addr)]), create_options_bootstrapper()),
            )
        (cycle_exception,) = e.exception.wrapped_exceptions
        assert isinstance(cycle_exception, CycleException)
        assert cycle_exception.subject == Address.parse(subject_addr)
        assert cycle_exception.path == tuple(Address.parse(p) for p in path_addrs)

    def test_cycle_self(self) -> None:
        self.add_to_build_file(
            "",
            dedent(
                """\
                target(name='t1', dependencies=[':t1'])
                """
            ),
        )
        self.assert_failed_cycle("//:t1", "//:t1", ("//:t1", "//:t1"))

    def test_cycle_direct(self) -> None:
        self.add_to_build_file(
            "",
            dedent(
                """\
                target(name='t1', dependencies=[':t2'])
                target(name='t2', dependencies=[':t1'])
                """
            ),
        )
        self.assert_failed_cycle("//:t1", "//:t1", ("//:t1", "//:t2", "//:t1"))
        self.assert_failed_cycle("//:t2", "//:t2", ("//:t2", "//:t1", "//:t2"))

    def test_cycle_indirect(self) -> None:
        self.add_to_build_file(
            "",
            dedent(
                """\
                target(name='t1', dependencies=[':t2'])
                target(name='t2', dependencies=[':t3'])
                target(name='t3', dependencies=[':t2'])
                """
            ),
        )
        self.assert_failed_cycle("//:t1", "//:t2", ("//:t1", "//:t2", "//:t3", "//:t2"))
        self.assert_failed_cycle("//:t2", "//:t2", ("//:t2", "//:t3", "//:t2"))

    def test_resolve_sources_snapshot(self) -> None:
        """This tests that convert filesystem specs and/or address specs into a single snapshot.

        Some important edge cases:
        - When a filesystem spec refers to a file without any owning target, it should be included
          in the snapshot.
        - If a file is covered both by an address spec and by a filesystem spec, we should merge it
          so that the file only shows up once.
        """
        self.create_files("demo", ["f1.txt", "f2.txt"])
        self.add_to_build_file("demo", "target(sources=['*.txt'])")
        specs = SpecsCalculator.parse_specs(["demo:demo", "demo/f1.txt", "demo/BUILD"])
        result = self.request_single_product(
            SourcesSnapshot, Params(specs, create_options_bootstrapper())
        )
        assert result.snapshot.files == ("demo/BUILD", "demo/f1.txt", "demo/f2.txt")


class TestOwners(TestBase):
    @classmethod
    def target_types(cls):
        return (MockTarget,)

    def test_owners_source_file_does_not_exist(self) -> None:
        """Test when a source file belongs to a target, even though the file does not actually
        exist.

        This happens, for example, when the file is deleted and we're computing `--changed-since`.
        """
        self.create_file("demo/f.txt")
        self.add_to_build_file("demo", "target(sources=['*.txt'])")
        result = self.request_single_product(Owners, OwnersRequest(("demo/deleted.txt",)))
        assert result == Owners([Address("demo", "demo")])

    def test_owners_multiple_owners(self) -> None:
        self.create_files("demo", ["f1.txt", "f2.txt"])
        self.add_to_build_file(
            "demo",
            dedent(
                """\
                target(name='all', sources=['*.txt'])
                target(name='f2', sources=['f2.txt'])
                """
            ),
        )

        one_owner_result = self.request_single_product(Owners, OwnersRequest(("demo/f1.txt",)))
        assert one_owner_result == Owners([Address("demo", "all")])

        two_owners_result = self.request_single_product(Owners, OwnersRequest(("demo/f2.txt",)))
        assert two_owners_result == Owners([Address("demo", "all"), Address("demo", "f2")])

        sibling_has_two_owners_result = self.request_single_product(
            Owners, OwnersRequest(("demo/f1.txt", "demo/f2.txt"))
        )
        assert sibling_has_two_owners_result == Owners(
            [Address("demo", "all"), Address("demo", "f2")]
        )

    def test_owners_build_file(self) -> None:
        """A BUILD file owns every target defined in it."""
        self.create_files("demo", ["f1.txt", "f2.txt"])
        self.add_to_build_file(
            "demo",
            dedent(
                """\
                target(name='f1', sources=['f1.txt'])
                target(name='f2_first', sources=['f2.txt'])
                target(name='f2_second', sources=['f2.txt'])
                """
            ),
        )
        result = self.request_single_product(Owners, OwnersRequest(("demo/BUILD",)))
        assert set(result) == {
            Address("demo", "f1"),
            Address("demo", "f2_first"),
            Address("demo", "f2_second"),
        }


class TestSpecsToAddresses(TestBase):
    @classmethod
    def rules(cls):
        return (*super().rules(), RootRule(Addresses), RootRule(FilesystemSpecs))

    @classmethod
    def target_types(cls):
        return (MockTarget,)

    def test_filesystem_specs_literal_file(self) -> None:
        self.create_files("demo", ["f1.txt", "f2.txt"])
        self.add_to_build_file("demo", "target(sources=['*.txt'])")
        spec = FilesystemLiteralSpec("demo/f1.txt")
        result = self.request_single_product(
            AddressesWithOrigins, Params(FilesystemSpecs([spec]), create_options_bootstrapper())
        )
        assert len(result) == 1
        assert result[0] == AddressWithOrigin(Address("demo", "demo"), origin=spec)

    def test_filesystem_specs_glob(self) -> None:
        self.create_files("demo", ["f1.txt", "f2.txt"])
        self.add_to_build_file("demo", "target(sources=['*.txt'])")
        result = self.request_single_product(
            AddressesWithOrigins,
            Params(
                FilesystemSpecs([FilesystemGlobSpec("demo/*.txt")]), create_options_bootstrapper()
            ),
        )
        expected = AddressWithOrigin(
            Address("demo", "demo"),
            origin=FilesystemResolvedGlobSpec(
                glob="demo/*.txt", files=("demo/f1.txt", "demo/f2.txt")
            ),
        )
        assert result == AddressesWithOrigins([expected])

    def test_filesystem_specs_merge_when_same_address(self) -> None:
        """Test that two filesystem specs resulting in the same address will merge into one
        result."""
        self.create_files("demo", ["f1.txt", "f2.txt"])
        self.add_to_build_file("demo", "target(sources=['*.txt'])")
        specs = [FilesystemLiteralSpec("demo/f1.txt"), FilesystemLiteralSpec("demo/f2.txt")]
        result = self.request_single_product(
            AddressesWithOrigins, Params(FilesystemSpecs(specs), create_options_bootstrapper())
        )
        assert result == AddressesWithOrigins(
            [AddressWithOrigin(Address("demo", "demo"), FilesystemMergedSpec.create(specs)),]
        )

    def test_filesystem_specs_nonexistent_file(self) -> None:
        specs = FilesystemSpecs([FilesystemLiteralSpec("demo/fake.txt")])
        with pytest.raises(ExecutionError) as exc:
            self.request_single_product(
                AddressesWithOrigins, Params(specs, create_options_bootstrapper()),
            )
        assert 'Unmatched glob from file arguments: "demo/fake.txt"' in str(exc.value)
        ignore_errors_result = self.request_single_product(
            AddressesWithOrigins,
            Params(specs, create_options_bootstrapper(args=["--owners-not-found-behavior=ignore"])),
        )
        assert not ignore_errors_result

    def test_filesystem_specs_no_owner(self) -> None:
        self.create_file("no_owners/f.txt")
        # Error for literal specs.
        with pytest.raises(ExecutionError) as exc:
            self.request_single_product(
                AddressesWithOrigins,
                Params(
                    FilesystemSpecs([FilesystemLiteralSpec("no_owners/f.txt")]),
                    create_options_bootstrapper(),
                ),
            )
        assert "No owning targets could be found for the file `no_owners/f.txt`" in str(exc.value)

        # Do not error for glob specs.
        glob_file_result = self.request_single_product(
            AddressesWithOrigins,
            Params(
                FilesystemSpecs([FilesystemGlobSpec("no_owners/*.txt")]),
                create_options_bootstrapper(),
            ),
        )
        assert not glob_file_result

    def test_resolve_addresses(self) -> None:
        """This tests that we correctly merge addresses resolved from address specs with those
        resolved from filesystem specs."""
        self.create_file("fs_spec/f.txt")
        self.add_to_build_file("fs_spec", "target(sources=['f.txt'])")
        self.create_file("address_spec/f.txt")
        self.add_to_build_file("address_spec", "target(sources=['f.txt'])")
        no_interaction_specs = ["fs_spec/f.txt", "address_spec:address_spec"]

        # If we use an address spec on one of the two owners, then we should properly dedupe with
        # the filesystem spec result.
        self.create_file("two_owners/f.txt")
        self.add_to_build_file(
            "two_owners",
            dedent(
                """\
                target(name='one', sources=['f.txt'])
                target(name='two', sources=['f.txt'])
                """
            ),
        )
        two_owners_specs = ["two_owners/f.txt", "two_owners:one"]

        self.create_files("multiple_files", ["f1.txt", "f2.txt"])
        self.add_to_build_file("multiple_files", "target(sources=['*.txt'])")
        multiple_files_specs = ["multiple_files/f2.txt", "multiple_files:multiple_files"]

        specs = SpecsCalculator.parse_specs(
            [*no_interaction_specs, *two_owners_specs, *multiple_files_specs]
        )
        result = self.request_single_product(
            AddressesWithOrigins, Params(specs, create_options_bootstrapper())
        )
        assert set(result) == {
            AddressWithOrigin(
                Address("fs_spec", "fs_spec"), origin=FilesystemLiteralSpec("fs_spec/f.txt"),
            ),
            AddressWithOrigin(
                Address("address_spec", "address_spec"),
                origin=SingleAddress("address_spec", "address_spec"),
            ),
            AddressWithOrigin(
                Address("two_owners", "one"), origin=SingleAddress("two_owners", "one")
            ),
            AddressWithOrigin(
                Address("two_owners", "two"), origin=FilesystemLiteralSpec("two_owners/f.txt"),
            ),
            AddressWithOrigin(
                Address("multiple_files", "multiple_files"),
                origin=SingleAddress("multiple_files", "multiple_files"),
            ),
        }


# -----------------------------------------------------------------------------------------------
# Test FieldSets. Also see `engine/target_test.py`.
# -----------------------------------------------------------------------------------------------


class FortranSources(Sources):
    pass


class FortranTarget(Target):
    alias = "fortran_target"
    core_fields = (FortranSources, Tags)


class TestFindValidFieldSets(TestBase):
    class InvalidTarget(Target):
        alias = "invalid_target"
        core_fields = ()

    @classmethod
    def target_types(cls):
        return [FortranTarget, cls.InvalidTarget]

    @union
    class FieldSetSuperclass(FieldSet):
        pass

    @dataclass(frozen=True)
    class FieldSetSubclass1(FieldSetSuperclass):
        required_fields = (FortranSources,)

        sources: FortranSources

    @dataclass(frozen=True)
    class FieldSetSubclass2(FieldSetSuperclass):
        required_fields = (FortranSources,)

        sources: FortranSources

    @union
    class FieldSetSuperclassWithOrigin(FieldSetWithOrigin):
        pass

    class FieldSetSubclassWithOrigin(FieldSetSuperclassWithOrigin):
        required_fields = (FortranSources,)

        sources: FortranSources

    @classmethod
    def rules(cls):
        return (
            *super().rules(),
            RootRule(TargetsWithOrigins),
            UnionRule(cls.FieldSetSuperclass, cls.FieldSetSubclass1),
            UnionRule(cls.FieldSetSuperclass, cls.FieldSetSubclass2),
            UnionRule(cls.FieldSetSuperclassWithOrigin, cls.FieldSetSubclassWithOrigin),
        )

    def test_find_valid_field_sets(self) -> None:
        origin = FilesystemLiteralSpec("f.txt")
        valid_tgt = FortranTarget({}, address=Address.parse(":valid"))
        valid_tgt_with_origin = TargetWithOrigin(valid_tgt, origin)
        invalid_tgt = self.InvalidTarget({}, address=Address.parse(":invalid"))
        invalid_tgt_with_origin = TargetWithOrigin(invalid_tgt, origin)

        def find_valid_field_sets(
            superclass: Type,
            targets_with_origins: Iterable[TargetWithOrigin],
            *,
            error_if_no_valid_targets: bool = False,
            expect_single_config: bool = False,
        ) -> TargetsToValidFieldSets:
            request = TargetsToValidFieldSetsRequest(
                superclass,
                goal_description="fake",
                error_if_no_valid_targets=error_if_no_valid_targets,
                expect_single_field_set=expect_single_config,
            )
            return self.request_single_product(
                TargetsToValidFieldSets, Params(request, TargetsWithOrigins(targets_with_origins),),
            )

        valid = find_valid_field_sets(
            self.FieldSetSuperclass, [valid_tgt_with_origin, invalid_tgt_with_origin]
        )
        assert valid.targets == (valid_tgt,)
        assert valid.targets_with_origins == (valid_tgt_with_origin,)
        assert valid.field_sets == (
            self.FieldSetSubclass1.create(valid_tgt),
            self.FieldSetSubclass2.create(valid_tgt),
        )

        with pytest.raises(ExecutionError) as exc:
            find_valid_field_sets(
                self.FieldSetSuperclass, [valid_tgt_with_origin], expect_single_config=True
            )
        assert AmbiguousImplementationsException.__name__ in str(exc.value)

        with pytest.raises(ExecutionError) as exc:
            find_valid_field_sets(
                self.FieldSetSuperclass,
                [
                    valid_tgt_with_origin,
                    TargetWithOrigin(FortranTarget({}, address=Address.parse(":valid2")), origin),
                ],
                expect_single_config=True,
            )
        assert TooManyTargetsException.__name__ in str(exc.value)

        no_valid_targets = find_valid_field_sets(self.FieldSetSuperclass, [invalid_tgt_with_origin])
        assert no_valid_targets.targets == ()
        assert no_valid_targets.targets_with_origins == ()
        assert no_valid_targets.field_sets == ()

        with pytest.raises(ExecutionError) as exc:
            find_valid_field_sets(
                self.FieldSetSuperclass, [invalid_tgt_with_origin], error_if_no_valid_targets=True
            )
        assert NoValidTargetsException.__name__ in str(exc.value)

        valid_with_origin = find_valid_field_sets(
            self.FieldSetSuperclassWithOrigin, [valid_tgt_with_origin, invalid_tgt_with_origin]
        )
        assert valid_with_origin.targets == (valid_tgt,)
        assert valid_with_origin.targets_with_origins == (valid_tgt_with_origin,)
        assert valid_with_origin.field_sets == (
            self.FieldSetSubclassWithOrigin.create(valid_tgt_with_origin),
        )


# -----------------------------------------------------------------------------------------------
# Test the Sources field, including codegen. Also see `engine/target_test.py`.
# -----------------------------------------------------------------------------------------------


class TestSources(TestBase):
    @classmethod
    def rules(cls):
        return (*super().rules(), RootRule(HydrateSourcesRequest))

    def test_normal_hydration(self) -> None:
        addr = Address.parse("src/fortran:lib")
        self.create_files("src/fortran", files=["f1.f95", "f2.f95", "f1.f03", "ignored.f03"])
        sources = Sources(["f1.f95", "*.f03", "!ignored.f03", "!**/ignore*"], address=addr)
        hydrated_sources = self.request_single_product(
            HydratedSources, HydrateSourcesRequest(sources)
        )
        assert hydrated_sources.snapshot.files == ("src/fortran/f1.f03", "src/fortran/f1.f95")

        # Also test that the Filespec is correct. This does not need hydration to be calculated.
        assert (
            sources.filespec
            == {
                "includes": ["src/fortran/*.f03", "src/fortran/f1.f95"],
                "excludes": ["src/fortran/**/ignore*", "src/fortran/ignored.f03"],
            }
            == hydrated_sources.filespec
        )

    def test_output_type(self) -> None:
        class SourcesSubclass(Sources):
            pass

        addr = Address.parse(":lib")
        self.create_files("", files=["f1.f95"])

        valid_sources = SourcesSubclass(["*"], address=addr)
        hydrated_valid_sources = self.request_single_product(
            HydratedSources,
            HydrateSourcesRequest(valid_sources, for_sources_types=[SourcesSubclass]),
        )
        assert hydrated_valid_sources.snapshot.files == ("f1.f95",)
        assert hydrated_valid_sources.sources_type == SourcesSubclass

        invalid_sources = Sources(["*"], address=addr)
        hydrated_invalid_sources = self.request_single_product(
            HydratedSources,
            HydrateSourcesRequest(invalid_sources, for_sources_types=[SourcesSubclass]),
        )
        assert hydrated_invalid_sources.snapshot.files == ()
        assert hydrated_invalid_sources.sources_type is None

    def test_unmatched_globs(self) -> None:
        self.create_files("", files=["f1.f95"])
        sources = Sources(["non_existent.f95"], address=Address.parse(":lib"))
        with pytest.raises(ExecutionError) as exc:
            self.request_single_product(HydratedSources, HydrateSourcesRequest(sources))
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
        assert set(sources.sanitized_raw_value or ()) == set(DefaultSources.default)

        hydrated_sources = self.request_single_product(
            HydratedSources, HydrateSourcesRequest(sources)
        )
        assert hydrated_sources.snapshot.files == ("src/fortran/default.f95", "src/fortran/f1.f08")

    def test_expected_file_extensions(self) -> None:
        class ExpectedExtensionsSources(Sources):
            expected_file_extensions = (".f95", ".f03")

        addr = Address.parse("src/fortran:lib")
        self.create_files("src/fortran", files=["s.f95", "s.f03", "s.f08"])
        sources = ExpectedExtensionsSources(["s.f*"], address=addr)
        with pytest.raises(ExecutionError) as exc:
            self.request_single_product(HydratedSources, HydrateSourcesRequest(sources))
        assert "s.f08" in str(exc.value)
        assert str(addr) in str(exc.value)

        # Also check that we support valid sources
        valid_sources = ExpectedExtensionsSources(["s.f95"], address=addr)
        assert self.request_single_product(
            HydratedSources, HydrateSourcesRequest(valid_sources)
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
                HydratedSources,
                HydrateSourcesRequest(sources_cls(sources, address=Address.parse(":example"))),
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


class SmalltalkSources(Sources):
    pass


class AvroSources(Sources):
    pass


class AvroLibrary(Target):
    alias = "avro_library"
    core_fields = (AvroSources,)


class GenerateSmalltalkFromAvroRequest(GenerateSourcesRequest):
    input = AvroSources
    output = SmalltalkSources


@rule
async def generate_smalltalk_from_avro(
    request: GenerateSmalltalkFromAvroRequest,
) -> GeneratedSources:
    protocol_files = request.protocol_sources.files

    def generate_fortran(fp: str) -> FileContent:
        parent = str(PurePath(fp).parent).replace("src/avro", "src/smalltalk")
        file_name = f"{PurePath(fp).stem}.st"
        return FileContent(str(PurePath(parent, file_name)), b"Generated")

    result = await Get(Snapshot, CreateDigest([generate_fortran(fp) for fp in protocol_files]))
    return GeneratedSources(result)


class TestCodegen(TestBase):
    @classmethod
    def rules(cls):
        return (
            *super().rules(),
            generate_smalltalk_from_avro,
            RootRule(GenerateSmalltalkFromAvroRequest),
            RootRule(HydrateSourcesRequest),
            UnionRule(GenerateSourcesRequest, GenerateSmalltalkFromAvroRequest),
        )

    @classmethod
    def target_types(cls):
        return [AvroLibrary]

    def setUp(self) -> None:
        self.address = Address.parse("src/avro:lib")
        self.create_files("src/avro", files=["f.avro"])
        self.add_to_build_file("src/avro", "avro_library(name='lib', sources=['*.avro'])")
        self.union_membership = self.request_single_product(UnionMembership, Params())

    def test_generate_sources(self) -> None:
        protocol_sources = AvroSources(["*.avro"], address=self.address)
        assert protocol_sources.can_generate(SmalltalkSources, self.union_membership) is True

        # First, get the original protocol sources.
        hydrated_protocol_sources = self.request_single_product(
            HydratedSources, HydrateSourcesRequest(protocol_sources)
        )
        assert hydrated_protocol_sources.snapshot.files == ("src/avro/f.avro",)

        # Test directly feeding the protocol sources into the codegen rule.
        wrapped_tgt = self.request_single_product(WrappedTarget, self.address)
        generated_sources = self.request_single_product(
            GeneratedSources,
            GenerateSmalltalkFromAvroRequest(
                hydrated_protocol_sources.snapshot, wrapped_tgt.target
            ),
        )
        assert generated_sources.snapshot.files == ("src/smalltalk/f.st",)

        # Test that HydrateSourcesRequest can also be used.
        generated_via_hydrate_sources = self.request_single_product(
            HydratedSources,
            HydrateSourcesRequest(
                protocol_sources, for_sources_types=[SmalltalkSources], enable_codegen=True
            ),
        )
        assert generated_via_hydrate_sources.snapshot.files == ("src/smalltalk/f.st",)
        assert generated_via_hydrate_sources.sources_type == SmalltalkSources

    def test_works_with_subclass_fields(self) -> None:
        class CustomAvroSources(AvroSources):
            pass

        protocol_sources = CustomAvroSources(["*.avro"], address=self.address)
        assert protocol_sources.can_generate(SmalltalkSources, self.union_membership) is True
        generated = self.request_single_product(
            HydratedSources,
            HydrateSourcesRequest(
                protocol_sources, for_sources_types=[SmalltalkSources], enable_codegen=True
            ),
        )
        assert generated.snapshot.files == ("src/smalltalk/f.st",)

    def test_cannot_generate_language(self) -> None:
        class AdaSources(Sources):
            pass

        protocol_sources = AvroSources(["*.avro"], address=self.address)
        assert protocol_sources.can_generate(AdaSources, self.union_membership) is False
        generated = self.request_single_product(
            HydratedSources,
            HydrateSourcesRequest(
                protocol_sources, for_sources_types=[AdaSources], enable_codegen=True
            ),
        )
        assert generated.snapshot.files == ()
        assert generated.sources_type is None

    def test_ambiguous_implementations_exception(self) -> None:
        # This error message is quite complex. We test that it correctly generates the message.
        class SmalltalkGenerator1(GenerateSourcesRequest):
            input = AvroSources
            output = SmalltalkSources

        class SmalltalkGenerator2(GenerateSourcesRequest):
            input = AvroSources
            output = SmalltalkSources

        class AdaSources(Sources):
            pass

        class AdaGenerator(GenerateSourcesRequest):
            input = AvroSources
            output = AdaSources

        class IrrelevantSources(Sources):
            pass

        # Test when all generators have the same input and output.
        exc = AmbiguousCodegenImplementationsException(
            [SmalltalkGenerator1, SmalltalkGenerator2], for_sources_types=[SmalltalkSources]
        )
        assert "can generate SmalltalkSources from AvroSources" in str(exc)
        assert "* SmalltalkGenerator1" in str(exc)
        assert "* SmalltalkGenerator2" in str(exc)

        # Test when the generators have different input and output, which usually happens because
        # the call site used too expansive of a `for_sources_types` argument.
        exc = AmbiguousCodegenImplementationsException(
            [SmalltalkGenerator1, AdaGenerator],
            for_sources_types=[SmalltalkSources, AdaSources, IrrelevantSources],
        )
        assert "can generate one of ['AdaSources', 'SmalltalkSources'] from AvroSources" in str(exc)
        assert "IrrelevantSources" not in str(exc)
        assert "* SmalltalkGenerator1 -> SmalltalkSources" in str(exc)
        assert "* AdaGenerator -> AdaSources" in str(exc)


# -----------------------------------------------------------------------------------------------
# Test the Dependencies field. Also see `engine/target_test.py`.
# -----------------------------------------------------------------------------------------------


def test_parse_dependencies_field() -> None:
    given_values = [
        ":relative",
        "//:top_level",
        "demo:tgt",
        "demo",
    ]
    result = parse_dependencies_field(
        [*given_values, *(f"!{v}" for v in given_values)],
        spec_path="demo/subdir",
        subproject_roots=[],
    )
    expected = {
        Address("demo/subdir", "relative"),
        Address("", "top_level"),
        Address("demo", "tgt"),
        Address("demo", "demo"),
    }
    assert set(result.addresses) == expected
    assert set(result.ignored) == expected


class SmalltalkDependencies(Dependencies):
    pass


class CustomSmalltalkDependencies(SmalltalkDependencies):
    pass


class InjectSmalltalkDependencies(InjectDependenciesRequest):
    inject_for = SmalltalkDependencies


class InjectCustomSmalltalkDependencies(InjectDependenciesRequest):
    inject_for = CustomSmalltalkDependencies


@rule
def inject_smalltalk_deps(_: InjectSmalltalkDependencies) -> InjectedDependencies:
    return InjectedDependencies([Address.parse("//:injected1"), Address.parse("//:injected2")])


@rule
def inject_custom_smalltalk_deps(_: InjectCustomSmalltalkDependencies) -> InjectedDependencies:
    return InjectedDependencies([Address.parse("//:custom_injected")])


class SmalltalkLibrarySources(SmalltalkSources):
    pass


class SmalltalkLibrary(Target):
    alias = "smalltalk"
    core_fields = (Dependencies, SmalltalkLibrarySources)


class InferSmalltalkDependencies(InferDependenciesRequest):
    infer_from = SmalltalkSources


@rule
async def infer_smalltalk_dependencies(request: InferSmalltalkDependencies) -> InferredDependencies:
    # To demo an inference rule, we simply treat each `sources` file to contain a list of
    # addresses, one per line.
    hydrated_sources = await Get(HydratedSources, HydrateSourcesRequest(request.sources_field))
    digest_contents = await Get(DigestContents, Digest, hydrated_sources.snapshot.digest)
    all_lines = itertools.chain.from_iterable(
        file_content.content.decode().splitlines() for file_content in digest_contents
    )
    return InferredDependencies(Address.parse(line) for line in all_lines)


class TestDependencies(TestBase):
    @classmethod
    def rules(cls):
        return (
            *super().rules(),
            RootRule(DependenciesRequest),
            inject_smalltalk_deps,
            inject_custom_smalltalk_deps,
            infer_smalltalk_dependencies,
            UnionRule(InjectDependenciesRequest, InjectSmalltalkDependencies),
            UnionRule(InjectDependenciesRequest, InjectCustomSmalltalkDependencies),
            UnionRule(InferDependenciesRequest, InferSmalltalkDependencies),
        )

    @classmethod
    def target_types(cls):
        return [SmalltalkLibrary]

    def assert_dependencies_resolved(
        self,
        *,
        requested_address: Address,
        expected: Iterable[Address],
        enable_dep_inference: bool = False,
    ) -> None:
        target = self.request_single_product(WrappedTarget, requested_address).target
        args = ["--dependency-inference"] if enable_dep_inference else []
        result = self.request_single_product(
            Addresses,
            Params(
                DependenciesRequest(target[Dependencies]), create_options_bootstrapper(args=args)
            ),
        )
        assert result == Addresses(sorted(expected))

    def test_normal_resolution(self) -> None:
        self.add_to_build_file(
            "src/smalltalk", "smalltalk(dependencies=['//:dep1', '//:dep2', ':sibling'])"
        )
        self.assert_dependencies_resolved(
            requested_address=Address.parse("src/smalltalk"),
            expected=[
                Address.parse("//:dep1"),
                Address.parse("//:dep2"),
                Address.parse("src/smalltalk:sibling"),
            ],
        )

        # Also test that we handle no dependencies.
        self.add_to_build_file("no_deps", "smalltalk()")
        self.assert_dependencies_resolved(requested_address=Address.parse("no_deps"), expected=[])

        # An ignore should override an include.
        self.add_to_build_file("ignore", "smalltalk(dependencies=['//:dep', '!//:dep'])")
        self.assert_dependencies_resolved(requested_address=Address.parse("ignore"), expected=[])

        # Error on unused ignores.
        self.add_to_build_file("unused", "smalltalk(dependencies=[':sibling', '!:ignore'])")
        with pytest.raises(ExecutionError) as exc:
            self.assert_dependencies_resolved(
                requested_address=Address.parse("unused"), expected=[]
            )
        assert "'!unused:ignore'" in str(exc.value)
        assert "* unused:sibling" in str(exc.value)

    def test_dependency_injection(self) -> None:
        self.add_to_build_file("", "smalltalk(name='target')")

        def assert_injected(deps_cls: Type[Dependencies], *, injected: List[str]) -> None:
            provided_deps = ["//:provided"]
            if injected:
                provided_deps.append("!//:injected2")
            deps_field = deps_cls(provided_deps, address=Address.parse("//:target"))
            result = self.request_single_product(
                Addresses, Params(DependenciesRequest(deps_field), create_options_bootstrapper())
            )
            assert result == Addresses(
                sorted(Address.parse(addr) for addr in (*injected, "//:provided"))
            )

        assert_injected(Dependencies, injected=[])
        assert_injected(SmalltalkDependencies, injected=["//:injected1"])
        assert_injected(
            CustomSmalltalkDependencies, injected=["//:custom_injected", "//:injected1"]
        )

    def test_dependency_inference(self) -> None:
        """We test that dependency inference works generally and that we merge it correctly with
        explicitly provided dependencies."""
        self.add_to_build_file(
            "",
            dedent(
                """\
                smalltalk(name='provided')
                smalltalk(name='inferred')
                smalltalk(name='inferred_but_ignored')
                smalltalk(name='inferred_and_provided')
                """
            ),
        )
        self.create_file(
            "demo/f1.st",
            dedent(
                """\
                //:inferred
                """
            ),
        )
        self.create_file(
            "demo/f2.st",
            dedent(
                """\
                //:inferred_and_provided
                //:inferred_but_ignored
                """
            ),
        )
        self.add_to_build_file(
            "demo",
            dedent(
                """\
                smalltalk(
                  sources=['*.st'],
                  dependencies=[
                    '//:provided',
                    '//:inferred_and_provided',
                    '!//:inferred_but_ignored',
                  ],
                )
                """
            ),
        )

        self.assert_dependencies_resolved(
            requested_address=Address.parse("demo"),
            enable_dep_inference=True,
            expected=[
                Address.parse("//:provided"),
                Address.parse("//:inferred"),
                Address.parse("//:inferred_and_provided"),
            ],
        )
