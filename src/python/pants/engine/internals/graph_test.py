# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
from dataclasses import dataclass
from pathlib import PurePath
from textwrap import dedent
from typing import Iterable, List, Optional, Set, Tuple, Type

import pytest

from pants.base.specs import (
    AddressLiteralSpec,
    FilesystemGlobSpec,
    FilesystemLiteralSpec,
    FilesystemSpec,
    FilesystemSpecs,
    Specs,
)
from pants.base.specs_parser import SpecsParser
from pants.engine.addresses import (
    Address,
    Addresses,
    AddressesWithOrigins,
    AddressInput,
    AddressWithOrigin,
)
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
    NoApplicableTargetsException,
    Owners,
    OwnersRequest,
    TooManyTargetsException,
    TransitiveExcludesNotSupportedError,
    parse_dependencies_field,
)
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.rules import Get, MultiGet, rule
from pants.engine.target import (
    Dependencies,
    DependenciesRequest,
    FieldSet,
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
    TargetRootsToFieldSets,
    TargetRootsToFieldSetsRequest,
    Targets,
    TargetsWithOrigins,
    TargetWithOrigin,
    TransitiveTargets,
    WrappedTarget,
)
from pants.engine.unions import UnionMembership, UnionRule, union
from pants.testutil.rule_runner import QueryRule, RuleRunner
from pants.testutil.test_base import TestBase
from pants.util.ordered_set import FrozenOrderedSet


class MockDependencies(Dependencies):
    supports_transitive_excludes = True


class MockTarget(Target):
    alias = "target"
    core_fields = (MockDependencies, Sources)


@pytest.fixture
def transitive_targets_rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            QueryRule(Targets, (DependenciesRequest,)),
            QueryRule(TransitiveTargets, (Addresses,)),
        ],
        target_types=[MockTarget],
    )


def test_transitive_targets(transitive_targets_rule_runner: RuleRunner) -> None:
    transitive_targets_rule_runner.add_to_build_file(
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
        return transitive_targets_rule_runner.get_target(Address("", target_name=name))

    t1 = get_target("t1")
    t2 = get_target("t2")
    d1 = get_target("d1")
    d2 = get_target("d2")
    d3 = get_target("d3")
    root = get_target("root")

    direct_deps = transitive_targets_rule_runner.request(
        Targets, [DependenciesRequest(root[Dependencies])]
    )
    assert direct_deps == Targets([d1, d2, d3])

    transitive_targets = transitive_targets_rule_runner.request(
        TransitiveTargets, [Addresses([root.address, d2.address])]
    )
    assert transitive_targets.roots == (root, d2)
    # NB: `//:d2` is both a target root and a dependency of `//:root`.
    assert transitive_targets.dependencies == FrozenOrderedSet([d1, d2, d3, t2, t1])
    assert transitive_targets.closure == FrozenOrderedSet([root, d2, d1, d3, t2, t1])


def test_transitive_targets_transitive_exclude(transitive_targets_rule_runner: RuleRunner) -> None:
    transitive_targets_rule_runner.add_to_build_file(
        "",
        dedent(
            """\
            target(name='base')
            target(name='intermediate', dependencies=[':base'])
            target(name='root', dependencies=[':intermediate', '!!:base'])
            """
        ),
    )

    def get_target(name: str) -> Target:
        return transitive_targets_rule_runner.get_target(Address("", target_name=name))

    base = get_target("base")
    intermediate = get_target("intermediate")
    root = get_target("root")

    intermediate_direct_deps = transitive_targets_rule_runner.request(
        Targets, [DependenciesRequest(intermediate[Dependencies])]
    )
    assert intermediate_direct_deps == Targets([base])

    transitive_targets = transitive_targets_rule_runner.request(
        TransitiveTargets, [Addresses([root.address, intermediate.address])]
    )
    assert transitive_targets.roots == (root, intermediate)
    assert transitive_targets.dependencies == FrozenOrderedSet([intermediate])
    assert transitive_targets.closure == FrozenOrderedSet([root, intermediate])


def test_transitive_targets_tolerates_subtarget_cycles(
    transitive_targets_rule_runner: RuleRunner,
) -> None:
    """For generated subtargets, we should tolerate cycles between targets.

    This only works with generated subtargets, so we use explicit file dependencies in this test.
    """
    transitive_targets_rule_runner.create_files("", ["dep.txt", "t1.txt", "t2.txt"])
    transitive_targets_rule_runner.add_to_build_file(
        "",
        dedent(
            """\
            target(name='dep', sources=['dep.txt'])
            target(name='t1', sources=['t1.txt'], dependencies=['dep.txt:dep', 't2.txt:t2'])
            target(name='t2', sources=['t2.txt'], dependencies=['t1.txt:t1'])
            """
        ),
    )
    result = transitive_targets_rule_runner.request(
        TransitiveTargets,
        [Addresses([Address("", target_name="t2")])],
    )
    assert len(result.roots) == 1
    assert result.roots[0].address == Address("", relative_file_path="t2.txt", target_name="t2")
    assert [tgt.address for tgt in result.dependencies] == [
        Address("", relative_file_path="t1.txt", target_name="t1"),
        Address("", relative_file_path="dep.txt", target_name="dep"),
        Address("", relative_file_path="t2.txt", target_name="t2"),
    ]


def assert_failed_cycle(
    rule_runner: RuleRunner,
    *,
    root_target_name: str,
    subject_target_name: str,
    path_target_names: Tuple[str, ...],
) -> None:
    with pytest.raises(ExecutionError) as e:
        rule_runner.request(
            TransitiveTargets, [Addresses([Address("", target_name=root_target_name)])]
        )
    (cycle_exception,) = e.value.wrapped_exceptions
    assert isinstance(cycle_exception, CycleException)
    assert cycle_exception.subject == Address("", target_name=subject_target_name)
    assert cycle_exception.path == tuple(Address("", target_name=p) for p in path_target_names)


def test_dep_cycle_self(transitive_targets_rule_runner: RuleRunner) -> None:
    transitive_targets_rule_runner.add_to_build_file(
        "",
        dedent(
            """\
            target(name='t1', dependencies=[':t1'])
            """
        ),
    )
    assert_failed_cycle(
        transitive_targets_rule_runner,
        root_target_name="t1",
        subject_target_name="t1",
        path_target_names=("t1", "t1"),
    )


def test_dep_cycle_direct(transitive_targets_rule_runner: RuleRunner) -> None:
    transitive_targets_rule_runner.add_to_build_file(
        "",
        dedent(
            """\
            target(name='t1', dependencies=[':t2'])
            target(name='t2', dependencies=[':t1'])
            """
        ),
    )
    assert_failed_cycle(
        transitive_targets_rule_runner,
        root_target_name="t1",
        subject_target_name="t1",
        path_target_names=("t1", "t2", "t1"),
    )
    assert_failed_cycle(
        transitive_targets_rule_runner,
        root_target_name="t2",
        subject_target_name="t2",
        path_target_names=("t2", "t1", "t2"),
    )


def test_dep_cycle_indirect(transitive_targets_rule_runner: RuleRunner) -> None:
    transitive_targets_rule_runner.add_to_build_file(
        "",
        dedent(
            """\
            target(name='t1', dependencies=[':t2'])
            target(name='t2', dependencies=[':t3'])
            target(name='t3', dependencies=[':t2'])
            """
        ),
    )
    assert_failed_cycle(
        transitive_targets_rule_runner,
        root_target_name="t1",
        subject_target_name="t2",
        path_target_names=("t1", "t2", "t3", "t2"),
    )
    assert_failed_cycle(
        transitive_targets_rule_runner,
        root_target_name="t2",
        subject_target_name="t2",
        path_target_names=("t2", "t3", "t2"),
    )


def test_dep_nocycle_indirect(transitive_targets_rule_runner: RuleRunner) -> None:
    transitive_targets_rule_runner.create_file("t2.txt")
    transitive_targets_rule_runner.add_to_build_file(
        "",
        dedent(
            """\
            target(name='t1', dependencies=['t2.txt:t2'])
            target(name='t2', dependencies=[':t1'], sources=['t2.txt'])
            """
        ),
    )
    result = transitive_targets_rule_runner.request(
        TransitiveTargets,
        [Addresses([Address("", target_name="t1")])],
    )
    assert len(result.roots) == 1
    assert result.roots[0].address == Address("", target_name="t1")
    assert {tgt.address for tgt in result.dependencies} == {
        Address("", target_name="t1"),
        Address("", relative_file_path="t2.txt", target_name="t2"),
    }


def test_resolve_generated_subtarget() -> None:
    rule_runner = RuleRunner(target_types=[MockTarget])
    rule_runner.add_to_build_file("demo", "target(sources=['f1.txt', 'f2.txt'])")
    generated_target_address = Address("demo", relative_file_path="f1.txt", target_name="demo")
    generated_target = rule_runner.get_target(generated_target_address)
    assert generated_target == MockTarget(
        {Sources.alias: ["f1.txt"]}, address=generated_target_address
    )


def test_resolve_sources_snapshot() -> None:
    """This tests that convert filesystem specs and/or address specs into a single snapshot.

    Some important edge cases:
    - When a filesystem spec refers to a file without any owning target, it should be included
      in the snapshot.
    - If a file is covered both by an address spec and by a filesystem spec, we should merge it
      so that the file only shows up once.
    """
    rule_runner = RuleRunner(
        rules=[QueryRule(SourcesSnapshot, (Specs,))], target_types=[MockTarget]
    )
    rule_runner.create_files("demo", ["f1.txt", "f2.txt"])
    rule_runner.add_to_build_file("demo", "target(sources=['*.txt'])")
    specs = SpecsParser(rule_runner.build_root).parse_specs(
        ["demo:demo", "demo/f1.txt", "demo/BUILD"]
    )
    result = rule_runner.request(SourcesSnapshot, [specs])
    assert result.snapshot.files == ("demo/BUILD", "demo/f1.txt", "demo/f2.txt")


@pytest.fixture
def owners_rule_runner() -> RuleRunner:
    return RuleRunner(rules=[QueryRule(Owners, (OwnersRequest,))], target_types=[MockTarget])


def assert_owners(
    rule_runner: RuleRunner, requested: Iterable[str], *, expected: Set[Address]
) -> None:
    result = rule_runner.request(Owners, [OwnersRequest(tuple(requested))])
    assert set(result) == expected


def test_owners_source_file_does_not_exist(owners_rule_runner: RuleRunner) -> None:
    """Test when a source file belongs to a target, even though the file does not actually exist.

    This happens, for example, when the file is deleted and we're computing `--changed-since`. In
    this case, we should not attempt to generate a subtarget and should use the original target.
    """
    owners_rule_runner.create_file("demo/f.txt")
    owners_rule_runner.add_to_build_file("demo", "target(sources=['*.txt'])")
    assert_owners(
        owners_rule_runner, ["demo/deleted.txt"], expected={Address("demo", target_name="demo")}
    )

    # For files that do exist, we should still use a generated subtarget, though.
    assert_owners(
        owners_rule_runner,
        ["demo/f.txt"],
        expected={Address("demo", relative_file_path="f.txt", target_name="demo")},
    )

    # If a sibling file uses the original target, then both should be used.
    assert_owners(
        owners_rule_runner,
        ["demo/f.txt", "demo/deleted.txt"],
        expected={
            Address("demo", relative_file_path="f.txt", target_name="demo"),
            Address("demo"),
        },
    )


def test_owners_multiple_owners(owners_rule_runner: RuleRunner) -> None:
    """Even if there are multiple owners of the same file, we still use generated subtargets."""
    owners_rule_runner.create_files("demo", ["f1.txt", "f2.txt"])
    owners_rule_runner.add_to_build_file(
        "demo",
        dedent(
            """\
            target(name='all', sources=['*.txt'])
            target(name='f2', sources=['f2.txt'])
            """
        ),
    )
    assert_owners(
        owners_rule_runner,
        ["demo/f1.txt"],
        expected={Address("demo", relative_file_path="f1.txt", target_name="all")},
    )
    assert_owners(
        owners_rule_runner,
        ["demo/f2.txt"],
        expected={
            Address("demo", relative_file_path="f2.txt", target_name="all"),
            Address("demo", relative_file_path="f2.txt", target_name="f2"),
        },
    )


def test_owners_build_file(owners_rule_runner: RuleRunner) -> None:
    """A BUILD file owns every target defined in it."""
    owners_rule_runner.create_files("demo", ["f1.txt", "f2.txt"])
    owners_rule_runner.add_to_build_file(
        "demo",
        dedent(
            """\
            target(name='f1', sources=['f1.txt'])
            target(name='f2_first', sources=['f2.txt'])
            target(name='f2_second', sources=['f2.txt'])
            """
        ),
    )
    assert_owners(
        owners_rule_runner,
        ["demo/BUILD"],
        expected={
            Address("demo", relative_file_path="f1.txt", target_name="f1"),
            Address("demo", relative_file_path="f2.txt", target_name="f2_first"),
            Address("demo", relative_file_path="f2.txt", target_name="f2_second"),
        },
    )


@pytest.fixture
def specs_rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[QueryRule(AddressesWithOrigins, (FilesystemSpecs,))],
        target_types=[MockTarget],
    )


def resolve_filesystem_specs(
    rule_runner: RuleRunner,
    specs: Iterable[FilesystemSpec],
) -> Set[AddressWithOrigin]:
    result = rule_runner.request(AddressesWithOrigins, [FilesystemSpecs(specs)])
    return set(result)


def test_filesystem_specs_literal_file(specs_rule_runner: RuleRunner) -> None:
    specs_rule_runner.create_files("demo", ["f1.txt", "f2.txt"])
    specs_rule_runner.add_to_build_file("demo", "target(sources=['*.txt'])")
    spec = FilesystemLiteralSpec("demo/f1.txt")
    assert resolve_filesystem_specs(specs_rule_runner, [spec]) == {
        AddressWithOrigin(
            Address("demo", relative_file_path="f1.txt", target_name="demo"), origin=spec
        )
    }


def test_filesystem_specs_glob(specs_rule_runner: RuleRunner) -> None:
    specs_rule_runner.create_files("demo", ["f1.txt", "f2.txt"])
    specs_rule_runner.add_to_build_file("demo", "target(sources=['*.txt'])")
    spec = FilesystemGlobSpec("demo/*.txt")
    assert resolve_filesystem_specs(specs_rule_runner, [spec]) == {
        AddressWithOrigin(
            Address("demo", relative_file_path="f1.txt", target_name="demo"), origin=spec
        ),
        AddressWithOrigin(
            Address("demo", relative_file_path="f2.txt", target_name="demo"), origin=spec
        ),
    }

    # If a glob and a literal spec both resolve to the same file, the literal spec should be
    # used as it's more precise.
    literal_spec = FilesystemLiteralSpec("demo/f1.txt")
    assert resolve_filesystem_specs(specs_rule_runner, [spec, literal_spec]) == {
        AddressWithOrigin(
            Address("demo", relative_file_path="f1.txt", target_name="demo"),
            origin=literal_spec,
        ),
        AddressWithOrigin(
            Address("demo", relative_file_path="f2.txt", target_name="demo"), origin=spec
        ),
    }


def test_filesystem_specs_nonexistent_file(specs_rule_runner: RuleRunner) -> None:
    spec = FilesystemLiteralSpec("demo/fake.txt")
    with pytest.raises(ExecutionError) as exc:
        resolve_filesystem_specs(specs_rule_runner, [spec])
    assert 'Unmatched glob from file arguments: "demo/fake.txt"' in str(exc.value)

    specs_rule_runner.set_options(["--owners-not-found-behavior=ignore"])
    assert not resolve_filesystem_specs(specs_rule_runner, [spec])


def test_filesystem_specs_no_owner(specs_rule_runner: RuleRunner) -> None:
    specs_rule_runner.create_file("no_owners/f.txt")
    # Error for literal specs.
    with pytest.raises(ExecutionError) as exc:
        resolve_filesystem_specs(specs_rule_runner, [FilesystemLiteralSpec("no_owners/f.txt")])
    assert "No owning targets could be found for the file `no_owners/f.txt`" in str(exc.value)

    # Do not error for glob specs.
    assert not resolve_filesystem_specs(specs_rule_runner, [FilesystemGlobSpec("no_owners/*.txt")])


def test_resolve_addresses_from_specs() -> None:
    """This tests that we correctly handle resolving from both address and filesystem specs."""
    rule_runner = RuleRunner(
        rules=[QueryRule(AddressesWithOrigins, (Specs,))],
        target_types=[MockTarget],
    )
    rule_runner.create_file("fs_spec/f.txt")
    rule_runner.add_to_build_file("fs_spec", "target(sources=['f.txt'])")
    rule_runner.create_file("address_spec/f.txt")
    rule_runner.add_to_build_file("address_spec", "target(sources=['f.txt'])")
    no_interaction_specs = ["fs_spec/f.txt", "address_spec:address_spec"]

    # If a generated subtarget's original base target is included via an address spec,
    # we will still include the generated subtarget for consistency. When we expand Targets
    # into their base targets this redundancy is removed, but during Address expansion we
    # get literal matches.
    rule_runner.create_files("multiple_files", ["f1.txt", "f2.txt"])
    rule_runner.add_to_build_file("multiple_files", "target(sources=['*.txt'])")
    multiple_files_specs = ["multiple_files/f2.txt", "multiple_files:multiple_files"]

    specs = SpecsParser(rule_runner.build_root).parse_specs(
        [*no_interaction_specs, *multiple_files_specs]
    )
    result = rule_runner.request(AddressesWithOrigins, [specs])
    assert set(result) == {
        AddressWithOrigin(
            Address("fs_spec", relative_file_path="f.txt"),
            origin=FilesystemLiteralSpec("fs_spec/f.txt"),
        ),
        AddressWithOrigin(
            Address("address_spec"),
            origin=AddressLiteralSpec("address_spec", "address_spec"),
        ),
        AddressWithOrigin(
            Address("multiple_files"),
            origin=AddressLiteralSpec("multiple_files", "multiple_files"),
        ),
        AddressWithOrigin(
            Address("multiple_files", relative_file_path="f2.txt"),
            origin=FilesystemLiteralSpec(file="multiple_files/f2.txt"),
        ),
    }


# -----------------------------------------------------------------------------------------------
# Test FieldSets. Also see `engine/target_test.py`.
# -----------------------------------------------------------------------------------------------


def test_find_valid_field_sets() -> None:
    class FortranSources(Sources):
        pass

    class FortranTarget(Target):
        alias = "fortran_target"
        core_fields = (FortranSources, Tags)

    class InvalidTarget(Target):
        alias = "invalid_target"
        core_fields = ()

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

    rule_runner = RuleRunner(
        rules=[
            QueryRule(TargetRootsToFieldSets, (TargetRootsToFieldSetsRequest, TargetsWithOrigins)),
            UnionRule(FieldSetSuperclass, FieldSetSubclass1),
            UnionRule(FieldSetSuperclass, FieldSetSubclass2),
        ],
        target_types=[FortranTarget, InvalidTarget],
    )

    origin = FilesystemLiteralSpec("f.txt")
    valid_tgt = FortranTarget({}, address=Address("", target_name=":valid"))
    valid_tgt_with_origin = TargetWithOrigin(valid_tgt, origin)
    invalid_tgt = InvalidTarget({}, address=Address("", target_name=":invalid"))
    invalid_tgt_with_origin = TargetWithOrigin(invalid_tgt, origin)

    def find_valid_field_sets(
        superclass: Type,
        targets_with_origins: Iterable[TargetWithOrigin],
        *,
        error_if_no_applicable_targets: bool = False,
        expect_single_config: bool = False,
    ) -> TargetRootsToFieldSets:
        request = TargetRootsToFieldSetsRequest(
            superclass,
            goal_description="fake",
            error_if_no_applicable_targets=error_if_no_applicable_targets,
            expect_single_field_set=expect_single_config,
        )
        return rule_runner.request(
            TargetRootsToFieldSets,
            [request, TargetsWithOrigins(targets_with_origins)],
        )

    valid = find_valid_field_sets(
        FieldSetSuperclass, [valid_tgt_with_origin, invalid_tgt_with_origin]
    )
    assert valid.targets == (valid_tgt,)
    assert valid.targets_with_origins == (valid_tgt_with_origin,)
    assert valid.field_sets == (
        FieldSetSubclass1.create(valid_tgt),
        FieldSetSubclass2.create(valid_tgt),
    )

    with pytest.raises(ExecutionError) as exc:
        find_valid_field_sets(
            FieldSetSuperclass, [valid_tgt_with_origin], expect_single_config=True
        )
    assert AmbiguousImplementationsException.__name__ in str(exc.value)

    with pytest.raises(ExecutionError) as exc:
        find_valid_field_sets(
            FieldSetSuperclass,
            [
                valid_tgt_with_origin,
                TargetWithOrigin(
                    FortranTarget({}, address=Address("", target_name=":valid2")), origin
                ),
            ],
            expect_single_config=True,
        )
    assert TooManyTargetsException.__name__ in str(exc.value)

    no_valid_targets = find_valid_field_sets(FieldSetSuperclass, [invalid_tgt_with_origin])
    assert no_valid_targets.targets == ()
    assert no_valid_targets.targets_with_origins == ()
    assert no_valid_targets.field_sets == ()

    with pytest.raises(ExecutionError) as exc:
        find_valid_field_sets(
            FieldSetSuperclass, [invalid_tgt_with_origin], error_if_no_applicable_targets=True
        )
    assert NoApplicableTargetsException.__name__ in str(exc.value)


# -----------------------------------------------------------------------------------------------
# Test the Sources field, including codegen. Also see `engine/target_test.py`.
# -----------------------------------------------------------------------------------------------


@pytest.fixture
def sources_rule_runner() -> RuleRunner:
    return RuleRunner(rules=[QueryRule(HydratedSources, (HydrateSourcesRequest,))])


def test_sources_normal_hydration(sources_rule_runner: RuleRunner) -> None:
    addr = Address("src/fortran", target_name=":lib")
    sources_rule_runner.create_files(
        "src/fortran", files=["f1.f95", "f2.f95", "f1.f03", "ignored.f03"]
    )
    sources = Sources(["f1.f95", "*.f03", "!ignored.f03", "!**/ignore*"], address=addr)
    hydrated_sources = sources_rule_runner.request(
        HydratedSources, [HydrateSourcesRequest(sources)]
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


def test_sources_output_type(sources_rule_runner: RuleRunner) -> None:
    class SourcesSubclass(Sources):
        pass

    addr = Address("", target_name=":lib")
    sources_rule_runner.create_files("", files=["f1.f95"])

    valid_sources = SourcesSubclass(["*"], address=addr)
    hydrated_valid_sources = sources_rule_runner.request(
        HydratedSources,
        [HydrateSourcesRequest(valid_sources, for_sources_types=[SourcesSubclass])],
    )
    assert hydrated_valid_sources.snapshot.files == ("f1.f95",)
    assert hydrated_valid_sources.sources_type == SourcesSubclass

    invalid_sources = Sources(["*"], address=addr)
    hydrated_invalid_sources = sources_rule_runner.request(
        HydratedSources,
        [HydrateSourcesRequest(invalid_sources, for_sources_types=[SourcesSubclass])],
    )
    assert hydrated_invalid_sources.snapshot.files == ()
    assert hydrated_invalid_sources.sources_type is None


def test_sources_unmatched_globs(sources_rule_runner: RuleRunner) -> None:
    sources_rule_runner.set_options(["--files-not-found-behavior=error"])
    sources_rule_runner.create_files("", files=["f1.f95"])
    sources = Sources(["non_existent.f95"], address=Address("", target_name="lib"))
    with pytest.raises(ExecutionError) as exc:
        sources_rule_runner.request(HydratedSources, [HydrateSourcesRequest(sources)])
    assert "Unmatched glob" in str(exc.value)
    assert "//:lib" in str(exc.value)
    assert "non_existent.f95" in str(exc.value)


def test_sources_default_globs(sources_rule_runner: RuleRunner) -> None:
    class DefaultSources(Sources):
        default = ("default.f95", "default.f03", "*.f08", "!ignored.f08")

    addr = Address("src/fortran", target_name="lib")
    # NB: Not all globs will be matched with these files, specifically `default.f03` will not
    # be matched. This is intentional to ensure that we use `any` glob conjunction rather
    # than the normal `all` conjunction.
    sources_rule_runner.create_files("src/fortran", files=["default.f95", "f1.f08", "ignored.f08"])
    sources = DefaultSources(None, address=addr)
    assert set(sources.sanitized_raw_value or ()) == set(DefaultSources.default)

    hydrated_sources = sources_rule_runner.request(
        HydratedSources, [HydrateSourcesRequest(sources)]
    )
    assert hydrated_sources.snapshot.files == ("src/fortran/default.f95", "src/fortran/f1.f08")


def test_sources_expected_file_extensions(sources_rule_runner: RuleRunner) -> None:
    class ExpectedExtensionsSources(Sources):
        expected_file_extensions = (".f95", ".f03")

    addr = Address("src/fortran", target_name="lib")
    sources_rule_runner.create_files("src/fortran", files=["s.f95", "s.f03", "s.f08"])
    sources = ExpectedExtensionsSources(["s.f*"], address=addr)
    with pytest.raises(ExecutionError) as exc:
        sources_rule_runner.request(HydratedSources, [HydrateSourcesRequest(sources)])
    assert "s.f08" in str(exc.value)
    assert str(addr) in str(exc.value)

    # Also check that we support valid sources
    valid_sources = ExpectedExtensionsSources(["s.f95"], address=addr)
    assert sources_rule_runner.request(
        HydratedSources, [HydrateSourcesRequest(valid_sources)]
    ).snapshot.files == ("src/fortran/s.f95",)


def test_sources_expected_num_files(sources_rule_runner: RuleRunner) -> None:
    class ExpectedNumber(Sources):
        expected_num_files = 2

    class ExpectedRange(Sources):
        # We allow for 1 or 3 files
        expected_num_files = range(1, 4, 2)

    sources_rule_runner.create_files("", files=["f1.txt", "f2.txt", "f3.txt", "f4.txt"])

    def hydrate(sources_cls: Type[Sources], sources: Iterable[str]) -> HydratedSources:
        return sources_rule_runner.request(
            HydratedSources,
            [
                HydrateSourcesRequest(
                    sources_cls(sources, address=Address("", target_name=":example"))
                ),
            ],
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

    # Many codegen implementations will need to look up a protocol target's dependencies in their
    # rule. We add this here to ensure that this does not result in rule graph issues.
    _ = await Get(TransitiveTargets, Addresses([request.protocol_target.address]))

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
            QueryRule(UnionMembership, ()),
            QueryRule(HydratedSources, (HydrateSourcesRequest,)),
            QueryRule(GeneratedSources, (GenerateSmalltalkFromAvroRequest,)),
            UnionRule(GenerateSourcesRequest, GenerateSmalltalkFromAvroRequest),
        )

    @classmethod
    def target_types(cls):
        return [AvroLibrary]

    def setUp(self) -> None:
        self.address = Address("src/avro", target_name="lib")
        self.create_files("src/avro", files=["f.avro"])
        self.add_to_build_file("src/avro", "avro_library(name='lib', sources=['*.avro'])")
        self.union_membership = self.request(UnionMembership, [])

    def test_generate_sources(self) -> None:
        protocol_sources = AvroSources(["*.avro"], address=self.address)
        assert protocol_sources.can_generate(SmalltalkSources, self.union_membership) is True

        # First, get the original protocol sources.
        hydrated_protocol_sources = self.request(
            HydratedSources, [HydrateSourcesRequest(protocol_sources)]
        )
        assert hydrated_protocol_sources.snapshot.files == ("src/avro/f.avro",)

        # Test directly feeding the protocol sources into the codegen rule.
        tgt = self.request(WrappedTarget, [self.address]).target
        generated_sources = self.request(
            GeneratedSources,
            [
                GenerateSmalltalkFromAvroRequest(hydrated_protocol_sources.snapshot, tgt),
            ],
        )
        assert generated_sources.snapshot.files == ("src/smalltalk/f.st",)

        # Test that HydrateSourcesRequest can also be used.
        generated_via_hydrate_sources = self.request(
            HydratedSources,
            [
                HydrateSourcesRequest(
                    protocol_sources, for_sources_types=[SmalltalkSources], enable_codegen=True
                ),
            ],
        )
        assert generated_via_hydrate_sources.snapshot.files == ("src/smalltalk/f.st",)
        assert generated_via_hydrate_sources.sources_type == SmalltalkSources

    def test_works_with_subclass_fields(self) -> None:
        class CustomAvroSources(AvroSources):
            pass

        protocol_sources = CustomAvroSources(["*.avro"], address=self.address)
        assert protocol_sources.can_generate(SmalltalkSources, self.union_membership) is True
        generated = self.request(
            HydratedSources,
            [
                HydrateSourcesRequest(
                    protocol_sources, for_sources_types=[SmalltalkSources], enable_codegen=True
                ),
            ],
        )
        assert generated.snapshot.files == ("src/smalltalk/f.st",)

    def test_cannot_generate_language(self) -> None:
        class AdaSources(Sources):
            pass

        protocol_sources = AvroSources(["*.avro"], address=self.address)
        assert protocol_sources.can_generate(AdaSources, self.union_membership) is False
        generated = self.request(
            HydratedSources,
            [
                HydrateSourcesRequest(
                    protocol_sources, for_sources_types=[AdaSources], enable_codegen=True
                ),
            ],
        )
        assert generated.snapshot.files == ()
        assert generated.sources_type is None


def test_ambiguous_codegen_implementations_exception() -> None:
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


def test_transitive_excludes_error() -> None:
    class Valid1(Target):
        alias = "valid1"
        core_fields = (MockDependencies,)

    class Valid2(Target):
        alias = "valid2"
        core_fields = (MockDependencies,)

    class Invalid(Target):
        alias = "invalid"
        core_fields = (Dependencies,)

    exc = TransitiveExcludesNotSupportedError(
        bad_value="!!//:bad",
        address=Address("demo"),
        registered_target_types=[Valid1, Valid2, Invalid],
        union_membership=UnionMembership({}),
    )
    assert "Bad value '!!//:bad' in the `dependencies` field for demo." in exc.args[0]
    assert "work with these target types: ['valid1', 'valid2']" in exc.args[0]


def test_parse_dependencies_field() -> None:
    """Ensure that we correctly handle `!` and `!!` ignores.

    We leave the rest of the parsing to AddressInput and Address.
    """
    result = parse_dependencies_field(
        MockDependencies(
            ["a/b/c", "!a/b/c", "f.txt", "!f.txt", "!!transitive_exclude.txt"],
            address=Address("demo/subdir"),
        ),
        subproject_roots=[],
        registered_target_types=[],
        union_membership=UnionMembership({}),
    )
    expected_addresses = {AddressInput("a/b/c"), AddressInput("f.txt")}
    assert set(result.addresses) == expected_addresses
    assert set(result.ignored_addresses) == {
        *expected_addresses,
        AddressInput("transitive_exclude.txt"),
    }


class SmalltalkDependencies(Dependencies):
    supports_transitive_excludes = True


class CustomSmalltalkDependencies(SmalltalkDependencies):
    pass


class InjectSmalltalkDependencies(InjectDependenciesRequest):
    inject_for = SmalltalkDependencies


class InjectCustomSmalltalkDependencies(InjectDependenciesRequest):
    inject_for = CustomSmalltalkDependencies


@rule
def inject_smalltalk_deps(_: InjectSmalltalkDependencies) -> InjectedDependencies:
    return InjectedDependencies(
        [Address("", target_name="injected1"), Address("", target_name="injected2")]
    )


@rule
def inject_custom_smalltalk_deps(_: InjectCustomSmalltalkDependencies) -> InjectedDependencies:
    return InjectedDependencies([Address("", target_name="custom_injected")])


class SmalltalkLibrarySources(SmalltalkSources):
    pass


class SmalltalkLibrary(Target):
    alias = "smalltalk"
    # Note that we use MockDependencies so that we support transitive excludes (`!!`).
    core_fields = (MockDependencies, SmalltalkLibrarySources)


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
    resolved = await MultiGet(
        Get(Address, AddressInput, AddressInput.parse(line)) for line in all_lines
    )
    # NB: See `test_depends_on_subtargets` for why we set the field
    # `sibling_dependencies_inferrable` this way.
    return InferredDependencies(resolved, sibling_dependencies_inferrable=bool(resolved))


@pytest.fixture
def dependencies_rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            inject_smalltalk_deps,
            inject_custom_smalltalk_deps,
            infer_smalltalk_dependencies,
            QueryRule(Addresses, (DependenciesRequest,)),
            UnionRule(InjectDependenciesRequest, InjectSmalltalkDependencies),
            UnionRule(InjectDependenciesRequest, InjectCustomSmalltalkDependencies),
            UnionRule(InferDependenciesRequest, InferSmalltalkDependencies),
        ],
        target_types=[SmalltalkLibrary],
    )


def assert_dependencies_resolved(
    rule_runner: RuleRunner,
    *,
    requested_address: Address,
    expected: Iterable[Address],
) -> None:
    target = rule_runner.get_target(requested_address)
    result = rule_runner.request(
        Addresses,
        [DependenciesRequest(target[Dependencies])],
    )
    assert sorted(result) == sorted(expected)


def test_normal_resolution(dependencies_rule_runner: RuleRunner) -> None:
    dependencies_rule_runner.add_to_build_file(
        "src/smalltalk", "smalltalk(dependencies=['//:dep1', '//:dep2', ':sibling'])"
    )
    assert_dependencies_resolved(
        dependencies_rule_runner,
        requested_address=Address("src/smalltalk"),
        expected=[
            Address("", target_name="dep1"),
            Address("", target_name="dep2"),
            Address("src/smalltalk", target_name="sibling"),
        ],
    )

    # Also test that we handle no dependencies.
    dependencies_rule_runner.add_to_build_file("no_deps", "smalltalk()")
    assert_dependencies_resolved(
        dependencies_rule_runner, requested_address=Address("no_deps"), expected=[]
    )

    # An ignore should override an include.
    dependencies_rule_runner.add_to_build_file(
        "ignore", "smalltalk(dependencies=['//:dep1', '!//:dep1', '//:dep2', '!!//:dep2'])"
    )
    assert_dependencies_resolved(
        dependencies_rule_runner, requested_address=Address("ignore"), expected=[]
    )


def test_explicit_file_dependencies(dependencies_rule_runner: RuleRunner) -> None:
    dependencies_rule_runner.create_files(
        "src/smalltalk/util", ["f1.st", "f2.st", "f3.st", "f4.st"]
    )
    dependencies_rule_runner.add_to_build_file("src/smalltalk/util", "smalltalk(sources=['*.st'])")
    dependencies_rule_runner.add_to_build_file(
        "src/smalltalk",
        dedent(
            """\
            smalltalk(
              dependencies=[
                './util/f1.st',
                'src/smalltalk/util/f2.st',
                './util/f3.st',
                './util/f4.st',
                '!./util/f3.st',
                '!!./util/f4.st',
              ]
            )
            """
        ),
    )
    assert_dependencies_resolved(
        dependencies_rule_runner,
        requested_address=Address("src/smalltalk"),
        expected=[
            Address("src/smalltalk/util", relative_file_path="f1.st", target_name="util"),
            Address("src/smalltalk/util", relative_file_path="f2.st", target_name="util"),
        ],
    )


def test_dependency_injection(dependencies_rule_runner: RuleRunner) -> None:
    dependencies_rule_runner.add_to_build_file("", "smalltalk(name='target')")

    def assert_injected(deps_cls: Type[Dependencies], *, injected: List[Address]) -> None:
        provided_deps = ["//:provided"]
        if injected:
            provided_deps.append("!//:injected2")
        deps_field = deps_cls(provided_deps, address=Address("", target_name="target"))
        result = dependencies_rule_runner.request(Addresses, [DependenciesRequest(deps_field)])
        assert result == Addresses(sorted([*injected, Address("", target_name="provided")]))

    assert_injected(Dependencies, injected=[])
    assert_injected(SmalltalkDependencies, injected=[Address("", target_name="injected1")])
    assert_injected(
        CustomSmalltalkDependencies,
        injected=[
            Address("", target_name="custom_injected"),
            Address("", target_name="injected1"),
        ],
    )


def test_dependency_inference(dependencies_rule_runner: RuleRunner) -> None:
    """We test that dependency inference works generally and that we merge it correctly with
    explicitly provided dependencies.

    For consistency, dep inference does not merge generated subtargets with base targets: if both
    are inferred, expansion to Targets will remove the redundancy while converting to subtargets.
    """
    dependencies_rule_runner.create_files(
        "",
        [
            "inferred1.st",
            "inferred2.st",
            "inferred_but_ignored1.st",
            "inferred_but_ignored2.st",
            "inferred_and_provided1.st",
            "inferred_and_provided2.st",
        ],
    )
    dependencies_rule_runner.add_to_build_file(
        "",
        dedent(
            """\
            smalltalk(name='inferred1')
            smalltalk(name='inferred2')
            smalltalk(name='inferred_but_ignored1', sources=['inferred_but_ignored1.st'])
            smalltalk(name='inferred_but_ignored2', sources=['inferred_but_ignored2.st'])
            smalltalk(name='inferred_and_provided1')
            smalltalk(name='inferred_and_provided2')
            """
        ),
    )
    dependencies_rule_runner.create_file(
        "demo/f1.st",
        dedent(
            """\
            //:inferred1
            inferred2.st:inferred2
            """
        ),
    )
    dependencies_rule_runner.create_file(
        "demo/f2.st",
        dedent(
            """\
            //:inferred_and_provided1
            inferred_and_provided2.st:inferred_and_provided2
            inferred_but_ignored1.st:inferred_but_ignored1
            //:inferred_but_ignored2
            """
        ),
    )
    dependencies_rule_runner.add_to_build_file(
        "demo",
        dedent(
            """\
            smalltalk(
              sources=['*.st'],
              dependencies=[
                '//:inferred_and_provided1',
                '//:inferred_and_provided2',
                '!inferred_but_ignored1.st:inferred_but_ignored1',
                '!//:inferred_but_ignored2',
              ],
            )
            """
        ),
    )

    assert_dependencies_resolved(
        dependencies_rule_runner,
        requested_address=Address("demo"),
        expected=[
            Address("", target_name="inferred1"),
            Address("", relative_file_path="inferred2.st", target_name="inferred2"),
            Address("", target_name="inferred_and_provided1"),
            Address("", target_name="inferred_and_provided2"),
            Address(
                "",
                relative_file_path="inferred_and_provided2.st",
                target_name="inferred_and_provided2",
            ),
            Address("demo", relative_file_path="f1.st"),
            Address("demo", relative_file_path="f2.st"),
        ],
    )

    assert_dependencies_resolved(
        dependencies_rule_runner,
        requested_address=Address("demo", relative_file_path="f1.st", target_name="demo"),
        expected=[
            Address("", target_name="inferred1"),
            Address("", relative_file_path="inferred2.st", target_name="inferred2"),
            Address("", target_name="inferred_and_provided1"),
            Address("", target_name="inferred_and_provided2"),
        ],
    )

    assert_dependencies_resolved(
        dependencies_rule_runner,
        requested_address=Address("demo", relative_file_path="f2.st", target_name="demo"),
        expected=[
            Address("", target_name="inferred_and_provided1"),
            Address("", target_name="inferred_and_provided2"),
            Address(
                "",
                relative_file_path="inferred_and_provided2.st",
                target_name="inferred_and_provided2",
            ),
        ],
    )


def test_depends_on_subtargets(dependencies_rule_runner: RuleRunner) -> None:
    """If the address is a base target, or none of the dependency inference rules can infer
    dependencies on sibling files, then we should depend on all the base target's subtargets."""
    dependencies_rule_runner.create_file("src/smalltalk/f1.st")
    dependencies_rule_runner.create_file("src/smalltalk/f2.st")
    dependencies_rule_runner.add_to_build_file("src/smalltalk", "smalltalk(sources=['*.st'])")

    # Test that a base address depends on its subtargets.
    assert_dependencies_resolved(
        dependencies_rule_runner,
        requested_address=Address("src/smalltalk"),
        expected=[
            Address("src/smalltalk", relative_file_path="f1.st"),
            Address("src/smalltalk", relative_file_path="f2.st"),
        ],
    )

    # Test that a file address depends on its siblings if it has no dependency inference rule,
    # or those inference rules do not claim to infer dependencies on siblings.
    assert_dependencies_resolved(
        dependencies_rule_runner,
        requested_address=Address("src/smalltalk", relative_file_path="f1.st"),
        expected=[Address("src/smalltalk", relative_file_path="f2.st")],
    )

    # Now we recreate the files so that the mock dependency inference will have results, which
    # will cause it to claim to be able to infer dependencies on sibling files.
    dependencies_rule_runner.add_to_build_file("src/smalltalk/util", "smalltalk()")
    dependencies_rule_runner.create_file("src/smalltalk/f1.st", "src/smalltalk/util")
    assert_dependencies_resolved(
        dependencies_rule_runner,
        requested_address=Address("src/smalltalk", relative_file_path="f1.st"),
        # We only expect the inferred address, not any dependencies on sibling files.
        expected=[Address("src/smalltalk/util")],
    )
