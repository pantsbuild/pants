# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
import os.path
from dataclasses import dataclass
from pathlib import PurePath
from textwrap import dedent
from typing import Iterable, List, Set, Tuple, Type, cast

import pytest

from pants.base.specs import (
    AddressLiteralSpec,
    AddressSpecs,
    DescendantAddresses,
    FileGlobSpec,
    FileLiteralSpec,
    FilesystemSpec,
    FilesystemSpecs,
    Specs,
)
from pants.base.specs_parser import SpecsParser
from pants.engine.addresses import Address, Addresses, AddressInput, UnparsedAddressInputs
from pants.engine.fs import (
    CreateDigest,
    Digest,
    DigestContents,
    FileContent,
    Snapshot,
    SpecsSnapshot,
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
    _DependencyMapping,
    _DependencyMappingRequest,
    _TargetParametrizations,
)
from pants.engine.internals.parametrize import Parametrize
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.rules import Get, MultiGet, rule
from pants.engine.target import (
    AllTargets,
    AllTargetsRequest,
    AllUnexpandedTargets,
    AsyncFieldMixin,
    CoarsenedTargets,
    Dependencies,
    DependenciesRequest,
    ExplicitlyProvidedDependencies,
    Field,
    FieldDefaultFactoryRequest,
    FieldDefaultFactoryResult,
    FieldSet,
    FilteredTargets,
    GeneratedSources,
    GenerateSourcesRequest,
    HydratedSources,
    HydrateSourcesRequest,
    InferDependenciesRequest,
    InferredDependencies,
    InjectDependenciesRequest,
    InjectedDependencies,
    MultipleSourcesField,
    NoApplicableTargetsBehavior,
    OverridesField,
    SecondaryOwnerMixin,
    SingleSourceField,
    SourcesPaths,
    SourcesPathsRequest,
    SpecialCasedDependencies,
    StringField,
    Tags,
    Target,
    TargetFilesGenerator,
    TargetRootsToFieldSets,
    TargetRootsToFieldSetsRequest,
    Targets,
    TransitiveTargets,
    TransitiveTargetsRequest,
)
from pants.engine.unions import UnionMembership, UnionRule, union
from pants.source.filespec import Filespec
from pants.testutil.rule_runner import QueryRule, RuleRunner, engine_error
from pants.util.ordered_set import FrozenOrderedSet


class MockDependencies(Dependencies):
    supports_transitive_excludes = True
    deprecated_alias = "deprecated_field"
    deprecated_alias_removal_version = "9.9.9.dev0"


class SpecialCasedDeps1(SpecialCasedDependencies):
    alias = "special_cased_deps1"


class SpecialCasedDeps2(SpecialCasedDependencies):
    alias = "special_cased_deps2"


class ResolveField(StringField, AsyncFieldMixin):
    alias = "resolve"
    default = None


_DEFAULT_RESOLVE = "default_test_resolve"


class ResolveFieldDefaultFactoryRequest(FieldDefaultFactoryRequest):
    field_type = ResolveField


@rule
def resolve_field_default_factory(
    request: ResolveFieldDefaultFactoryRequest,
) -> FieldDefaultFactoryResult:
    return FieldDefaultFactoryResult(lambda f: f.value or _DEFAULT_RESOLVE)


class MockTarget(Target):
    alias = "target"
    core_fields = (
        MockDependencies,
        MultipleSourcesField,
        SpecialCasedDeps1,
        SpecialCasedDeps2,
        Tags,
    )
    deprecated_alias = "deprecated_target"
    deprecated_alias_removal_version = "9.9.9.dev0"


class MockGeneratedTarget(Target):
    alias = "generated"
    core_fields = (MockDependencies, Tags, SingleSourceField, ResolveField)


class MockTargetGenerator(TargetFilesGenerator):
    alias = "generator"
    core_fields = (MultipleSourcesField, OverridesField)
    generated_target_cls = MockGeneratedTarget
    copied_fields = ()
    moved_fields = (Dependencies, Tags, ResolveField)


@pytest.fixture
def transitive_targets_rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            QueryRule(AllTargets, [AllTargetsRequest]),
            QueryRule(AllUnexpandedTargets, [AllTargetsRequest]),
            QueryRule(CoarsenedTargets, [Addresses]),
            QueryRule(Targets, [DependenciesRequest]),
            QueryRule(TransitiveTargets, [TransitiveTargetsRequest]),
            QueryRule(FilteredTargets, [Specs]),
        ],
        target_types=[MockTarget, MockTargetGenerator, MockGeneratedTarget],
    )


def test_transitive_targets(transitive_targets_rule_runner: RuleRunner) -> None:
    transitive_targets_rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                target(name='t1')
                target(name='t2', dependencies=[':t1'])
                target(name='d1', dependencies=[':t1'])
                target(name='d2', dependencies=[':t2'])
                target(name='d3')
                target(name='root', dependencies=[':d1', ':d2', ':d3'])
                """
            ),
        }
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
        TransitiveTargets, [TransitiveTargetsRequest([root.address, d2.address])]
    )
    assert transitive_targets.roots == (root, d2)
    # NB: `//:d2` is both a target root and a dependency of `//:root`.
    assert transitive_targets.dependencies == FrozenOrderedSet([d1, d2, d3, t2, t1])
    assert transitive_targets.closure == FrozenOrderedSet([root, d2, d1, d3, t2, t1])


def test_transitive_targets_transitive_exclude(transitive_targets_rule_runner: RuleRunner) -> None:
    transitive_targets_rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                target(name='base')
                target(name='intermediate', dependencies=[':base'])
                target(name='root', dependencies=[':intermediate', '!!:base'])
                """
            ),
        }
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
        TransitiveTargets, [TransitiveTargetsRequest([root.address, intermediate.address])]
    )
    assert transitive_targets.roots == (root, intermediate)
    assert transitive_targets.dependencies == FrozenOrderedSet([intermediate])
    assert transitive_targets.closure == FrozenOrderedSet([root, intermediate])

    # Regression test that we work with deeply nested levels of excludes.
    transitive_targets_rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                target(name='t1')
                target(name='t2', dependencies=[':t1'])
                target(name='t3', dependencies=[':t2'])
                target(name='t4', dependencies=[':t3'])
                target(name='t5', dependencies=[':t4'])
                target(name='t6', dependencies=[':t5'])
                target(name='t7', dependencies=[':t6'])
                target(name='t8', dependencies=[':t7'])
                target(name='t9', dependencies=[':t8'])
                target(name='t10', dependencies=[':t9'])
                target(name='t11', dependencies=[':t10'])
                target(name='t12', dependencies=[':t11'])
                target(name='t13', dependencies=[':t12'])
                target(name='t14', dependencies=[':t13'])
                target(name='t15', dependencies=[':t14', '!!:t1', '!!:t5'])
                """
            ),
        }
    )
    transitive_targets = transitive_targets_rule_runner.request(
        TransitiveTargets, [TransitiveTargetsRequest([get_target("t15").address])]
    )
    assert transitive_targets.dependencies == FrozenOrderedSet(
        [
            get_target("t14"),
            get_target("t13"),
            get_target("t12"),
            get_target("t11"),
            get_target("t10"),
            get_target("t9"),
            get_target("t8"),
            get_target("t7"),
            get_target("t6"),
            get_target("t4"),
            get_target("t3"),
            get_target("t2"),
        ]
    )


def test_special_cased_dependencies(transitive_targets_rule_runner: RuleRunner) -> None:
    """Test that subclasses of `SpecialCasedDependencies` show up if requested, but otherwise are
    left off.

    This uses the same test setup as `test_transitive_targets`, but does not use the `dependencies`
    field like normal.
    """
    transitive_targets_rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                target(name='t1')
                target(name='t2', special_cased_deps1=[':t1'])
                target(name='d1', special_cased_deps1=[':t1'])
                target(name='d2', special_cased_deps2=[':t2'])
                target(name='d3')
                target(name='root', special_cased_deps1=[':d1', ':d2'], special_cased_deps2=[':d3'])
                """
            ),
        }
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
    assert direct_deps == Targets()

    direct_deps = transitive_targets_rule_runner.request(
        Targets, [DependenciesRequest(root[Dependencies], include_special_cased_deps=True)]
    )
    assert direct_deps == Targets([d1, d2, d3])

    transitive_targets = transitive_targets_rule_runner.request(
        TransitiveTargets, [TransitiveTargetsRequest([root.address, d2.address])]
    )
    assert transitive_targets.roots == (root, d2)
    assert transitive_targets.dependencies == FrozenOrderedSet()
    assert transitive_targets.closure == FrozenOrderedSet([root, d2])

    transitive_targets = transitive_targets_rule_runner.request(
        TransitiveTargets,
        [TransitiveTargetsRequest([root.address, d2.address], include_special_cased_deps=True)],
    )
    assert transitive_targets.roots == (root, d2)
    assert transitive_targets.dependencies == FrozenOrderedSet([d1, d2, d3, t2, t1])
    assert transitive_targets.closure == FrozenOrderedSet([root, d2, d1, d3, t2, t1])


# TODO(#12871): Fix this to not be based on generated targets.
def test_transitive_targets_tolerates_generated_target_cycles(
    transitive_targets_rule_runner: RuleRunner,
) -> None:
    """For certain file-level targets like `python_source`, we should tolerate cycles because the
    underlying language tolerates them."""
    transitive_targets_rule_runner.write_files(
        {
            "dep.txt": "",
            "t1.txt": "",
            "t2.txt": "",
            "BUILD": dedent(
                """\
                generator(name='dep', sources=['dep.txt'])
                generator(name='t1', sources=['t1.txt'], dependencies=['dep.txt:dep', 't2.txt:t2'])
                generator(name='t2', sources=['t2.txt'], dependencies=['t1.txt:t1'])
                """
            ),
        }
    )
    result = transitive_targets_rule_runner.request(
        TransitiveTargets,
        [TransitiveTargetsRequest([Address("", target_name="t2")])],
    )
    assert len(result.roots) == 1
    assert result.roots[0].address == Address("", target_name="t2")
    assert [tgt.address for tgt in result.dependencies] == [
        Address("", relative_file_path="t2.txt", target_name="t2"),
        Address("", relative_file_path="t1.txt", target_name="t1"),
        Address("", relative_file_path="dep.txt", target_name="dep"),
    ]


def test_coarsened_targets(transitive_targets_rule_runner: RuleRunner) -> None:
    """CoarsenedTargets should "coarsen" a cycle into a single CoarsenedTarget instance."""
    transitive_targets_rule_runner.write_files(
        {
            "dep.txt": "",
            "t1.txt": "",
            "t2.txt": "",
            # Cycles are only tolerated for file-level targets like `python_source`.
            # TODO(#12871): Stop relying on only generated targets having cycle tolerance.
            "BUILD": dedent(
                """\
                generator(name='dep', sources=['dep.txt'])
                generator(name='t1', sources=['t1.txt'], dependencies=['dep.txt:dep', 't2.txt:t2'])
                generator(name='t2', sources=['t2.txt'], dependencies=['t1.txt:t1'])
                """
            ),
        }
    )

    def assert_coarsened(
        a: Address, expected_members: List[Address], expected_dependencies: List[Address]
    ) -> None:
        coarsened_targets = transitive_targets_rule_runner.request(
            CoarsenedTargets,
            [Addresses([a])],
        )
        assert sorted(t.address for t in coarsened_targets[0].members) == expected_members
        # NB: Only the direct dependencies are compared.
        assert (
            sorted(d.address for ct in coarsened_targets[0].dependencies for d in ct.members)
            == expected_dependencies
        )

    # Non-file-level targets are already validated to not have cycles, so they coarsen to
    # themselves.
    assert_coarsened(
        Address("", target_name="dep"),
        [Address("", target_name="dep")],
        [Address("", relative_file_path="dep.txt", target_name="dep")],
    )
    assert_coarsened(
        Address("", target_name="t1"),
        [Address("", target_name="t1")],
        [
            Address("", relative_file_path="t1.txt", target_name="t1"),
            Address("", relative_file_path="t2.txt", target_name="t2"),
        ],
    )
    assert_coarsened(
        Address("", target_name="t2"),
        [Address("", target_name="t2")],
        [
            Address("", relative_file_path="t1.txt", target_name="t1"),
            Address("", relative_file_path="t2.txt", target_name="t2"),
        ],
    )

    # File-level targets not involved in cycles coarsen to themselves.
    assert_coarsened(
        Address("", relative_file_path="dep.txt", target_name="dep"),
        [Address("", relative_file_path="dep.txt", target_name="dep")],
        [],
    )

    # File-level targets involved in cycles will coarsen to the cycle, and have only dependencies
    # outside of the cycle.
    cycle_files = [
        Address("", relative_file_path="t1.txt", target_name="t1"),
        Address("", relative_file_path="t2.txt", target_name="t2"),
    ]
    assert_coarsened(
        Address("", relative_file_path="t1.txt", target_name="t1"),
        cycle_files,
        [Address("", relative_file_path="dep.txt", target_name="dep")],
    )
    assert_coarsened(
        Address("", relative_file_path="t2.txt", target_name="t2"),
        cycle_files,
        [Address("", relative_file_path="dep.txt", target_name="dep")],
    )


def assert_failed_cycle(
    rule_runner: RuleRunner,
    *,
    root_target_name: str,
    subject_target_name: str,
    path_target_names: Tuple[str, ...],
) -> None:
    with pytest.raises(ExecutionError) as e:
        rule_runner.request(
            TransitiveTargets,
            [TransitiveTargetsRequest([Address("", target_name=root_target_name)])],
        )
    (cycle_exception,) = e.value.wrapped_exceptions
    assert isinstance(cycle_exception, CycleException)
    assert cycle_exception.subject == Address("", target_name=subject_target_name)
    assert cycle_exception.path == tuple(Address("", target_name=p) for p in path_target_names)


def test_dep_cycle_self(transitive_targets_rule_runner: RuleRunner) -> None:
    transitive_targets_rule_runner.write_files({"BUILD": "target(name='t1', dependencies=[':t1'])"})
    assert_failed_cycle(
        transitive_targets_rule_runner,
        root_target_name="t1",
        subject_target_name="t1",
        path_target_names=("t1", "t1"),
    )


def test_dep_cycle_direct(transitive_targets_rule_runner: RuleRunner) -> None:
    transitive_targets_rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                target(name='t1', dependencies=[':t2'])
                target(name='t2', dependencies=[':t1'])
                """
            )
        }
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
    transitive_targets_rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                target(name='t1', dependencies=[':t2'])
                target(name='t2', dependencies=[':t3'])
                target(name='t3', dependencies=[':t2'])
                """
            )
        }
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


def test_dep_no_cycle_indirect(transitive_targets_rule_runner: RuleRunner) -> None:
    transitive_targets_rule_runner.write_files(
        {
            "t1.txt": "",
            "t2.txt": "",
            # TODO(#12871): Stop relying on only generated targets having cycle tolerance.
            "BUILD": dedent(
                """\
                generator(name='t1', dependencies=['t2.txt:t2'], sources=['t1.txt'])
                generator(name='t2', dependencies=[':t1'], sources=['t2.txt'])
                """
            ),
        }
    )
    result = transitive_targets_rule_runner.request(
        TransitiveTargets,
        [TransitiveTargetsRequest([Address("", target_name="t1")])],
    )
    assert len(result.roots) == 1
    assert result.roots[0].address == Address("", target_name="t1")
    assert {tgt.address for tgt in result.dependencies} == {
        Address("", relative_file_path="t1.txt", target_name="t1"),
        Address("", relative_file_path="t2.txt", target_name="t2"),
    }


def test_deprecated_field_name(transitive_targets_rule_runner: RuleRunner, caplog) -> None:
    transitive_targets_rule_runner.write_files({"BUILD": "target(name='t', deprecated_field=[])"})
    transitive_targets_rule_runner.get_target(Address("", target_name="t"))
    assert len(caplog.records) == 1
    assert "Instead, use `dependencies`" in caplog.text


def test_resolve_deprecated_target_name(transitive_targets_rule_runner: RuleRunner, caplog) -> None:
    transitive_targets_rule_runner.write_files({"BUILD": "deprecated_target(name='t')"})
    transitive_targets_rule_runner.get_target(Address("", target_name="t"))
    assert len(caplog.records) == 1
    assert "Instead, use `target`" in caplog.text


def test_resolve_generated_target(transitive_targets_rule_runner: RuleRunner) -> None:
    transitive_targets_rule_runner.write_files(
        {
            "f1.txt": "",
            "f2.txt": "",
            "f3.txt": "",
            "no_owner.txt": "",
            "BUILD": dedent(
                """\
                generator(name='generator', sources=['f1.txt', 'f2.txt'])
                target(name='non-generator', sources=['f1.txt'])
                """
            ),
        }
    )
    generated_target_address = Address("", target_name="generator", relative_file_path="f1.txt")
    assert transitive_targets_rule_runner.get_target(
        generated_target_address
    ) == MockGeneratedTarget({SingleSourceField.alias: "f1.txt"}, generated_target_address)

    # The target generator must actually generate the requested target.
    with pytest.raises(ExecutionError):
        transitive_targets_rule_runner.get_target(
            Address("", target_name="generator", relative_file_path="no_owner.txt")
        )

    # TODO: Using a "file address" on a target that does not generate file-level targets will fall
    # back to the target generator. See https://github.com/pantsbuild/pants/issues/14419.
    non_generator_file_address = Address(
        "", target_name="non-generator", relative_file_path="f1.txt"
    )
    assert transitive_targets_rule_runner.get_target(non_generator_file_address) == MockTarget(
        {MultipleSourcesField.alias: ["f1.txt"]},
        non_generator_file_address.maybe_convert_to_target_generator(),
    )


def test_find_all_targets(transitive_targets_rule_runner: RuleRunner) -> None:
    transitive_targets_rule_runner.write_files(
        {
            "f1.txt": "",
            "f2.txt": "",
            "f3.txt": "",
            "no_owner.txt": "",
            "BUILD": dedent(
                """\
                generator(name='generator', sources=['f1.txt', 'f2.txt'])
                target(name='non-generator', sources=['f1.txt'])
                """
            ),
            "dir/BUILD": "target()",
        }
    )
    all_tgts = transitive_targets_rule_runner.request(AllTargets, [AllTargetsRequest()])
    expected = {
        Address("", target_name="generator", relative_file_path="f1.txt"),
        Address("", target_name="generator", relative_file_path="f2.txt"),
        Address("", target_name="non-generator"),
        Address("dir"),
    }
    assert {t.address for t in all_tgts} == expected

    all_unexpanded = transitive_targets_rule_runner.request(
        AllUnexpandedTargets, [AllTargetsRequest()]
    )
    assert {t.address for t in all_unexpanded} == {*expected, Address("", target_name="generator")}


def test_filtered_targets(transitive_targets_rule_runner: RuleRunner) -> None:
    transitive_targets_rule_runner.write_files(
        {
            "addr_specs/f1.txt": "",
            "addr_specs/f2.txt": "",
            "addr_specs/BUILD": dedent(
                """\
                generator(
                    sources=["*.txt"],
                    tags=["a"],
                    overrides={"f2.txt": {"tags": ["b"]}},
                )

                target(name='t', tags=["a"])
                """
            ),
            "fs_specs/f1.txt": "",
            "fs_specs/f2.txt": "",
            "fs_specs/BUILD": dedent(
                """\
                generator(
                    sources=["*.txt"],
                    tags=["a"],
                    overrides={"f2.txt": {"tags": ["b"]}},
                )

                target(name='t', sources=["f1.txt"], tags=["a"])
                """
            ),
        }
    )
    specs = Specs(
        AddressSpecs([DescendantAddresses("addr_specs")], filter_by_global_options=True),
        FilesystemSpecs([FileGlobSpec("fs_specs/*.txt")]),
    )

    def check(tags_option: str | None, expected: set[Address]) -> None:
        if tags_option:
            transitive_targets_rule_runner.set_options([f"--tag={tags_option}"])
        result = transitive_targets_rule_runner.request(FilteredTargets, [specs])
        assert {t.address for t in result} == expected

    addr_f1 = Address("addr_specs", relative_file_path="f1.txt")
    addr_f2 = Address("addr_specs", relative_file_path="f2.txt")
    addr_direct = Address("addr_specs", target_name="t")

    fs_f1 = Address("fs_specs", relative_file_path="f1.txt")
    fs_f2 = Address("fs_specs", relative_file_path="f2.txt")
    fs_direct = Address("fs_specs", target_name="t")

    all_a_tags = {addr_f1, addr_direct, fs_f1, fs_direct}
    all_b_tags = {addr_f2, fs_f2}

    check(None, {*all_a_tags, *all_b_tags})
    check("a", all_a_tags)
    check("b", all_b_tags)
    check("-a", all_b_tags)
    check("-b", all_a_tags)


def test_resolve_specs_snapshot() -> None:
    """This tests that convert filesystem specs and/or address specs into a single snapshot.

    Some important edge cases:
    - When a filesystem spec refers to a file without any owning target, it should be included
      in the snapshot.
    - If a file is covered both by an address spec and by a filesystem spec, we should merge it
      so that the file only shows up once.
    """
    rule_runner = RuleRunner(rules=[QueryRule(SpecsSnapshot, (Specs,))], target_types=[MockTarget])
    rule_runner.write_files(
        {"demo/f1.txt": "", "demo/f2.txt": "", "demo/BUILD": "target(sources=['*.txt'])"}
    )
    specs = SpecsParser(rule_runner.build_root).parse_specs(
        ["demo:demo", "demo/f1.txt", "demo/BUILD"]
    )
    result = rule_runner.request(SpecsSnapshot, [specs])
    assert result.snapshot.files == ("demo/BUILD", "demo/f1.txt", "demo/f2.txt")


class MockSecondaryOwnerField(StringField, AsyncFieldMixin, SecondaryOwnerMixin):
    alias = "secondary_owner_field"
    required = True

    @property
    def filespec(self) -> Filespec:
        return {"includes": [os.path.join(self.address.spec_path, cast(str, self.value))]}


class MockSecondaryOwnerTarget(Target):
    alias = "secondary_owner"
    core_fields = (MockSecondaryOwnerField,)


@pytest.fixture
def owners_rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            QueryRule(Owners, [OwnersRequest]),
        ],
        target_types=[
            MockTarget,
            MockTargetGenerator,
            MockGeneratedTarget,
            MockSecondaryOwnerTarget,
        ],
    )


def assert_owners(
    rule_runner: RuleRunner, requested: Iterable[str], *, expected: Set[Address]
) -> None:
    result = rule_runner.request(Owners, [OwnersRequest(tuple(requested))])
    assert set(result) == expected


def test_owners_source_file_does_not_exist(owners_rule_runner: RuleRunner) -> None:
    """Test when a source file belongs to a target, even though the file does not actually exist.

    This happens, for example, when the file is deleted and we're computing `--changed-since`. In
    this case, we can only use target generators rather than their generated targets.
    """
    owners_rule_runner.write_files(
        {
            "demo/f.txt": "",
            "demo/BUILD": dedent(
                """\
                target(name='not-generator', sources=['*.txt'])
                generator(name='generator', sources=['*.txt'])
                secondary_owner(name='secondary', secondary_owner_field='deleted.txt')
                """
            ),
        }
    )
    assert_owners(
        owners_rule_runner,
        ["demo/deleted.txt"],
        expected={
            Address("demo", target_name="generator"),
            Address("demo", target_name="not-generator"),
            Address("demo", target_name="secondary"),
        },
    )

    # For files that do exist, we should use generated targets when possible.
    assert_owners(
        owners_rule_runner,
        ["demo/f.txt"],
        expected={
            Address("demo", target_name="generator", relative_file_path="f.txt"),
            Address("demo", target_name="not-generator"),
        },
    )

    # If another generated target comes from the same target generator, then both that generated
    # target and its generator should be used.
    assert_owners(
        owners_rule_runner,
        ["demo/f.txt", "demo/deleted.txt"],
        expected={
            Address("demo", target_name="generator", relative_file_path="f.txt"),
            Address("demo", target_name="generator"),
            Address("demo", target_name="not-generator"),
            Address("demo", target_name="secondary"),
        },
    )


def test_owners_multiple_owners(owners_rule_runner: RuleRunner) -> None:
    owners_rule_runner.write_files(
        {
            "demo/f1.txt": "",
            "demo/f2.txt": "",
            "demo/BUILD": dedent(
                """\
                target(name='not-generator-all', sources=['*.txt'])
                target(name='not-generator-f2', sources=['f2.txt'])
                generator(name='generator-all', sources=['*.txt'])
                generator(name='generator-f2', sources=['f2.txt'])
                secondary_owner(name='secondary', secondary_owner_field='f1.txt')
                """
            ),
        }
    )
    assert_owners(
        owners_rule_runner,
        ["demo/f1.txt"],
        expected={
            Address("demo", target_name="generator-all", relative_file_path="f1.txt"),
            Address("demo", target_name="not-generator-all"),
            Address("demo", target_name="secondary"),
        },
    )
    assert_owners(
        owners_rule_runner,
        ["demo/f2.txt"],
        expected={
            Address("demo", target_name="generator-all", relative_file_path="f2.txt"),
            Address("demo", target_name="not-generator-all"),
            Address("demo", target_name="generator-f2", relative_file_path="f2.txt"),
            Address("demo", target_name="not-generator-f2"),
        },
    )


def test_owners_build_file(owners_rule_runner: RuleRunner) -> None:
    """A BUILD file owns every target defined in it."""
    owners_rule_runner.write_files(
        {
            "demo/f1.txt": "",
            "demo/f2.txt": "",
            "demo/BUILD": dedent(
                """\
                target(name='f1', sources=['f1.txt'])
                target(name='f2_first', sources=['f2.txt'])
                target(name='f2_second', sources=['f2.txt'])
                generator(name='generated', sources=['*.txt'])
                secondary_owner(name='secondary', secondary_owner_field='f1.txt')
                """
            ),
        }
    )
    assert_owners(
        owners_rule_runner,
        ["demo/BUILD"],
        expected={
            Address("demo", target_name="f1"),
            Address("demo", target_name="f2_first"),
            Address("demo", target_name="f2_second"),
            Address("demo", target_name="secondary"),
            Address("demo", target_name="generated", relative_file_path="f1.txt"),
            Address("demo", target_name="generated", relative_file_path="f2.txt"),
        },
    )


@pytest.fixture
def specs_rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            QueryRule(Addresses, [FilesystemSpecs]),
            QueryRule(Addresses, [Specs]),
        ],
        target_types=[MockTarget, MockTargetGenerator, MockGeneratedTarget],
    )


def resolve_filesystem_specs(
    rule_runner: RuleRunner,
    specs: Iterable[FilesystemSpec],
) -> List[Address]:
    result = rule_runner.request(Addresses, [FilesystemSpecs(specs)])
    return sorted(result)


def test_filesystem_specs_literal_file(specs_rule_runner: RuleRunner) -> None:
    specs_rule_runner.write_files(
        {
            "demo/f1.txt": "",
            "demo/f2.txt": "",
            "demo/BUILD": dedent(
                """\
                generator(name='generator', sources=['*.txt'])
                target(name='not-generator', sources=['*.txt'])
                """
            ),
        }
    )
    assert resolve_filesystem_specs(specs_rule_runner, [FileLiteralSpec("demo/f1.txt")]) == [
        Address("demo", target_name="not-generator"),
        Address("demo", target_name="generator", relative_file_path="f1.txt"),
    ]


def test_filesystem_specs_glob(specs_rule_runner: RuleRunner) -> None:
    specs_rule_runner.write_files(
        {
            "demo/f1.txt": "",
            "demo/f2.txt": "",
            "demo/BUILD": dedent(
                """\
                generator(name='generator', sources=['*.txt'])
                target(name='not-generator', sources=['*.txt'])
                target(name='skip-me', sources=['*.txt'])
                target(name='bad-tag', sources=['*.txt'], tags=['skip'])
                """
            ),
        }
    )
    specs_rule_runner.set_options(["--tag=-skip", "--exclude-target-regexp=skip-me"])
    all_unskipped_addresses = [
        Address("demo", target_name="not-generator"),
        Address("demo", target_name="generator", relative_file_path="f1.txt"),
        Address("demo", target_name="generator", relative_file_path="f2.txt"),
    ]

    assert (
        resolve_filesystem_specs(specs_rule_runner, [FileGlobSpec("demo/*.txt")])
        == all_unskipped_addresses
    )
    # We should deduplicate between glob and literal specs.
    assert (
        resolve_filesystem_specs(
            specs_rule_runner,
            [FileGlobSpec("demo/*.txt"), FileLiteralSpec("demo/f1.txt")],
        )
        == all_unskipped_addresses
    )


def test_filesystem_specs_nonexistent_file(specs_rule_runner: RuleRunner) -> None:
    spec = FileLiteralSpec("demo/fake.txt")
    with engine_error(contains='Unmatched glob from file/directory arguments: "demo/fake.txt"'):
        resolve_filesystem_specs(specs_rule_runner, [spec])

    specs_rule_runner.set_options(["--owners-not-found-behavior=ignore"])
    assert not resolve_filesystem_specs(specs_rule_runner, [spec])


def test_filesystem_specs_no_owner(specs_rule_runner: RuleRunner) -> None:
    specs_rule_runner.write_files({"no_owners/f.txt": ""})
    # Error for literal specs.
    with pytest.raises(ExecutionError) as exc:
        resolve_filesystem_specs(specs_rule_runner, [FileLiteralSpec("no_owners/f.txt")])
    assert "No owning targets could be found for the file `no_owners/f.txt`" in str(exc.value)

    # Do not error for glob specs.
    assert not resolve_filesystem_specs(specs_rule_runner, [FileGlobSpec("no_owners/*.txt")])


def test_resolve_addresses_from_specs(specs_rule_runner: RuleRunner) -> None:
    """This tests that we correctly handle resolving from both address and filesystem specs."""
    specs_rule_runner.write_files(
        {
            "fs_spec/f.txt": "",
            "fs_spec/BUILD": "generator(sources=['f.txt'])",
            "address_spec/f.txt": "",
            "address_spec/BUILD": "generator(sources=['f.txt'])",
            "multiple_files/f1.txt": "",
            "multiple_files/f2.txt": "",
            "multiple_files/BUILD": "generator(sources=['*.txt'])",
        }
    )

    no_interaction_specs = ["fs_spec/f.txt", "address_spec:address_spec"]
    multiple_files_specs = ["multiple_files/f2.txt", "multiple_files:multiple_files"]
    specs = SpecsParser(specs_rule_runner.build_root).parse_specs(
        [*no_interaction_specs, *multiple_files_specs]
    )

    result = specs_rule_runner.request(Addresses, [specs])
    assert set(result) == {
        Address("fs_spec", relative_file_path="f.txt"),
        Address("address_spec"),
        Address("multiple_files"),
        Address("multiple_files", relative_file_path="f2.txt"),
    }


# -----------------------------------------------------------------------------------------------
# Test file-level target generation and parameterization.
# -----------------------------------------------------------------------------------------------


@pytest.fixture
def generated_targets_rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            QueryRule(Addresses, [Specs]),
            QueryRule(_DependencyMapping, [_DependencyMappingRequest]),
            QueryRule(_TargetParametrizations, [Address]),
            UnionRule(FieldDefaultFactoryRequest, ResolveFieldDefaultFactoryRequest),
            resolve_field_default_factory,
        ],
        target_types=[MockTargetGenerator, MockGeneratedTarget],
        objects={"parametrize": Parametrize},
    )


def assert_generated(
    rule_runner: RuleRunner,
    address: Address,
    build_content: str,
    files: list[str],
    expected_targets: set[Target] | None = None,
    *,
    expected_dependencies: dict[str, set[str]] | None = None,
) -> None:
    rule_runner.write_files(
        {
            f"{address.spec_path}/BUILD": build_content,
            **{os.path.join(address.spec_path, f): "" for f in files},
        }
    )
    parametrizations = rule_runner.request(_TargetParametrizations, [address])
    if expected_targets is not None:
        assert expected_targets == {
            t
            for parametrization in parametrizations
            for t in parametrization.parametrization.values()
        }

    if expected_dependencies is not None:
        # TODO: Adjust the `TransitiveTargets` API to expose the complete mapping.
        #   see https://github.com/pantsbuild/pants/issues/11270
        specs = SpecsParser(rule_runner.build_root).parse_specs(["::"])
        addresses = rule_runner.request(Addresses, [specs])
        dependency_mapping = rule_runner.request(
            _DependencyMapping,
            [
                _DependencyMappingRequest(
                    TransitiveTargetsRequest(addresses),
                    expanded_targets=False,
                )
            ],
        )
        assert {
            k.spec: {a.spec for a in v} for k, v in dependency_mapping.mapping.items()
        } == expected_dependencies


def test_generate_multiple(generated_targets_rule_runner: RuleRunner) -> None:
    assert_generated(
        generated_targets_rule_runner,
        Address("demo"),
        "generator(tags=['tag'], sources=['*.ext'])",
        ["f1.ext", "f2.ext"],
        {
            MockGeneratedTarget(
                {SingleSourceField.alias: "f1.ext", Tags.alias: ["tag"]},
                Address("demo", relative_file_path="f1.ext"),
                residence_dir="demo",
            ),
            MockGeneratedTarget(
                {SingleSourceField.alias: "f2.ext", Tags.alias: ["tag"]},
                Address("demo", relative_file_path="f2.ext"),
                residence_dir="demo",
            ),
        },
    )


def test_generate_subdir(generated_targets_rule_runner: RuleRunner) -> None:
    assert_generated(
        generated_targets_rule_runner,
        Address("src/fortran", target_name="demo"),
        "generator(name='demo', sources=['**/*.f95'])",
        ["subdir/demo.f95"],
        {
            MockGeneratedTarget(
                {SingleSourceField.alias: "subdir/demo.f95"},
                Address("src/fortran", target_name="demo", relative_file_path="subdir/demo.f95"),
                residence_dir="src/fortran/subdir",
            )
        },
    )


def test_generate_overrides(generated_targets_rule_runner: RuleRunner) -> None:
    assert_generated(
        generated_targets_rule_runner,
        Address("example"),
        "generator(sources=['*.ext'], tags=['override_me'], overrides={'f1.ext': {'tags': ['overridden']}})",
        ["f1.ext"],
        {
            MockGeneratedTarget(
                {
                    SingleSourceField.alias: "f1.ext",
                    Tags.alias: ["overridden"],
                },
                Address("example", relative_file_path="f1.ext"),
            ),
        },
    )


def test_generate_overrides_unused(generated_targets_rule_runner: RuleRunner) -> None:
    with engine_error(
        contains="Unused file paths in the `overrides` field for demo:demo: ['fake.ext']"
    ):
        assert_generated(
            generated_targets_rule_runner,
            Address("demo"),
            "generator(sources=['*.ext'], overrides={'fake.ext': {'tags': ['irrelevant']}})",
            ["f1.ext"],
            set(),
        )


def test_parametrize(generated_targets_rule_runner: RuleRunner) -> None:
    assert_generated(
        generated_targets_rule_runner,
        Address("demo"),
        "generator(tags=parametrize(t1=['t1'], t2=['t2']), sources=['f1.ext'])",
        ["f1.ext"],
        {
            MockGeneratedTarget(
                {SingleSourceField.alias: "f1.ext", Tags.alias: ["t1"]},
                Address("demo", relative_file_path="f1.ext", parameters={"tags": "t1"}),
                residence_dir="demo",
            ),
            MockGeneratedTarget(
                {SingleSourceField.alias: "f1.ext", Tags.alias: ["t2"]},
                Address("demo", relative_file_path="f1.ext", parameters={"tags": "t2"}),
                residence_dir="demo",
            ),
        },
        expected_dependencies={
            "demo@tags=t1": {"demo/f1.ext@tags=t1"},
            "demo@tags=t2": {"demo/f1.ext@tags=t2"},
            "demo/f1.ext@tags=t1": set(),
            "demo/f1.ext@tags=t2": set(),
        },
    )


def test_parametrize_multi(generated_targets_rule_runner: RuleRunner) -> None:
    assert_generated(
        generated_targets_rule_runner,
        Address("demo"),
        "generator(tags=parametrize(t1=['t1'], t2=['t2']), resolve=parametrize('a', 'b'), sources=['f1.ext'])",
        ["f1.ext"],
        {
            MockGeneratedTarget(
                {SingleSourceField.alias: "f1.ext", Tags.alias: ["t1"], ResolveField.alias: "a"},
                Address(
                    "demo", relative_file_path="f1.ext", parameters={"tags": "t1", "resolve": "a"}
                ),
                residence_dir="demo",
            ),
            MockGeneratedTarget(
                {SingleSourceField.alias: "f1.ext", Tags.alias: ["t2"], ResolveField.alias: "a"},
                Address(
                    "demo", relative_file_path="f1.ext", parameters={"tags": "t2", "resolve": "a"}
                ),
                residence_dir="demo",
            ),
            MockGeneratedTarget(
                {SingleSourceField.alias: "f1.ext", Tags.alias: ["t1"], ResolveField.alias: "b"},
                Address(
                    "demo", relative_file_path="f1.ext", parameters={"tags": "t1", "resolve": "b"}
                ),
                residence_dir="demo",
            ),
            MockGeneratedTarget(
                {SingleSourceField.alias: "f1.ext", Tags.alias: ["t2"], ResolveField.alias: "b"},
                Address(
                    "demo", relative_file_path="f1.ext", parameters={"tags": "t2", "resolve": "b"}
                ),
                residence_dir="demo",
            ),
        },
    )


def test_parametrize_overrides(generated_targets_rule_runner: RuleRunner) -> None:
    assert_generated(
        generated_targets_rule_runner,
        Address("demo"),
        "generator(overrides={'f1.ext': {'resolve': parametrize('a', 'b')}}, resolve='c', sources=['*.ext'])",
        ["f1.ext", "f2.ext"],
        {
            MockGeneratedTarget(
                {SingleSourceField.alias: "f1.ext", ResolveField.alias: "a"},
                Address("demo", relative_file_path="f1.ext", parameters={"resolve": "a"}),
                residence_dir="demo",
            ),
            MockGeneratedTarget(
                {SingleSourceField.alias: "f1.ext", ResolveField.alias: "b"},
                Address("demo", relative_file_path="f1.ext", parameters={"resolve": "b"}),
                residence_dir="demo",
            ),
            MockGeneratedTarget(
                {SingleSourceField.alias: "f2.ext", ResolveField.alias: "c"},
                Address("demo", relative_file_path="f2.ext"),
                residence_dir="demo",
            ),
        },
        expected_dependencies={
            "demo:demo": {
                "demo/f1.ext@resolve=a",
                "demo/f1.ext@resolve=b",
                "demo/f2.ext",
            },
            "demo/f1.ext@resolve=a": set(),
            "demo/f1.ext@resolve=b": set(),
            "demo/f2.ext": set(),
        },
    )


def test_parametrize_atom(generated_targets_rule_runner: RuleRunner) -> None:
    assert_generated(
        generated_targets_rule_runner,
        Address("demo"),
        "generated(resolve=parametrize('a', 'b'), source='f1.ext')",
        ["f1.ext"],
        {
            MockGeneratedTarget(
                {SingleSourceField.alias: "f1.ext", ResolveField.alias: "a"},
                Address("demo", target_name="demo", parameters={"resolve": "a"}),
                residence_dir="demo",
            ),
            MockGeneratedTarget(
                {SingleSourceField.alias: "f1.ext", ResolveField.alias: "b"},
                Address("demo", target_name="demo", parameters={"resolve": "b"}),
                residence_dir="demo",
            ),
        },
        expected_dependencies={
            "demo@resolve=a": set(),
            "demo@resolve=b": set(),
        },
    )


def test_parametrize_partial_atom_to_atom(generated_targets_rule_runner: RuleRunner) -> None:
    assert_generated(
        generated_targets_rule_runner,
        Address("demo", target_name="t2"),
        dedent(
            """\
            generated(
              name='t1',
              resolve=parametrize('a', 'b'),
              source='f1.ext',
            )
            generated(
              name='t2',
              resolve=parametrize('a', 'b'),
              source='f2.ext',
              dependencies=[':t1'],
            )
            """
        ),
        ["f1.ext", "f2.ext"],
        expected_dependencies={
            "demo:t1@resolve=a": set(),
            "demo:t1@resolve=b": set(),
            "demo:t2@resolve=a": {"demo:t1@resolve=a"},
            "demo:t2@resolve=b": {"demo:t1@resolve=b"},
        },
    )
    assert_generated(
        generated_targets_rule_runner,
        Address("demo", target_name="t2"),
        dedent(
            """\
            generated(
              name='t1',
              resolve=parametrize('default_test_resolve', 'b'),
              source='f1.ext',
            )
            generated(
              name='t2',
              source='f2.ext',
              dependencies=[':t1'],
            )
            """
        ),
        ["f1.ext", "f2.ext"],
        expected_dependencies={
            "demo:t1@resolve=default_test_resolve": set(),
            "demo:t1@resolve=b": set(),
            "demo:t2": {"demo:t1@resolve=default_test_resolve"},
        },
    )


def test_parametrize_partial_generator_to_generator(
    generated_targets_rule_runner: RuleRunner,
) -> None:
    assert_generated(
        generated_targets_rule_runner,
        Address("demo", target_name="t2"),
        dedent(
            """\
            generator(
              name='t1',
              resolve=parametrize('a', 'b'),
              sources=['f1.ext'],
            )
            generator(
              name='t2',
              resolve=parametrize('a', 'b'),
              sources=['f2.ext'],
              dependencies=[':t1'],
            )
            """
        ),
        ["f1.ext", "f2.ext"],
        expected_dependencies={
            "demo/f1.ext:t1@resolve=a": set(),
            "demo/f1.ext:t1@resolve=b": set(),
            "demo/f2.ext:t2@resolve=a": {"demo:t1@resolve=a"},
            "demo/f2.ext:t2@resolve=b": {"demo:t1@resolve=b"},
            "demo:t1@resolve=a": {
                "demo/f1.ext:t1@resolve=a",
            },
            "demo:t1@resolve=b": {
                "demo/f1.ext:t1@resolve=b",
            },
            "demo:t2@resolve=a": {
                "demo/f2.ext:t2@resolve=a",
            },
            "demo:t2@resolve=b": {
                "demo/f2.ext:t2@resolve=b",
            },
        },
    )


def test_parametrize_partial_generator_to_generated(
    generated_targets_rule_runner: RuleRunner,
) -> None:
    assert_generated(
        generated_targets_rule_runner,
        Address("demo", target_name="t2"),
        dedent(
            """\
            generator(
              name='t1',
              resolve=parametrize('a', 'b'),
              sources=['f1.ext'],
            )
            generator(
              name='t2',
              resolve=parametrize('a', 'b'),
              sources=['f2.ext'],
              dependencies=['./f1.ext:t1'],
            )
            """
        ),
        ["f1.ext", "f2.ext"],
        expected_dependencies={
            "demo/f1.ext:t1@resolve=a": set(),
            "demo/f1.ext:t1@resolve=b": set(),
            "demo/f2.ext:t2@resolve=a": {"demo/f1.ext:t1@resolve=a"},
            "demo/f2.ext:t2@resolve=b": {"demo/f1.ext:t1@resolve=b"},
            "demo:t1@resolve=a": {
                "demo/f1.ext:t1@resolve=a",
            },
            "demo:t1@resolve=b": {
                "demo/f1.ext:t1@resolve=b",
            },
            "demo:t2@resolve=a": {
                "demo/f2.ext:t2@resolve=a",
            },
            "demo:t2@resolve=b": {
                "demo/f2.ext:t2@resolve=b",
            },
        },
    )


def test_parametrize_partial_exclude(generated_targets_rule_runner: RuleRunner) -> None:
    assert_generated(
        generated_targets_rule_runner,
        Address("demo", target_name="t2"),
        dedent(
            """\
            generator(
              name='t1',
              resolve=parametrize('a', 'b'),
              sources=['f1.ext', 'f2.ext'],
            )
            generator(
              name='t2',
              resolve=parametrize('a', 'b'),
              sources=['f3.ext'],
              dependencies=[
                './f1.ext:t1',
                './f2.ext:t1',
                '!./f2.ext:t1',
              ],
            )
            """
        ),
        ["f1.ext", "f2.ext", "f3.ext"],
        expected_dependencies={
            "demo/f1.ext:t1@resolve=a": set(),
            "demo/f2.ext:t1@resolve=a": set(),
            "demo/f1.ext:t1@resolve=b": set(),
            "demo/f2.ext:t1@resolve=b": set(),
            "demo/f3.ext:t2@resolve=a": {"demo/f1.ext:t1@resolve=a"},
            "demo/f3.ext:t2@resolve=b": {"demo/f1.ext:t1@resolve=b"},
            "demo:t1@resolve=a": {
                "demo/f1.ext:t1@resolve=a",
                "demo/f2.ext:t1@resolve=a",
            },
            "demo:t1@resolve=b": {
                "demo/f1.ext:t1@resolve=b",
                "demo/f2.ext:t1@resolve=b",
            },
            "demo:t2@resolve=a": {
                "demo/f3.ext:t2@resolve=a",
            },
            "demo:t2@resolve=b": {
                "demo/f3.ext:t2@resolve=b",
            },
        },
    )


def test_parametrize_16190(generated_targets_rule_runner: RuleRunner) -> None:
    class ParentField(Field):
        alias = "parent"
        help = "foo"

    class ChildField(ParentField):
        alias = "child"
        help = "foo"

    class ParentTarget(Target):
        alias = "parent_tgt"
        help = "foo"
        core_fields = (ParentField, Dependencies)

    class ChildTarget(Target):
        alias = "child_tgt"
        help = "foo"
        core_fields = (ChildField, Dependencies)

    rule_runner = RuleRunner(
        rules=generated_targets_rule_runner.rules,
        target_types=[ParentTarget, ChildTarget],
        objects={"parametrize": Parametrize},
    )
    build_content = dedent(
        """\
        child_tgt(name="child", child=parametrize("a", "b"))
        parent_tgt(name="parent", parent=parametrize("a", "b"), dependencies=[":child"])
        """
    )
    assert_generated(
        rule_runner,
        Address("demo", target_name="child"),
        build_content,
        [],
        expected_dependencies={
            "demo:child@child=a": set(),
            "demo:child@child=b": set(),
            "demo:parent@parent=a": {"demo:child@child=a"},
            "demo:parent@parent=b": {"demo:child@child=b"},
        },
    )


# -----------------------------------------------------------------------------------------------
# Test FieldSets. Also see `engine/target_test.py`.
# -----------------------------------------------------------------------------------------------

# Must be defined here because `from __future__ import annotations` causes the FieldSet to not be
# able to find the type..
class FortranSources(MultipleSourcesField):
    pass


def test_find_valid_field_sets(caplog) -> None:
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
            QueryRule(TargetRootsToFieldSets, [TargetRootsToFieldSetsRequest, Specs]),
            UnionRule(FieldSetSuperclass, FieldSetSubclass1),
            UnionRule(FieldSetSuperclass, FieldSetSubclass2),
        ],
        target_types=[FortranTarget, InvalidTarget],
    )

    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                fortran_target(name="valid")
                fortran_target(name="valid2")
                invalid_target(name="invalid")
                """
            )
        }
    )
    valid_tgt = FortranTarget({}, Address("", target_name="valid"))
    valid_spec = AddressLiteralSpec("", "valid")
    invalid_spec = AddressLiteralSpec("", "invalid")

    def find_valid_field_sets(
        superclass: Type,
        address_specs: Iterable[AddressLiteralSpec],
        *,
        no_applicable_behavior: NoApplicableTargetsBehavior = NoApplicableTargetsBehavior.ignore,
        expect_single_config: bool = False,
    ) -> TargetRootsToFieldSets:
        request = TargetRootsToFieldSetsRequest(
            superclass,
            goal_description="fake",
            no_applicable_targets_behavior=no_applicable_behavior,
            expect_single_field_set=expect_single_config,
        )
        return rule_runner.request(
            TargetRootsToFieldSets,
            [request, Specs(AddressSpecs(address_specs), FilesystemSpecs([]))],
        )

    valid = find_valid_field_sets(FieldSetSuperclass, [valid_spec, invalid_spec])
    assert valid.targets == (valid_tgt,)
    assert valid.field_sets == (
        FieldSetSubclass1.create(valid_tgt),
        FieldSetSubclass2.create(valid_tgt),
    )

    with pytest.raises(ExecutionError) as exc:
        find_valid_field_sets(FieldSetSuperclass, [valid_spec], expect_single_config=True)
    assert AmbiguousImplementationsException.__name__ in str(exc.value)

    with pytest.raises(ExecutionError) as exc:
        find_valid_field_sets(
            FieldSetSuperclass,
            [valid_spec, AddressLiteralSpec("", "valid2")],
            expect_single_config=True,
        )
    assert TooManyTargetsException.__name__ in str(exc.value)

    no_valid_targets = find_valid_field_sets(FieldSetSuperclass, [invalid_spec])
    assert no_valid_targets.targets == ()
    assert no_valid_targets.field_sets == ()

    with pytest.raises(ExecutionError) as exc:
        find_valid_field_sets(
            FieldSetSuperclass,
            [invalid_spec],
            no_applicable_behavior=NoApplicableTargetsBehavior.error,
        )
    assert NoApplicableTargetsException.__name__ in str(exc.value)

    caplog.clear()
    find_valid_field_sets(
        FieldSetSuperclass,
        [invalid_spec],
        no_applicable_behavior=NoApplicableTargetsBehavior.warn,
    )
    assert len(caplog.records) == 1
    assert "No applicable files or targets matched." in caplog.text


def test_no_applicable_targets_exception() -> None:
    # Check that we correctly render the error message.
    class Tgt1(Target):
        alias = "tgt1"
        core_fields = ()

    class Tgt2(Target):
        alias = "tgt2"
        core_fields = (MultipleSourcesField,)

    class Tgt3(Target):
        alias = "tgt3"
        core_fields = ()

    # No targets/files specified. Because none of the relevant targets have a sources field, we do
    # not give the filedeps command.
    exc = NoApplicableTargetsException(
        [],
        Specs(AddressSpecs([]), FilesystemSpecs([])),
        UnionMembership({}),
        applicable_target_types=[Tgt1],
        goal_description="the `foo` goal",
    )
    remedy = (
        "Please specify relevant files and/or targets. Run `./pants filter --target-type=tgt1 ::` "
        "to find all applicable targets in your project."
    )
    assert (
        dedent(
            f"""\
            No files or targets specified. The `foo` goal works with these target types:

              * tgt1

            {remedy}"""
        )
        in str(exc)
    )

    invalid_tgt = Tgt3({}, Address("blah"))
    exc = NoApplicableTargetsException(
        [invalid_tgt],
        Specs(AddressSpecs([]), FilesystemSpecs([FileLiteralSpec("foo.ext")])),
        UnionMembership({}),
        applicable_target_types=[Tgt1, Tgt2],
        goal_description="the `foo` goal",
    )
    remedy = (
        "Please specify relevant files and/or targets. Run `./pants filter "
        "--target-type=tgt1,tgt2 ::` to find all applicable targets in your project, or run "
        "`./pants filter --target-type=tgt1,tgt2 :: | xargs ./pants filedeps` to find all "
        "applicable files."
    )
    assert (
        dedent(
            f"""\
            No applicable files or targets matched. The `foo` goal works with these target types:

              * tgt1
              * tgt2

            However, you only specified files with these target types:

              * tgt3

            {remedy}"""
        )
        in str(exc)
    )

    # Test handling of `Specs`.
    exc = NoApplicableTargetsException(
        [invalid_tgt],
        Specs(AddressSpecs([AddressLiteralSpec("foo", "bar")]), FilesystemSpecs([])),
        UnionMembership({}),
        applicable_target_types=[Tgt1],
        goal_description="the `foo` goal",
    )
    assert "However, you only specified targets with these target types:" in str(exc)
    exc = NoApplicableTargetsException(
        [invalid_tgt],
        Specs(
            AddressSpecs([AddressLiteralSpec("foo", "bar")]),
            FilesystemSpecs([FileLiteralSpec("foo.ext")]),
        ),
        UnionMembership({}),
        applicable_target_types=[Tgt1],
        goal_description="the `foo` goal",
    )
    assert "However, you only specified files and targets with these target types:" in str(exc)


# -----------------------------------------------------------------------------------------------
# Test `SourcesField`. Also see `engine/target_test.py`.
# -----------------------------------------------------------------------------------------------


@pytest.fixture
def sources_rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            QueryRule(HydratedSources, [HydrateSourcesRequest]),
            QueryRule(SourcesPaths, [SourcesPathsRequest]),
        ]
    )


def test_sources_normal_hydration(sources_rule_runner: RuleRunner) -> None:
    addr = Address("src/fortran", target_name="lib")
    sources_rule_runner.write_files(
        {f"src/fortran/{f}": "" for f in ["f1.f95", "f2.f95", "f1.f03", "ignored.f03"]}
    )
    sources = MultipleSourcesField(["f1.f95", "*.f03", "!ignored.f03", "!**/ignore*"], addr)
    hydrated_sources = sources_rule_runner.request(
        HydratedSources, [HydrateSourcesRequest(sources)]
    )
    assert hydrated_sources.snapshot.files == ("src/fortran/f1.f03", "src/fortran/f1.f95")

    single_source = SingleSourceField("f1.f95", addr)
    hydrated_single_source = sources_rule_runner.request(
        HydratedSources, [HydrateSourcesRequest(single_source)]
    )
    assert hydrated_single_source.snapshot.files == ("src/fortran/f1.f95",)

    # Test that `SourcesPaths` works too.
    sources_paths = sources_rule_runner.request(SourcesPaths, [SourcesPathsRequest(sources)])
    assert sources_paths.files == ("src/fortran/f1.f03", "src/fortran/f1.f95")
    sources_paths = sources_rule_runner.request(SourcesPaths, [SourcesPathsRequest(single_source)])
    assert sources_paths.files == ("src/fortran/f1.f95",)

    # Also test that the Filespec is correct. This does not need the engine to be calculated.
    assert (
        sources.filespec
        == {
            "includes": ["src/fortran/f1.f95", "src/fortran/*.f03"],
            "excludes": ["src/fortran/ignored.f03", "src/fortran/**/ignore*"],
        }
        == hydrated_sources.filespec
    )
    assert (
        single_source.filespec
        == {"includes": ["src/fortran/f1.f95"]}
        == hydrated_single_source.filespec
    )


def test_sources_output_type(sources_rule_runner: RuleRunner) -> None:
    class SourcesSubclass(MultipleSourcesField):
        pass

    class SingleSourceSubclass(SingleSourceField):
        pass

    addr = Address("", target_name="lib")
    sources_rule_runner.write_files({f: "" for f in ["f1.f95"]})

    valid_sources = SourcesSubclass(["*"], addr)
    hydrated_valid_sources = sources_rule_runner.request(
        HydratedSources,
        [HydrateSourcesRequest(valid_sources, for_sources_types=[SourcesSubclass])],
    )
    assert hydrated_valid_sources.snapshot.files == ("f1.f95",)
    assert hydrated_valid_sources.sources_type == SourcesSubclass

    valid_single_sources = SingleSourceSubclass("f1.f95", addr)
    hydrated_valid_sources = sources_rule_runner.request(
        HydratedSources,
        [HydrateSourcesRequest(valid_single_sources, for_sources_types=[SingleSourceSubclass])],
    )
    assert hydrated_valid_sources.snapshot.files == ("f1.f95",)
    assert hydrated_valid_sources.sources_type == SingleSourceSubclass

    invalid_sources = MultipleSourcesField(["*"], addr)
    hydrated_invalid_sources = sources_rule_runner.request(
        HydratedSources,
        [HydrateSourcesRequest(invalid_sources, for_sources_types=[SourcesSubclass])],
    )
    assert hydrated_invalid_sources.snapshot.files == ()
    assert hydrated_invalid_sources.sources_type is None

    invalid_single_sources = SingleSourceField("f1.f95", addr)
    hydrated_invalid_sources = sources_rule_runner.request(
        HydratedSources,
        [HydrateSourcesRequest(invalid_single_sources, for_sources_types=[SingleSourceSubclass])],
    )
    assert hydrated_invalid_sources.snapshot.files == ()
    assert hydrated_invalid_sources.sources_type is None


def test_sources_unmatched_globs(sources_rule_runner: RuleRunner) -> None:
    sources_rule_runner.set_options(["--files-not-found-behavior=error"])
    sources_rule_runner.write_files({f: "" for f in ["f1.f95"]})
    sources = MultipleSourcesField(["non_existent.f95"], Address("", target_name="lib"))
    with engine_error(contains="non_existent.f95"):
        sources_rule_runner.request(HydratedSources, [HydrateSourcesRequest(sources)])

    single_sources = SingleSourceField("non_existent.f95", Address("", target_name="lib"))
    with engine_error(contains="non_existent.f95"):
        sources_rule_runner.request(HydratedSources, [HydrateSourcesRequest(single_sources)])


def test_sources_default_globs(sources_rule_runner: RuleRunner) -> None:
    class DefaultSources(MultipleSourcesField):
        default = ("default.f95", "default.f03", "*.f08", "!ignored.f08")

    addr = Address("src/fortran", target_name="lib")
    # NB: Not all globs will be matched with these files, specifically `default.f03` will not
    # be matched. This is intentional to ensure that we use `any` glob conjunction rather
    # than the normal `all` conjunction.
    sources_rule_runner.write_files(
        {f"src/fortran/{f}": "" for f in ["default.f95", "f1.f08", "ignored.f08"]}
    )
    sources = DefaultSources(None, addr)
    assert set(sources.value or ()) == set(DefaultSources.default)

    hydrated_sources = sources_rule_runner.request(
        HydratedSources, [HydrateSourcesRequest(sources)]
    )
    assert hydrated_sources.snapshot.files == ("src/fortran/default.f95", "src/fortran/f1.f08")


def test_sources_expected_file_extensions(sources_rule_runner: RuleRunner) -> None:
    class ExpectedExtensionsSources(MultipleSourcesField):
        expected_file_extensions = (".f95", ".f03", "")

    class ExpectedExtensionsSingleSource(SingleSourceField):
        expected_file_extensions = (".f95", ".f03", "")

    addr = Address("src/fortran", target_name="lib")
    sources_rule_runner.write_files(
        {f"src/fortran/{f}": "" for f in ["s.f95", "s.f03", "s.f08", "s"]}
    )

    def get_source(src: str) -> str:
        sources = sources_rule_runner.request(
            HydratedSources, [HydrateSourcesRequest(ExpectedExtensionsSources([src], addr))]
        ).snapshot.files
        single_source = sources_rule_runner.request(
            HydratedSources, [HydrateSourcesRequest(ExpectedExtensionsSingleSource(src, addr))]
        ).snapshot.files
        assert sources == single_source
        assert len(sources) == 1
        return sources[0]

    with engine_error(contains="['src/fortran/s.f08']"):
        get_source("s.f08")

    # Also check that we support valid sources
    assert get_source("s.f95") == "src/fortran/s.f95"
    assert get_source("s") == "src/fortran/s"


def test_sources_expected_num_files(sources_rule_runner: RuleRunner) -> None:
    class ExpectedNumber(MultipleSourcesField):
        expected_num_files = 2

    class ExpectedRange(MultipleSourcesField):
        # We allow for 1 or 3 files
        expected_num_files = range(1, 4, 2)

    sources_rule_runner.write_files({f: "" for f in ["f1.txt", "f2.txt", "f3.txt", "f4.txt"]})

    def hydrate(sources_cls: Type[MultipleSourcesField], sources: Iterable[str]) -> HydratedSources:
        return sources_rule_runner.request(
            HydratedSources,
            [
                HydrateSourcesRequest(sources_cls(sources, Address("", target_name="example"))),
            ],
        )

    with engine_error(contains="must have 2 files"):
        hydrate(ExpectedNumber, [])
    with engine_error(contains="must have 1 or 3 files"):
        hydrate(ExpectedRange, ["f1.txt", "f2.txt"])

    # Also check that we support valid # files.
    assert hydrate(ExpectedNumber, ["f1.txt", "f2.txt"]).snapshot.files == ("f1.txt", "f2.txt")
    assert hydrate(ExpectedRange, ["f1.txt"]).snapshot.files == ("f1.txt",)
    assert hydrate(ExpectedRange, ["f1.txt", "f2.txt", "f3.txt"]).snapshot.files == (
        "f1.txt",
        "f2.txt",
        "f3.txt",
    )


# -----------------------------------------------------------------------------------------------
# Test codegen. Also see `engine/target_test.py`.
# -----------------------------------------------------------------------------------------------


class SmalltalkSource(SingleSourceField):
    pass


class AvroSources(MultipleSourcesField):
    pass


class AvroLibrary(Target):
    alias = "avro_library"
    core_fields = (AvroSources,)


class GenerateSmalltalkFromAvroRequest(GenerateSourcesRequest):
    input = AvroSources
    output = SmalltalkSource


@rule
async def generate_smalltalk_from_avro(
    request: GenerateSmalltalkFromAvroRequest,
) -> GeneratedSources:
    protocol_files = request.protocol_sources.files

    # Many codegen implementations will need to look up a protocol target's dependencies in their
    # rule. We add this here to ensure that this does not result in rule graph issues.
    _ = await Get(TransitiveTargets, TransitiveTargetsRequest([request.protocol_target.address]))

    def generate_fortran(fp: str) -> FileContent:
        parent = str(PurePath(fp).parent).replace("src/avro", "src/smalltalk")
        file_name = f"{PurePath(fp).stem}.st"
        return FileContent(str(PurePath(parent, file_name)), b"Generated")

    result = await Get(Snapshot, CreateDigest([generate_fortran(fp) for fp in protocol_files]))
    return GeneratedSources(result)


@pytest.fixture
def codegen_rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            generate_smalltalk_from_avro,
            QueryRule(HydratedSources, [HydrateSourcesRequest]),
            QueryRule(GeneratedSources, [GenerateSmalltalkFromAvroRequest]),
            UnionRule(GenerateSourcesRequest, GenerateSmalltalkFromAvroRequest),
        ],
        target_types=[AvroLibrary],
    )


def setup_codegen_protocol_tgt(rule_runner: RuleRunner) -> Address:
    rule_runner.write_files(
        {"src/avro/f.avro": "", "src/avro/BUILD": "avro_library(name='lib', sources=['*.avro'])"}
    )
    return Address("src/avro", target_name="lib")


def test_codegen_generates_sources(codegen_rule_runner: RuleRunner) -> None:
    addr = setup_codegen_protocol_tgt(codegen_rule_runner)
    protocol_sources = AvroSources(["*.avro"], addr)
    assert (
        protocol_sources.can_generate(SmalltalkSource, codegen_rule_runner.union_membership) is True
    )

    # First, get the original protocol sources.
    hydrated_protocol_sources = codegen_rule_runner.request(
        HydratedSources, [HydrateSourcesRequest(protocol_sources)]
    )
    assert hydrated_protocol_sources.snapshot.files == ("src/avro/f.avro",)

    # Test directly feeding the protocol sources into the codegen rule.
    tgt = codegen_rule_runner.get_target(addr)
    generated_sources = codegen_rule_runner.request(
        GeneratedSources,
        [GenerateSmalltalkFromAvroRequest(hydrated_protocol_sources.snapshot, tgt)],
    )
    assert generated_sources.snapshot.files == ("src/smalltalk/f.st",)

    # Test that HydrateSourcesRequest can also be used.
    generated_via_hydrate_sources = codegen_rule_runner.request(
        HydratedSources,
        [
            HydrateSourcesRequest(
                protocol_sources, for_sources_types=[SmalltalkSource], enable_codegen=True
            )
        ],
    )
    assert generated_via_hydrate_sources.snapshot.files == ("src/smalltalk/f.st",)
    assert generated_via_hydrate_sources.sources_type == SmalltalkSource


def test_codegen_works_with_subclass_fields(codegen_rule_runner: RuleRunner) -> None:
    addr = setup_codegen_protocol_tgt(codegen_rule_runner)

    class CustomAvroSources(AvroSources):
        pass

    protocol_sources = CustomAvroSources(["*.avro"], addr)
    assert (
        protocol_sources.can_generate(SmalltalkSource, codegen_rule_runner.union_membership) is True
    )
    generated = codegen_rule_runner.request(
        HydratedSources,
        [
            HydrateSourcesRequest(
                protocol_sources, for_sources_types=[SmalltalkSource], enable_codegen=True
            )
        ],
    )
    assert generated.snapshot.files == ("src/smalltalk/f.st",)


def test_codegen_cannot_generate_language(codegen_rule_runner: RuleRunner) -> None:
    addr = setup_codegen_protocol_tgt(codegen_rule_runner)

    class AdaSources(MultipleSourcesField):
        pass

    protocol_sources = AvroSources(["*.avro"], addr)
    assert protocol_sources.can_generate(AdaSources, codegen_rule_runner.union_membership) is False
    generated = codegen_rule_runner.request(
        HydratedSources,
        [
            HydrateSourcesRequest(
                protocol_sources, for_sources_types=[AdaSources], enable_codegen=True
            )
        ],
    )
    assert generated.snapshot.files == ()
    assert generated.sources_type is None


def test_ambiguous_codegen_implementations_exception() -> None:
    # This error message is quite complex. We test that it correctly generates the message.
    class SmalltalkGenerator1(GenerateSourcesRequest):
        input = AvroSources
        output = SmalltalkSource

    class SmalltalkGenerator2(GenerateSourcesRequest):
        input = AvroSources
        output = SmalltalkSource

    class AdaSources(MultipleSourcesField):
        pass

    class AdaGenerator(GenerateSourcesRequest):
        input = AvroSources
        output = AdaSources

    class IrrelevantSources(MultipleSourcesField):
        pass

    # Test when all generators have the same input and output.
    exc = AmbiguousCodegenImplementationsException.create(
        [SmalltalkGenerator1, SmalltalkGenerator2], for_sources_types=[SmalltalkSource]
    )
    assert "can generate SmalltalkSource from AvroSources" in str(exc)
    assert "* SmalltalkGenerator1" in str(exc)
    assert "* SmalltalkGenerator2" in str(exc)

    # Test when the generators have different input and output, which usually happens because
    # the call site used too expansive of a `for_sources_types` argument.
    exc = AmbiguousCodegenImplementationsException.create(
        [SmalltalkGenerator1, AdaGenerator],
        for_sources_types=[SmalltalkSource, AdaSources, IrrelevantSources],
    )
    assert "can generate one of ['AdaSources', 'SmalltalkSource'] from AvroSources" in str(exc)
    assert "IrrelevantSources" not in str(exc)
    assert "* SmalltalkGenerator1 -> SmalltalkSource" in str(exc)
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
    assert "Bad value '!!//:bad' in the `dependencies` field for demo:demo" in exc.args[0]
    assert "work with these target types: ['valid1', 'valid2']" in exc.args[0]


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


class SmalltalkLibrarySource(SmalltalkSource):
    pass


class SmalltalkLibrary(Target):
    alias = "smalltalk_library"
    # Note that we use MockDependencies so that we support transitive excludes (`!!`).
    core_fields = (MockDependencies, SmalltalkLibrarySource)


class SmalltalkLibraryGenerator(TargetFilesGenerator):
    alias = "smalltalk_libraries"
    core_fields = (MultipleSourcesField,)
    generated_target_cls = SmalltalkLibrary
    copied_fields = ()
    # Note that we use MockDependencies so that we support transitive excludes (`!!`).
    moved_fields = (MockDependencies,)


class InferSmalltalkDependencies(InferDependenciesRequest):
    infer_from = SmalltalkLibrarySource


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
    return InferredDependencies(resolved)


@pytest.fixture
def dependencies_rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            inject_smalltalk_deps,
            inject_custom_smalltalk_deps,
            infer_smalltalk_dependencies,
            QueryRule(Addresses, [DependenciesRequest]),
            QueryRule(ExplicitlyProvidedDependencies, [DependenciesRequest]),
            UnionRule(InjectDependenciesRequest, InjectSmalltalkDependencies),
            UnionRule(InjectDependenciesRequest, InjectCustomSmalltalkDependencies),
            UnionRule(InferDependenciesRequest, InferSmalltalkDependencies),
        ],
        target_types=[SmalltalkLibrary, SmalltalkLibraryGenerator, MockTarget],
    )


def assert_dependencies_resolved(
    rule_runner: RuleRunner,
    requested_address: Address,
    *,
    expected: Iterable[Address],
) -> None:
    target = rule_runner.get_target(requested_address)
    result = rule_runner.request(Addresses, [DependenciesRequest(target.get(Dependencies))])
    assert sorted(result) == sorted(expected)


def test_explicitly_provided_dependencies(dependencies_rule_runner: RuleRunner) -> None:
    """Ensure that we correctly handle `!` and `!!` ignores.

    We leave the rest of the parsing to AddressInput and Address.
    """
    dependencies_rule_runner.write_files(
        {
            "files/f.txt": "",
            "files/transitive_exclude.txt": "",
            "files/BUILD": "smalltalk_libraries(sources=['*.txt'])",
            "a/b/c/BUILD": "smalltalk_libraries()",
            "demo/subdir/BUILD": dedent(
                """\
                target(
                    dependencies=[
                        'a/b/c',
                        '!a/b/c',
                        'files/f.txt',
                        '!files/f.txt',
                        '!!files/transitive_exclude.txt',
                    ],
                )
                """
            ),
        }
    )
    target = dependencies_rule_runner.get_target(Address("demo/subdir"))
    result = dependencies_rule_runner.request(
        ExplicitlyProvidedDependencies, [DependenciesRequest(target[Dependencies])]
    )
    assert result.address == target.address
    expected_addresses = {Address("a/b/c"), Address("files", relative_file_path="f.txt")}
    assert set(result.includes) == expected_addresses
    assert set(result.ignores) == {
        *expected_addresses,
        Address("files", relative_file_path="transitive_exclude.txt"),
    }


def test_normal_resolution(dependencies_rule_runner: RuleRunner) -> None:
    dependencies_rule_runner.write_files(
        {
            "src/smalltalk/BUILD": dedent(
                """\
                target(dependencies=['//:dep1', '//:dep2', ':sibling'])
                target(name='sibling')
                """
            ),
            "no_deps/BUILD": "target()",
            # An ignore should override an include.
            "ignore/BUILD": (
                "target(dependencies=['//:dep1', '!//:dep1', '//:dep2', '!!//:dep2'])"
            ),
            "BUILD": dedent(
                """\
                target(name='dep1')
                target(name='dep2')
                """
            ),
        }
    )
    assert_dependencies_resolved(
        dependencies_rule_runner,
        Address("src/smalltalk"),
        expected=[
            Address("", target_name="dep1"),
            Address("", target_name="dep2"),
            Address("src/smalltalk", target_name="sibling"),
        ],
    )
    assert_dependencies_resolved(dependencies_rule_runner, Address("no_deps"), expected=[])
    assert_dependencies_resolved(dependencies_rule_runner, Address("ignore"), expected=[])


def test_explicit_file_dependencies(dependencies_rule_runner: RuleRunner) -> None:
    dependencies_rule_runner.write_files(
        {
            "src/smalltalk/util/f1.st": "",
            "src/smalltalk/util/f2.st": "",
            "src/smalltalk/util/f3.st": "",
            "src/smalltalk/util/f4.st": "",
            "src/smalltalk/util/BUILD": "smalltalk_libraries(sources=['*.st'])",
            "src/smalltalk/BUILD": dedent(
                """\
                target(
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
        }
    )
    assert_dependencies_resolved(
        dependencies_rule_runner,
        Address("src/smalltalk"),
        expected=[
            Address("src/smalltalk/util", relative_file_path="f1.st", target_name="util"),
            Address("src/smalltalk/util", relative_file_path="f2.st", target_name="util"),
        ],
    )


def test_dependency_injection(dependencies_rule_runner: RuleRunner) -> None:
    dependencies_rule_runner.write_files(
        {
            "src/smalltalk/util/f1.st": "",
            "BUILD": dedent(
                """\
                smalltalk_libraries(name='target', sources=['*.st'])
                target(name='provided')
                target(name='injected2')
                """
            ),
        }
    )

    def assert_injected(deps_cls: Type[Dependencies], *, injected: List[Address]) -> None:
        provided_deps = ["//:provided"]
        if injected:
            provided_deps.append("!//:injected2")
        deps_field = deps_cls(provided_deps, Address("", target_name="target"))
        result = dependencies_rule_runner.request(Addresses, [DependenciesRequest(deps_field)])
        assert result == Addresses(sorted((*injected, Address("", target_name="provided"))))

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

    For consistency, dep inference does not merge generated subtargets with BUILD targets: if both
    are inferred, expansion to Targets will remove the redundancy while converting to subtargets.
    """
    dependencies_rule_runner.write_files(
        {
            "inferred1.st": "",
            "inferred2.st": "",
            "inferred_but_ignored1.st": "",
            "inferred_but_ignored2.st": "",
            "inferred_and_provided1.st": "",
            "inferred_and_provided2.st": "",
            "BUILD": dedent(
                """\
                smalltalk_libraries(name='inferred1')
                smalltalk_libraries(name='inferred2')
                smalltalk_libraries(name='inferred_but_ignored1', sources=['inferred_but_ignored1.st'])
                smalltalk_libraries(name='inferred_but_ignored2', sources=['inferred_but_ignored2.st'])
                target(name='inferred_and_provided1')
                target(name='inferred_and_provided2')
                """
            ),
            "demo/f1.st": dedent(
                """\
                //:inferred1
                inferred2.st:inferred2
                """
            ),
            "demo/f2.st": dedent(
                """\
                //:inferred_and_provided1
                inferred_and_provided2.st:inferred_and_provided2
                inferred_but_ignored1.st:inferred_but_ignored1
                //:inferred_but_ignored2
                """
            ),
            "demo/BUILD": dedent(
                """\
                smalltalk_libraries(
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
        }
    )

    assert_dependencies_resolved(
        dependencies_rule_runner,
        Address("demo"),
        expected=[
            Address("demo", relative_file_path="f1.st"),
            Address("demo", relative_file_path="f2.st"),
        ],
    )

    assert_dependencies_resolved(
        dependencies_rule_runner,
        Address("demo", relative_file_path="f1.st", target_name="demo"),
        expected=[
            Address("", target_name="inferred1"),
            Address("", relative_file_path="inferred2.st", target_name="inferred2"),
            Address("", target_name="inferred_and_provided1"),
            Address("", target_name="inferred_and_provided2"),
        ],
    )

    assert_dependencies_resolved(
        dependencies_rule_runner,
        Address("demo", relative_file_path="f2.st", target_name="demo"),
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


def test_depends_on_generated_targets(dependencies_rule_runner: RuleRunner) -> None:
    """If the address is a target generator, then it depends on all of its generated targets."""
    dependencies_rule_runner.write_files(
        {
            "src/smalltalk/f1.st": "",
            "src/smalltalk/f2.st": "",
            "src/smalltalk/BUILD": "smalltalk_libraries(sources=['*.st'])",
            "src/smalltalk/util/BUILD": "smalltalk_libraries()",
        }
    )
    assert_dependencies_resolved(
        dependencies_rule_runner,
        Address("src/smalltalk"),
        expected=[
            Address("src/smalltalk", relative_file_path="f1.st"),
            Address("src/smalltalk", relative_file_path="f2.st"),
        ],
    )


def test_depends_on_atom_via_14419(dependencies_rule_runner: RuleRunner) -> None:
    """See #14419."""
    dependencies_rule_runner.write_files(
        {
            "src/smalltalk/f1.st": "",
            "src/smalltalk/f2.st": "",
            "src/smalltalk/BUILD": dedent(
                """\
                smalltalk_library(source='f1.st')
                smalltalk_library(
                    name='t2',
                    source='f2.st',
                    dependencies=['./f1.st'],
                )
                """
            ),
        }
    )
    # Due to the accommodation for #14419, the file address `./f1.st` resolves to the atom target
    # with the default name.
    assert_dependencies_resolved(
        dependencies_rule_runner,
        Address("src/smalltalk", target_name="t2"),
        expected=[
            Address("src/smalltalk"),
        ],
    )


def test_resolve_unparsed_address_inputs() -> None:
    rule_runner = RuleRunner(
        rules=[QueryRule(Addresses, [UnparsedAddressInputs])], target_types=[MockTarget]
    )
    rule_runner.write_files(
        {
            "project/BUILD": dedent(
                """\
                target(name="t1")
                target(name="t2")
                target(name="t3")
                """
            )
        }
    )
    addresses = rule_runner.request(
        Addresses,
        [
            UnparsedAddressInputs(
                ["project:t1", ":t2"], owning_address=Address("project", target_name="t3")
            )
        ],
    )
    assert set(addresses) == {
        Address("project", target_name="t1"),
        Address("project", target_name="t2"),
    }
