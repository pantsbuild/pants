# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from textwrap import dedent
from typing import Iterable, Type

import pytest

from pants.base.exceptions import ResolveError
from pants.base.specs_parser import SpecsParser
from pants.base.specs_v2 import (
    AddressLiteralSpec,
    AncestorGlobSpec,
    DirGlobSpec,
    FileGlobSpec,
    FileLiteralSpec,
    RecursiveGlobSpec,
    Spec,
    Specs,
    SpecsWithOnlyFileOwners,
    SpecsWithoutFileOwners,
)
from pants.build_graph.address import Address
from pants.engine.addresses import Addresses
from pants.engine.fs import SpecsSnapshot
from pants.engine.internals.parametrize import Parametrize
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.internals.specs_rules import (
    AmbiguousImplementationsException,
    NoApplicableTargetsException,
    TooManyTargetsException,
)
from pants.engine.rules import QueryRule, rule
from pants.engine.target import (
    Dependencies,
    FieldSet,
    FilteredTargets,
    GeneratedTargets,
    GenerateTargetsRequest,
    MultipleSourcesField,
    NoApplicableTargetsBehavior,
    OverridesField,
    SingleSourceField,
    StringField,
    Tags,
    Target,
    TargetFilesGenerator,
    TargetGenerator,
    TargetRootsToFieldSets,
    TargetRootsToFieldSetsRequest,
)
from pants.engine.unions import UnionMembership, UnionRule, union
from pants.testutil.rule_runner import RuleRunner, engine_error
from pants.util.frozendict import FrozenDict


class ResolveField(StringField):
    alias = "resolve"


class MockTarget(Target):
    alias = "target"
    core_fields = (Dependencies, MultipleSourcesField, Tags, ResolveField)


class MockGeneratedFileTarget(Target):
    alias = "file_generated"
    core_fields = (Dependencies, SingleSourceField, Tags, ResolveField)


class MockFileTargetGenerator(TargetFilesGenerator):
    alias = "file_generator"
    generated_target_cls = MockGeneratedFileTarget
    core_fields = (MultipleSourcesField, Tags, OverridesField)
    copied_fields = (Tags,)
    moved_fields = (Dependencies, ResolveField)


class MockGeneratedNonfileTarget(Target):
    alias = "nonfile_generated"
    core_fields = (Dependencies, Tags, ResolveField)


class MockNonfileTargetGenerator(TargetGenerator):
    alias = "nonfile_generator"
    core_fields = (Tags,)
    copied_fields = (Tags,)
    moved_fields = (Dependencies, ResolveField)


class MockGenerateTargetsRequest(GenerateTargetsRequest):
    generate_from = MockNonfileTargetGenerator


@rule
async def generate_mock_generated_target(request: MockGenerateTargetsRequest) -> GeneratedTargets:
    return GeneratedTargets(
        request.generator,
        [
            MockGeneratedNonfileTarget(
                request.template, request.generator.address.create_generated("gen")
            )
        ],
    )


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            generate_mock_generated_target,
            UnionRule(GenerateTargetsRequest, MockGenerateTargetsRequest),
            QueryRule(Addresses, [Specs]),
            QueryRule(Addresses, [SpecsWithoutFileOwners]),
            QueryRule(Addresses, [SpecsWithOnlyFileOwners]),
            QueryRule(FilteredTargets, [Specs]),
            QueryRule(SpecsSnapshot, [Specs]),
        ],
        objects={"parametrize": Parametrize},
        target_types=[MockTarget, MockFileTargetGenerator, MockNonfileTargetGenerator],
    )


# -----------------------------------------------------------------------------------------------
# SpecsWithoutFileOwners -> Targets
# -----------------------------------------------------------------------------------------------


def resolve_specs_without_file_owners(
    rule_runner: RuleRunner,
    specs: Iterable[Spec],
) -> list[Address]:
    specs_obj = Specs.create(
        specs, filter_by_global_options=True, convert_dir_literal_to_address_literal=True
    )
    result = rule_runner.request(Addresses, [SpecsWithoutFileOwners.from_specs(specs_obj)])
    return sorted(result)


def test_specs_without_file_owners_literals_vs_globs(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "demo/BUILD": dedent(
                """\
                file_generator(sources=['**/*.txt'])
                nonfile_generator(name="nonfile")
                """
            ),
            "demo/f1.txt": "",
            "demo/f2.txt": "",
            "demo/f[3].txt": "",
            "demo/subdir/f.txt": "",
            "demo/subdir/f.another_ext": "",
            "demo/subdir/BUILD": "target(name='another_ext', sources=['f.another_ext'])",
            "another_dir/BUILD": "target(sources=[])",
        }
    )

    def assert_resolved(spec: Spec, expected: set[Address]) -> None:
        result = resolve_specs_without_file_owners(rule_runner, [spec])
        assert set(result) == expected

    # Literals should be "one-in, one-out".
    assert_resolved(AddressLiteralSpec("demo"), {Address("demo")})
    assert_resolved(
        AddressLiteralSpec("demo/f1.txt"), {Address("demo", relative_file_path="f1.txt")}
    )
    assert_resolved(
        AddressLiteralSpec("demo", target_component="nonfile", generated_component="gen"),
        {Address("demo", target_name="nonfile", generated_name="gen")},
    )
    assert_resolved(
        AddressLiteralSpec("demo/subdir", target_component="another_ext"),
        {Address("demo/subdir", target_name="another_ext")},
    )

    assert_resolved(
        # Match all targets that reside in `demo/`, either because explicitly declared there or
        # generated into that dir. Note that this does not include `demo/subdir/f2.ext:../demo`,
        # even though its target generator matches.
        DirGlobSpec("demo"),
        {
            Address("demo"),
            Address("demo", target_name="nonfile"),
            Address("demo", relative_file_path="f1.txt"),
            Address("demo", relative_file_path="f2.txt"),
            Address("demo", relative_file_path="f[[]3].txt"),
            Address("demo", target_name="nonfile", generated_name="gen"),
        },
    )
    assert_resolved(
        # Should include all generated targets that reside in `demo/subdir`, even though their
        # target generator is in an ancestor.
        DirGlobSpec("demo/subdir"),
        {
            Address("demo", relative_file_path="subdir/f.txt"),
            Address("demo/subdir", target_name="another_ext"),
        },
    )

    all_tgts_in_demo = {
        Address("demo"),
        Address("demo", target_name="nonfile"),
        Address("demo", target_name="nonfile", generated_name="gen"),
        Address("demo", relative_file_path="f1.txt"),
        Address("demo", relative_file_path="f2.txt"),
        Address("demo", relative_file_path="f[[]3].txt"),
        Address("demo", relative_file_path="subdir/f.txt"),
        Address("demo/subdir", target_name="another_ext"),
    }
    assert_resolved(RecursiveGlobSpec("demo"), all_tgts_in_demo)
    assert_resolved(AncestorGlobSpec("demo/subdir"), all_tgts_in_demo)
    assert_resolved(
        AncestorGlobSpec("demo"),
        {
            Address("demo"),
            Address("demo", target_name="nonfile"),
            Address("demo", target_name="nonfile", generated_name="gen"),
            Address("demo", relative_file_path="f1.txt"),
            Address("demo", relative_file_path="f2.txt"),
            Address("demo", relative_file_path="f[[]3].txt"),
        },
    )


def test_specs_without_file_owners_deduplication(rule_runner: RuleRunner) -> None:
    """When multiple specs cover the same address, we should deduplicate to one single Address."""
    rule_runner.write_files(
        {
            "demo/f.txt": "",
            "demo/BUILD": dedent(
                """\
                file_generator(sources=['f.txt'])
                nonfile_generator(name="nonfile")
                """
            ),
        }
    )
    specs = [
        AddressLiteralSpec("demo"),
        DirGlobSpec("demo"),
        RecursiveGlobSpec("demo"),
        AncestorGlobSpec("demo"),
        AddressLiteralSpec("demo", target_component="nonfile", generated_component="gen"),
        AddressLiteralSpec("demo/f.txt"),
    ]
    assert resolve_specs_without_file_owners(rule_runner, specs) == [
        Address("demo"),
        Address("demo", target_name="nonfile"),
        Address("demo", target_name="nonfile", generated_name="gen"),
        Address("demo", relative_file_path="f.txt"),
    ]


def test_specs_without_file_owners_filter_by_tag(rule_runner: RuleRunner) -> None:
    rule_runner.set_options(["--tag=+integration"])
    all_integration_tgts = [
        Address("demo", target_name="b_f"),
        Address("demo", target_name="b_nf"),
        Address("demo", target_name="b_nf", generated_name="gen"),
        Address("demo", target_name="b_f", relative_file_path="f.txt"),
    ]
    rule_runner.write_files(
        {
            "demo/f.txt": "",
            "demo/BUILD": dedent(
                """\
                file_generator(name="a_f", sources=["f.txt"])
                file_generator(name="b_f", sources=["f.txt"], tags=["integration"])
                file_generator(name="c_f", sources=["f.txt"], tags=["ignore"])

                nonfile_generator(name="a_nf")
                nonfile_generator(name="b_nf", tags=["integration"])
                nonfile_generator(name="c_nf", tags=["ignore"])
                """
            ),
        }
    )
    assert (
        resolve_specs_without_file_owners(rule_runner, [DirGlobSpec("demo")])
        == all_integration_tgts
    )

    # The same filtering should work when given literal addresses, including generated targets and
    # file addresses.
    literals_result = resolve_specs_without_file_owners(
        rule_runner,
        [
            AddressLiteralSpec("demo", "a_f"),
            AddressLiteralSpec("demo", "b_f"),
            AddressLiteralSpec("demo", "c_f"),
            AddressLiteralSpec("demo", "a_nf"),
            AddressLiteralSpec("demo", "b_nf"),
            AddressLiteralSpec("demo", "c_nf"),
            AddressLiteralSpec("demo/f.txt", "a_f"),
            AddressLiteralSpec("demo/f.txt", "b_f"),
            AddressLiteralSpec("demo", "a_nf", "gen"),
            AddressLiteralSpec("demo", "b_nf", "gen"),
            AddressLiteralSpec("demo", "c_nf", "gen"),
        ],
    )
    assert literals_result == all_integration_tgts


def test_specs_without_file_owners_filter_by_exclude_pattern(rule_runner: RuleRunner) -> None:
    rule_runner.set_options(["--exclude-target-regexp=exclude_me.*"])
    rule_runner.write_files(
        {
            "demo/f.txt": "",
            "demo/BUILD": dedent(
                """\
                file_generator(name="exclude_me_f", sources=["f.txt"])
                file_generator(name="not_me_f", sources=["f.txt"])

                nonfile_generator(name="exclude_me_nf")
                nonfile_generator(name="not_me_nf")
                """
            ),
        }
    )
    not_me_tgts = [
        Address("demo", target_name="not_me_f"),
        Address("demo", target_name="not_me_nf"),
        Address("demo", target_name="not_me_nf", generated_name="gen"),
        Address("demo", target_name="not_me_f", relative_file_path="f.txt"),
    ]

    assert resolve_specs_without_file_owners(rule_runner, [DirGlobSpec("demo")]) == not_me_tgts

    # The same filtering should work when given literal addresses, including generated targets and
    # file addresses.
    literals_result = resolve_specs_without_file_owners(
        rule_runner,
        [
            AddressLiteralSpec("demo", "exclude_me_f"),
            AddressLiteralSpec("demo", "exclude_me_nf"),
            AddressLiteralSpec("demo", "not_me_f"),
            AddressLiteralSpec("demo", "not_me_nf"),
            AddressLiteralSpec("demo", "exclude_me_nf", "gen"),
            AddressLiteralSpec("demo", "not_me_nf", "gen"),
            AddressLiteralSpec("demo/f.txt", "exclude_me_f"),
            AddressLiteralSpec("demo/f.txt", "not_me_f"),
        ],
    )
    assert literals_result == not_me_tgts


def test_specs_without_file_owners_do_not_exist(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {"real/f.txt": "", "real/BUILD": "target(sources=['f.txt'])", "empty/BUILD": "# empty"}
    )

    def assert_resolve_error(specs: Iterable[Spec], *, expected: str) -> None:
        with engine_error(contains=expected):
            resolve_specs_without_file_owners(rule_runner, specs)

    # Literal addresses require for the relevant BUILD file to exist and for the target to be
    # resolved.
    assert_resolve_error(
        [AddressLiteralSpec("fake", "tgt")], expected="'fake' does not exist on disk"
    )
    assert_resolve_error(
        [AddressLiteralSpec("fake/f.txt", "tgt")],
        expected="'fake/f.txt' does not exist on disk",
    )
    did_you_mean = ResolveError.did_you_mean(
        bad_name="fake_tgt", known_names=["real"], namespace="real"
    )
    assert_resolve_error([AddressLiteralSpec("real", "fake_tgt")], expected=str(did_you_mean))
    assert_resolve_error([AddressLiteralSpec("real/f.txt", "fake_tgt")], expected=str(did_you_mean))

    assert_resolve_error(
        [DirGlobSpec("fake")],
        expected="No targets found for the glob `fake:`",
    )
    assert_resolve_error([DirGlobSpec("empty")], expected="No targets found for the glob `empty:`")
    assert not resolve_specs_without_file_owners(
        rule_runner, [DirGlobSpec("fake", error_if_no_target_matches=False)]
    )
    assert not resolve_specs_without_file_owners(
        rule_runner, [DirGlobSpec("empty", error_if_no_target_matches=False)]
    )

    assert_resolve_error(
        [RecursiveGlobSpec("fake"), RecursiveGlobSpec("empty")],
        expected="No targets found for these globs: ['empty::', 'fake::']",
    )
    assert not resolve_specs_without_file_owners(
        rule_runner,
        [
            RecursiveGlobSpec("fake", error_if_no_target_matches=False),
            RecursiveGlobSpec("empty", error_if_no_target_matches=False),
        ],
    )

    assert not resolve_specs_without_file_owners(
        rule_runner, [AncestorGlobSpec("fake"), AncestorGlobSpec("empty")]
    )
    assert_resolve_error(
        [
            AncestorGlobSpec("fake", error_if_no_target_matches=True),
            AncestorGlobSpec("empty", error_if_no_target_matches=True),
        ],
        expected="No targets found for these globs: ['empty^', 'fake^']",
    )


def test_specs_without_file_owners_generated_target_does_not_belong_to_generator(
    rule_runner: RuleRunner,
) -> None:
    rule_runner.write_files(
        {
            "demo/f.txt": "",
            "demo/other.txt": "",
            "demo/BUILD": dedent(
                """\
                file_generator(name='owner', sources=['f.txt'])
                file_generator(name='not_owner', sources=['other.txt'])
                """
            ),
        }
    )

    with pytest.raises(ExecutionError) as exc:
        resolve_specs_without_file_owners(
            rule_runner, [AddressLiteralSpec("demo/f.txt", "not_owner")]
        )
    assert (
        "The address `demo/f.txt:not_owner` was not generated by the target `demo:not_owner`"
    ) in str(exc.value)


def test_specs_without_file_owners_parametrize(
    rule_runner: RuleRunner,
) -> None:
    rule_runner.write_files(
        {
            "demo/f.txt": "",
            "demo/BUILD": dedent(
                """\
                file_generator(sources=['f.txt'], resolve=parametrize("a", "b"))
                nonfile_generator(name="nonfile", resolve=parametrize("a", "b"))
                target(sources=['f.txt'], name="not_gen", resolve=parametrize("a", "b"))
                """
            ),
        }
    )

    def assert_resolved(spec: Spec, expected: set[Address]) -> None:
        assert set(resolve_specs_without_file_owners(rule_runner, [spec])) == expected

    not_gen_resolve_a = Address("demo", target_name="not_gen", parameters={"resolve": "a"})
    not_gen_resolve_b = Address("demo", target_name="not_gen", parameters={"resolve": "b"})
    file_generator_resolve_a = {
        Address("demo", relative_file_path="f.txt", parameters={"resolve": "a"}),
        Address("demo", parameters={"resolve": "a"}),
    }
    file_generator_resolve_b = {
        Address("demo", relative_file_path="f.txt", parameters={"resolve": "b"}),
        Address("demo", parameters={"resolve": "b"}),
    }
    nonfile_generator_resolve_a = {
        Address("demo", target_name="nonfile", generated_name="gen", parameters={"resolve": "a"}),
        Address("demo", target_name="nonfile", parameters={"resolve": "a"}),
    }
    nonfile_generator_resolve_b = {
        Address("demo", target_name="nonfile", generated_name="gen", parameters={"resolve": "b"}),
        Address("demo", target_name="nonfile", parameters={"resolve": "b"}),
    }

    assert_resolved(
        RecursiveGlobSpec(""),
        {
            *file_generator_resolve_a,
            *file_generator_resolve_b,
            *nonfile_generator_resolve_a,
            *nonfile_generator_resolve_b,
            not_gen_resolve_a,
            not_gen_resolve_b,
        },
    )

    # A literal address for a parameterized target works as expected.
    assert_resolved(
        AddressLiteralSpec(
            "demo", target_component="not_gen", parameters=FrozenDict({"resolve": "a"})
        ),
        {not_gen_resolve_a},
    )
    assert_resolved(
        AddressLiteralSpec("demo/f.txt", parameters=FrozenDict({"resolve": "a"})),
        {Address("demo", relative_file_path="f.txt", parameters={"resolve": "a"})},
    )
    assert_resolved(
        AddressLiteralSpec(
            "demo", "nonfile", generated_component="gen", parameters=FrozenDict({"resolve": "a"})
        ),
        {Address("demo", target_name="nonfile", generated_name="gen", parameters={"resolve": "a"})},
    )
    assert_resolved(
        # A direct reference to the parametrized target generator.
        AddressLiteralSpec("demo", parameters=FrozenDict({"resolve": "a"})),
        {Address("demo", parameters={"resolve": "a"})},
    )

    # A literal address for a parametrized template should be expanded with the matching targets.
    assert_resolved(
        AddressLiteralSpec("demo", target_component="not_gen"),
        {not_gen_resolve_a, not_gen_resolve_b},
    )

    # The above affordance plays nicely with target generation.
    assert_resolved(
        # Note that this returns references to the two target generators. Certain goals like
        # `test` may then later replace those with their generated targets.
        AddressLiteralSpec("demo"),
        {Address("demo", parameters={"resolve": r}) for r in ("a", "b")},
    )
    assert_resolved(
        AddressLiteralSpec("demo", "nonfile", "gen"),
        {
            Address("demo", target_name="nonfile", generated_name="gen", parameters={"resolve": r})
            for r in ("a", "b")
        },
    )
    assert_resolved(
        AddressLiteralSpec("demo/f.txt"),
        {
            Address("demo", relative_file_path="f.txt", parameters={"resolve": r})
            for r in ("a", "b")
        },
    )

    # Error on invalid targets.
    def assert_errors(spec: AddressLiteralSpec) -> None:
        with engine_error(ValueError):
            resolve_specs_without_file_owners(rule_runner, [spec])

    assert_errors(AddressLiteralSpec("demo", parameters=FrozenDict({"fake": "v"})))
    assert_errors(AddressLiteralSpec("demo", parameters=FrozenDict({"resolve": "fake"})))


# -----------------------------------------------------------------------------------------------
# SpecsWithOnlyFileOwners -> Targets
# -----------------------------------------------------------------------------------------------


def resolve_specs_with_only_file_owners(
    rule_runner: RuleRunner,
    specs: Iterable[Spec],
) -> list[Address]:
    specs_obj = Specs.create(
        specs, filter_by_global_options=True, convert_dir_literal_to_address_literal=True
    )
    result = rule_runner.request(Addresses, [SpecsWithOnlyFileOwners.from_specs(specs_obj)])
    return sorted(result)


def test_specs_with_only_file_owners_literal_file(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "demo/f1.txt": "",
            "demo/f2.txt": "",
            "demo/BUILD": dedent(
                """\
                file_generator(name='generator', sources=['*.txt'])
                nonfile_generator(name='nonfile')
                target(name='not-generator', sources=['*.txt'])
                """
            ),
        }
    )
    assert resolve_specs_with_only_file_owners(rule_runner, [FileLiteralSpec("demo/f1.txt")]) == [
        Address("demo", target_name="not-generator"),
        Address("demo", target_name="generator", relative_file_path="f1.txt"),
    ]


def test_specs_with_only_file_owners_glob(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "demo/f1.txt": "",
            "demo/f2.txt": "",
            "demo/BUILD": dedent(
                """\
                file_generator(name='generator', sources=['*.txt'])
                nonfile_generator(name='nonfile')
                target(name='not-generator', sources=['*.txt'])
                target(name='skip-me', sources=['*.txt'])
                target(name='bad-tag', sources=['*.txt'], tags=['skip'])
                """
            ),
        }
    )
    rule_runner.set_options(["--tag=-skip", "--exclude-target-regexp=skip-me"])
    all_unskipped_addresses = [
        Address("demo", target_name="not-generator"),
        Address("demo", target_name="generator", relative_file_path="f1.txt"),
        Address("demo", target_name="generator", relative_file_path="f2.txt"),
    ]

    assert (
        resolve_specs_with_only_file_owners(rule_runner, [FileGlobSpec("demo/*.txt")])
        == all_unskipped_addresses
    )
    # We should deduplicate between glob and literal specs.
    assert (
        resolve_specs_with_only_file_owners(
            rule_runner,
            [FileGlobSpec("demo/*.txt"), FileLiteralSpec("demo/f1.txt")],
        )
        == all_unskipped_addresses
    )


def test_specs_with_only_file_owners_nonexistent_file(rule_runner: RuleRunner) -> None:
    spec = FileLiteralSpec("demo/fake.txt")
    with engine_error(contains='Unmatched glob from file/directory arguments: "demo/fake.txt"'):
        resolve_specs_with_only_file_owners(rule_runner, [spec])

    rule_runner.set_options(["--owners-not-found-behavior=ignore"])
    assert not resolve_specs_with_only_file_owners(rule_runner, [spec])


def test_specs_with_only_file_owners_no_owner(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"no_owners/f.txt": ""})
    # Error for literal specs.
    with pytest.raises(ExecutionError) as exc:
        resolve_specs_with_only_file_owners(rule_runner, [FileLiteralSpec("no_owners/f.txt")])
    assert "No owning targets could be found for the file `no_owners/f.txt`" in str(exc.value)

    # Do not error for glob specs.
    assert not resolve_specs_with_only_file_owners(rule_runner, [FileGlobSpec("no_owners/*.txt")])


# -----------------------------------------------------------------------------------------------
# Specs -> Targets
# -----------------------------------------------------------------------------------------------


def test_resolve_addresses_from_specs(rule_runner: RuleRunner) -> None:
    """This tests that we correctly handle resolving from both address and filesystem specs."""
    rule_runner.write_files(
        {
            "fs_spec/f.txt": "",
            "fs_spec/BUILD": "file_generator(sources=['f.txt'])",
            "address_spec/f.txt": "",
            "address_spec/BUILD": dedent(
                """\
                file_generator(sources=['f.txt'])
                nonfile_generator(name='nonfile')
                """
            ),
            "multiple_files/f1.txt": "",
            "multiple_files/f2.txt": "",
            "multiple_files/BUILD": "file_generator(sources=['*.txt'])",
        }
    )

    no_interaction_specs = [
        "fs_spec/f.txt",
        "address_spec:address_spec",
        "address_spec:nonfile#gen",
    ]
    multiple_files_specs = ["multiple_files/f2.txt", "multiple_files:multiple_files"]
    specs = SpecsParser(rule_runner.build_root).parse_specs(
        [*no_interaction_specs, *multiple_files_specs]
    )

    result = rule_runner.request(Addresses, [specs])
    assert set(result) == {
        Address("fs_spec", relative_file_path="f.txt"),
        Address("address_spec"),
        Address("address_spec", target_name="nonfile", generated_name="gen"),
        Address("multiple_files"),
        Address("multiple_files", relative_file_path="f2.txt"),
    }


def test_filtered_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "addr_specs/f1.txt": "",
            "addr_specs/f2.txt": "",
            "addr_specs/BUILD": dedent(
                """\
                file_generator(
                    sources=["*.txt"],
                    tags=["a"],
                    overrides={"f2.txt": {"tags": ["b"]}},
                )
                nonfile_generator(name="nonfile", tags=["b"])

                target(name='t', tags=["a"])
                """
            ),
            "fs_specs/f1.txt": "",
            "fs_specs/f2.txt": "",
            "fs_specs/BUILD": dedent(
                """\
                file_generator(
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
        recursive_globs=(RecursiveGlobSpec("addr_specs"),),
        file_globs=(FileGlobSpec("fs_specs/*.txt"),),
        filter_by_global_options=True,
    )

    def check(tags_option: str | None, expected: set[Address]) -> None:
        if tags_option:
            rule_runner.set_options([f"--tag={tags_option}"])
        result = rule_runner.request(FilteredTargets, [specs])
        assert {t.address for t in result} == expected

    addr_f1 = Address("addr_specs", relative_file_path="f1.txt")
    addr_f2 = Address("addr_specs", relative_file_path="f2.txt")
    addr_gen = Address("addr_specs", target_name="nonfile", generated_name="gen")
    addr_direct = Address("addr_specs", target_name="t")

    fs_f1 = Address("fs_specs", relative_file_path="f1.txt")
    fs_f2 = Address("fs_specs", relative_file_path="f2.txt")
    fs_direct = Address("fs_specs", target_name="t")

    all_a_tags = {addr_f1, addr_direct, fs_f1, fs_direct}
    all_b_tags = {addr_gen, addr_f2, fs_f2}

    check(None, {*all_a_tags, *all_b_tags})
    check("a", all_a_tags)
    check("b", all_b_tags)
    check("-a", all_b_tags)
    check("-b", all_a_tags)


# -----------------------------------------------------------------------------------------------
# SpecsSnapshot
# -----------------------------------------------------------------------------------------------


def test_resolve_specs_snapshot(rule_runner: RuleRunner) -> None:
    """This tests that convert filesystem specs and/or address specs into a single snapshot.

    Some important edge cases:
    - When a filesystem spec refers to a file without any owning target, it should be included
      in the snapshot.
    - If a file is covered both by an address spec and by a filesystem spec, we should merge it
      so that the file only shows up once.
    """
    rule_runner.write_files(
        {"demo/f1.txt": "", "demo/f2.txt": "", "demo/BUILD": "target(sources=['*.txt'])"}
    )
    specs = SpecsParser(rule_runner.build_root).parse_specs(
        ["demo:demo", "demo/f1.txt", "demo/BUILD"]
    )
    result = rule_runner.request(SpecsSnapshot, [specs])
    assert result.snapshot.files == ("demo/BUILD", "demo/f1.txt", "demo/f2.txt")


# -----------------------------------------------------------------------------------------------
# Test FieldSets. Also see `engine/target_test.py`.
# -----------------------------------------------------------------------------------------------


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
        specs: Iterable[Spec],
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
            [request, Specs.create(specs, convert_dir_literal_to_address_literal=True)],
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
        Specs(),
        UnionMembership({}),
        applicable_target_types=[Tgt1],
        goal_description="the `foo` goal",
    )
    remedy = (
        "Please specify relevant file and/or target arguments. Run `./pants filter "
        "--target-type=tgt1 ::` to find all applicable targets in your project."
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
        Specs(file_literals=(FileLiteralSpec("foo.ext"),)),
        UnionMembership({}),
        applicable_target_types=[Tgt1, Tgt2],
        goal_description="the `foo` goal",
    )
    remedy = (
        "Please specify relevant file and/or target arguments. Run `./pants filter "
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

            However, you only specified file arguments with these target types:

              * tgt3

            {remedy}"""
        )
        in str(exc)
    )

    # Test handling of `Specs`.
    exc = NoApplicableTargetsException(
        [invalid_tgt],
        Specs(address_literals=(AddressLiteralSpec("foo", "bar"),)),
        UnionMembership({}),
        applicable_target_types=[Tgt1],
        goal_description="the `foo` goal",
    )
    assert "However, you only specified target arguments with these target types:" in str(exc)
    exc = NoApplicableTargetsException(
        [invalid_tgt],
        Specs(
            address_literals=(AddressLiteralSpec("foo", "bar"),),
            file_literals=(FileLiteralSpec("foo.ext"),),
        ),
        UnionMembership({}),
        applicable_target_types=[Tgt1],
        goal_description="the `foo` goal",
    )
    assert "However, you only specified target and file arguments with these target types:" in str(
        exc
    )
