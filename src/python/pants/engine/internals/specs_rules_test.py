# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from textwrap import dedent
from typing import Iterable, Type

import pytest

from pants.base.glob_match_error_behavior import GlobMatchErrorBehavior
from pants.base.specs import (
    AddressLiteralSpec,
    AncestorGlobSpec,
    DirGlobSpec,
    DirLiteralSpec,
    FileGlobSpec,
    FileLiteralSpec,
    RawSpecs,
    RawSpecsWithOnlyFileOwners,
    RawSpecsWithoutFileOwners,
    RecursiveGlobSpec,
    Spec,
    Specs,
)
from pants.base.specs_parser import SpecsParser
from pants.build_graph.address import Address, ResolveError
from pants.engine.addresses import Addresses
from pants.engine.fs import SpecsPaths
from pants.engine.internals.parametrize import Parametrize
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.internals.specs_rules import NoApplicableTargetsException
from pants.engine.internals.testutil import resolve_raw_specs_without_file_owners
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
from pants.util.strutil import softwrap


class ResolveField(StringField):
    alias = "resolve"


class MockDepsField(Dependencies):
    pass


class MockSingleSourcesField(SingleSourceField):
    pass


class MockMultipleSourcesField(MultipleSourcesField):
    pass


class MockTarget(Target):
    alias = "target"
    core_fields = (MockDepsField, MockMultipleSourcesField, Tags, ResolveField)


class MockGeneratedFileTarget(Target):
    alias = "file_generated"
    core_fields = (MockDepsField, MockSingleSourcesField, Tags, ResolveField)


class MockFileTargetGenerator(TargetFilesGenerator):
    alias = "file_generator"
    generated_target_cls = MockGeneratedFileTarget
    core_fields = (MockMultipleSourcesField, Tags, OverridesField)
    copied_fields = (Tags,)
    moved_fields = (MockDepsField, ResolveField)


class MockGeneratedNonfileTarget(Target):
    alias = "nonfile_generated"
    core_fields = (MockDepsField, Tags, ResolveField)


class MockNonfileTargetGenerator(TargetGenerator):
    alias = "nonfile_generator"
    core_fields = (Tags,)
    copied_fields = (Tags,)
    moved_fields = (MockDepsField, ResolveField)


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
            QueryRule(Addresses, [RawSpecs]),
            QueryRule(Addresses, [RawSpecsWithoutFileOwners]),
            QueryRule(Addresses, [RawSpecsWithOnlyFileOwners]),
            QueryRule(FilteredTargets, [Addresses]),
            QueryRule(Addresses, [Specs]),
            QueryRule(SpecsPaths, [Specs]),
        ],
        objects={"parametrize": Parametrize},
        target_types=[MockTarget, MockFileTargetGenerator, MockNonfileTargetGenerator],
    )


# -----------------------------------------------------------------------------------------------
# RawSpecsWithoutFileOwners -> Targets
# -----------------------------------------------------------------------------------------------


def test_raw_specs_without_file_owners_literals_vs_globs(rule_runner: RuleRunner) -> None:
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
        result = resolve_raw_specs_without_file_owners(rule_runner, [spec])
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

    demo_dir_generated_targets = {
        Address("demo", relative_file_path="f1.txt"),
        Address("demo", relative_file_path="f2.txt"),
        Address("demo", relative_file_path="f[[]3].txt"),
        Address("demo", target_name="nonfile", generated_name="gen"),
    }
    demo_subdir_generated_targets = {
        Address("demo", relative_file_path="subdir/f.txt"),
        Address("demo/subdir", target_name="another_ext"),
    }

    # `DirGlobSpec` matches all targets that "reside" in the directory, either because explicitly
    # declared there or generated into that dir.
    assert_resolved(
        # Note that this does not include `demo/subdir/f2.ext:../demo`, even though its target
        # generator matches.
        DirGlobSpec("demo"),
        {Address("demo"), Address("demo", target_name="nonfile"), *demo_dir_generated_targets},
    )
    assert_resolved(
        # Should include all generated targets that reside in `demo/subdir`, even though their
        # target generator is in an ancestor.
        DirGlobSpec("demo/subdir"),
        demo_subdir_generated_targets,
    )

    # `DirLiteralSpec` matches all targets that "reside" in the directory, but it filters out
    # target generators.
    assert_resolved(DirLiteralSpec("demo"), demo_dir_generated_targets)
    assert_resolved(DirLiteralSpec("demo/subdir"), demo_subdir_generated_targets)

    all_tgts_in_demo = {
        Address("demo"),
        Address("demo", target_name="nonfile"),
        *demo_dir_generated_targets,
        *demo_subdir_generated_targets,
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


def test_raw_specs_without_file_owners_deduplication(rule_runner: RuleRunner) -> None:
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
        DirLiteralSpec("demo"),
        DirGlobSpec("demo"),
        RecursiveGlobSpec("demo"),
        AncestorGlobSpec("demo"),
        AddressLiteralSpec("demo", target_component="nonfile", generated_component="gen"),
        AddressLiteralSpec("demo/f.txt"),
    ]
    assert resolve_raw_specs_without_file_owners(rule_runner, specs) == [
        Address("demo"),
        Address("demo", target_name="nonfile"),
        Address("demo", target_name="nonfile", generated_name="gen"),
        Address("demo", relative_file_path="f.txt"),
    ]


def test_raw_specs_without_file_owners_filter_by_tag(rule_runner: RuleRunner) -> None:
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
        resolve_raw_specs_without_file_owners(rule_runner, [DirGlobSpec("demo")])
        == all_integration_tgts
    )

    # The same filtering should work when given literal addresses, including generated targets and
    # file addresses.
    literals_result = resolve_raw_specs_without_file_owners(
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


def test_raw_specs_without_file_owners_do_not_exist(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {"real/f.txt": "", "real/BUILD": "target(sources=['f.txt'])", "empty/BUILD": "# empty"}
    )

    def assert_resolve_error(spec: Spec, *, expected: str) -> None:
        with engine_error(contains=expected):
            resolve_raw_specs_without_file_owners(rule_runner, [spec])

    def assert_does_not_error(spec: Spec, *, ignore_nonexistent: bool = False) -> None:
        assert not resolve_raw_specs_without_file_owners(
            rule_runner, [spec], ignore_nonexistent=ignore_nonexistent
        )

    # Literal addresses require for the target to be resolved.
    assert_resolve_error(
        AddressLiteralSpec("fake", "tgt"), expected="'fake' does not exist on disk"
    )
    assert_resolve_error(
        AddressLiteralSpec("fake/f.txt", "tgt"),
        expected="'fake/f.txt' does not exist on disk",
    )
    did_you_mean = ResolveError.did_you_mean(
        Address("real", target_name="fake_tgt"),
        description_of_origin="tests",
        known_names=["real"],
        namespace="real",
    )
    assert_resolve_error(AddressLiteralSpec("real", "fake_tgt"), expected=str(did_you_mean))
    assert_resolve_error(AddressLiteralSpec("real/f.txt", "fake_tgt"), expected=str(did_you_mean))

    assert_resolve_error(DirGlobSpec("fake"), expected='Unmatched glob from tests: "fake/*"')
    assert_does_not_error(DirGlobSpec("empty"))
    assert_does_not_error(DirGlobSpec("fake"), ignore_nonexistent=True)

    assert_resolve_error(DirLiteralSpec("fake"), expected='Unmatched glob from tests: "fake/*"')
    assert_does_not_error(DirLiteralSpec("empty"))
    assert_does_not_error(DirLiteralSpec("fake"), ignore_nonexistent=True)

    assert_resolve_error(RecursiveGlobSpec("fake"), expected='Unmatched glob from tests: "fake/**"')
    assert_does_not_error(RecursiveGlobSpec("empty"))
    assert_does_not_error(RecursiveGlobSpec("fake"), ignore_nonexistent=True)

    assert_resolve_error(AncestorGlobSpec("fake"), expected='Unmatched glob from tests: "fake/*"')
    assert_does_not_error(AncestorGlobSpec("empty"))
    assert_does_not_error(AncestorGlobSpec("fake"), ignore_nonexistent=True)


def test_raw_specs_without_file_owners_generated_target_does_not_belong_to_generator(
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
        resolve_raw_specs_without_file_owners(
            rule_runner, [AddressLiteralSpec("demo/f.txt", "not_owner")]
        )
    assert (
        softwrap(
            """
            The address `demo/f.txt:not_owner` from tests was not generated by the target
            `demo:not_owner`
            """
        )
        in str(exc.value)
    )


def test_raw_specs_without_file_owners_parametrize(
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
        assert set(resolve_raw_specs_without_file_owners(rule_runner, [spec])) == expected

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
        with engine_error(ResolveError):
            resolve_raw_specs_without_file_owners(rule_runner, [spec])

    assert_errors(AddressLiteralSpec("demo", parameters=FrozenDict({"fake": "v"})))
    assert_errors(AddressLiteralSpec("demo", parameters=FrozenDict({"resolve": "fake"})))


# -----------------------------------------------------------------------------------------------
# RawSpecsWithOnlyFileOwners -> Targets
# -----------------------------------------------------------------------------------------------


def resolve_raw_specs_with_only_file_owners(
    rule_runner: RuleRunner, specs: Iterable[Spec], ignore_nonexistent: bool = False
) -> list[Address]:
    specs_obj = RawSpecs.create(
        specs,
        filter_by_global_options=True,
        unmatched_glob_behavior=(
            GlobMatchErrorBehavior.ignore if ignore_nonexistent else GlobMatchErrorBehavior.error
        ),
        description_of_origin="tests",
    )
    result = rule_runner.request(Addresses, [RawSpecsWithOnlyFileOwners.from_raw_specs(specs_obj)])
    return sorted(result)


def test_raw_specs_with_only_file_owners_literal_file(rule_runner: RuleRunner) -> None:
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
    assert resolve_raw_specs_with_only_file_owners(
        rule_runner, [FileLiteralSpec("demo/f1.txt")]
    ) == [
        Address("demo", target_name="not-generator"),
        Address("demo", target_name="generator", relative_file_path="f1.txt"),
    ]


def test_raw_specs_with_only_file_owners_glob(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "demo/f1.txt": "",
            "demo/f2.txt": "",
            "demo/BUILD": dedent(
                """\
                file_generator(name='generator', sources=['*.txt'])
                nonfile_generator(name='nonfile')
                target(name='not-generator', sources=['*.txt'])
                target(name='bad-tag', sources=['*.txt'], tags=['skip'])
                """
            ),
        }
    )
    rule_runner.set_options(["--tag=-skip"])
    all_unskipped_addresses = [
        Address("demo", target_name="not-generator"),
        Address("demo", target_name="generator", relative_file_path="f1.txt"),
        Address("demo", target_name="generator", relative_file_path="f2.txt"),
    ]

    assert (
        resolve_raw_specs_with_only_file_owners(rule_runner, [FileGlobSpec("demo/*.txt")])
        == all_unskipped_addresses
    )
    # We should deduplicate between glob and literal specs.
    assert (
        resolve_raw_specs_with_only_file_owners(
            rule_runner,
            [FileGlobSpec("demo/*.txt"), FileLiteralSpec("demo/f1.txt")],
        )
        == all_unskipped_addresses
    )


def test_raw_specs_with_only_file_owners_nonexistent_file(rule_runner: RuleRunner) -> None:
    spec = FileLiteralSpec("demo/fake.txt")
    with engine_error(contains='Unmatched glob from tests: "demo/fake.txt"'):
        resolve_raw_specs_with_only_file_owners(rule_runner, [spec])

    assert not resolve_raw_specs_with_only_file_owners(rule_runner, [spec], ignore_nonexistent=True)


# -----------------------------------------------------------------------------------------------
# RawSpecs & Specs -> Targets
# -----------------------------------------------------------------------------------------------


def test_resolve_addresses_from_raw_specs(rule_runner: RuleRunner) -> None:
    """This tests that we correctly handle resolving from both specs with and without owners."""
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
    specs = SpecsParser(root_dir=rule_runner.build_root).parse_specs(
        [*no_interaction_specs, *multiple_files_specs],
        description_of_origin="tests",
    )

    result = rule_runner.request(Addresses, [specs])
    assert set(result) == {
        Address("fs_spec", relative_file_path="f.txt"),
        Address("address_spec"),
        Address("address_spec", target_name="nonfile", generated_name="gen"),
        Address("multiple_files"),
        Address("multiple_files", relative_file_path="f2.txt"),
    }


def test_resolve_addresses_from_specs(rule_runner: RuleRunner) -> None:
    """Test that ignore specs win out over include specs, no matter what."""
    rule_runner.write_files(
        {
            "f.txt": "",
            "BUILD": dedent(
                """\
                file_generator(name='files', sources=['f.txt'])
                nonfile_generator(name='nonfile')
                target(name='tgt', resolve=parametrize("a", "b"))
                """
            ),
            "subdir/BUILD": "target(name='tgt')",
        }
    )

    def assert_resolved(specs: Iterable[str], expected: set[str]) -> None:
        specs_obj = SpecsParser().parse_specs(specs, description_of_origin="tests")
        result = rule_runner.request(Addresses, [specs_obj])
        assert {addr.spec for addr in result} == expected

    assert_resolved(["//:tgt"], {"//:tgt@resolve=a", "//:tgt@resolve=b"})
    assert_resolved(["//:tgt", "-//:tgt@resolve=a"], {"//:tgt@resolve=b"})
    assert_resolved(["//:tgt", "-//:tgt"], set())

    assert_resolved(
        ["::"],
        {
            "//:tgt@resolve=a",
            "//:tgt@resolve=b",
            "//:files",
            "//f.txt:files",
            "//:nonfile",
            "//:nonfile#gen",
            "subdir:tgt",
        },
    )
    assert_resolved(
        ["::", "-subdir::", "-//:nonfile", "-f.txt"],
        {"//:tgt@resolve=a", "//:tgt@resolve=b", "//:files", "//:nonfile#gen"},
    )


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
    specs = RawSpecs(
        recursive_globs=(RecursiveGlobSpec("addr_specs"),),
        file_globs=(FileGlobSpec("fs_specs/*.txt"),),
        filter_by_global_options=True,
        description_of_origin="tests",
    )

    def check(tags_option: str | None, expected: set[Address]) -> None:
        if tags_option:
            rule_runner.set_options([f"--tag={tags_option}"])
        addresses = rule_runner.request(Addresses, [specs])
        result = rule_runner.request(FilteredTargets, [addresses])
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
# SpecsPaths
# -----------------------------------------------------------------------------------------------


def test_resolve_specs_paths(rule_runner: RuleRunner) -> None:
    """Test that we convert specs into a single snapshot for target-less goals.

    Some important edge cases:
    - Files without owning targets still show up.
    - If a file is owned by a target, and that target is ignored with a spec, or is filtered out
      e.g. via `--tags`, the file must not show up.
    - If a file is explicitly ignored via specs, it must now show up.
    """
    rule_runner.write_files(
        {
            "demo/unowned.foo": "",
            "demo/f1.txt": "",
            "demo/f2.txt": "",
            "demo/f3.txt": "",
            "demo/BUILD": dedent(
                """\
                target(name='f1', sources=['f1.txt'])
                target(name='f2', sources=['f2.txt'])
                target(name='f3', sources=['f3.txt'], tags=['ignore'])

                # Non-file targets are ignored.
                nonfile_generator(name='nonfile')
                """
            ),
            "f.txt": "",
            "unowned/f.txt": "",
            "unowned/subdir/f.txt": "",
        }
    )
    rule_runner.set_options(["--tag=-ignore"])

    def assert_paths(
        specs: Iterable[str], expected_files: set[str], expected_dirs: set[str]
    ) -> None:
        specs_obj = SpecsParser().parse_specs(specs, description_of_origin="tests")
        result = rule_runner.request(SpecsPaths, [specs_obj])
        assert set(result.files) == expected_files
        assert set(result.dirs) == expected_dirs

    all_expected_demo_files = {"demo/f1.txt", "demo/f2.txt", "demo/unowned.foo"}
    assert_paths(["demo:f1", "demo/*.txt", "demo/unowned.foo"], all_expected_demo_files, {"demo"})

    assert_paths(
        ["demo:", "-demo:f1", "-demo/f2.txt"], {"demo/unowned.foo", "demo/BUILD"}, {"demo"}
    )
    assert_paths(["demo/*.foo", "-demo/unowned.foo"], set(), set())

    assert_paths([":"], {"f.txt"}, set())
    for dir_suffix in ("", ":"):
        assert_paths([f"unowned{dir_suffix}"], {"unowned/f.txt"}, {"unowned"})
        assert_paths([f"demo{dir_suffix}"], {*all_expected_demo_files, "demo/BUILD"}, {"demo"})

    assert_paths(
        ["::"],
        {*all_expected_demo_files, "demo/BUILD", "f.txt", "unowned/f.txt", "unowned/subdir/f.txt"},
        {"demo", "unowned", "unowned/subdir"},
    )
    assert_paths(
        ["unowned::"],
        {"unowned/f.txt", "unowned/subdir/f.txt"},
        {"unowned", "unowned/subdir"},
    )
    assert_paths(["demo::"], {*all_expected_demo_files, "demo/BUILD"}, {"demo"})


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
    ) -> TargetRootsToFieldSets:
        request = TargetRootsToFieldSetsRequest(
            superclass,
            goal_description="fake",
            no_applicable_targets_behavior=no_applicable_behavior,
        )
        return rule_runner.request(
            TargetRootsToFieldSets,
            [
                request,
                Specs(
                    includes=RawSpecs.create(specs, description_of_origin="tests"),
                    ignores=RawSpecs(description_of_origin="tests"),
                ),
            ],
        )

    valid = find_valid_field_sets(FieldSetSuperclass, [valid_spec, invalid_spec])
    assert valid.targets == (valid_tgt,)
    assert valid.field_sets == (
        FieldSetSubclass1.create(valid_tgt),
        FieldSetSubclass2.create(valid_tgt),
    )

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
        Specs.empty(),
        UnionMembership({}),
        applicable_target_types=[Tgt1],
        goal_description="the `foo` goal",
    )
    remedy = (
        "Please specify relevant file and/or target arguments. Run `pants "
        "--filter-target-type=tgt1 list ::` to find all applicable targets in your project."
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
        Specs(
            includes=RawSpecs(
                file_literals=(FileLiteralSpec("foo.ext"),), description_of_origin="tests"
            ),
            ignores=RawSpecs(description_of_origin="tests"),
        ),
        UnionMembership({}),
        applicable_target_types=[Tgt1, Tgt2],
        goal_description="the `foo` goal",
    )
    remedy = (
        "Please specify relevant file and/or target arguments. Run `pants "
        "--filter-target-type=tgt1,tgt2 list ::` to find all applicable targets in your project, "
        "or run `pants --filter-target-type=tgt1,tgt2 filedeps ::` to find all "
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
        Specs(
            includes=RawSpecs(
                address_literals=(AddressLiteralSpec("foo", "bar"),), description_of_origin="tests"
            ),
            ignores=RawSpecs(description_of_origin="tests"),
        ),
        UnionMembership({}),
        applicable_target_types=[Tgt1],
        goal_description="the `foo` goal",
    )
    assert "However, you only specified target arguments with these target types:" in str(exc)
    exc = NoApplicableTargetsException(
        [invalid_tgt],
        Specs(
            includes=RawSpecs(
                address_literals=(AddressLiteralSpec("foo", "bar"),),
                file_literals=(FileLiteralSpec("foo.ext"),),
                description_of_origin="tests",
            ),
            ignores=RawSpecs(description_of_origin="tests"),
        ),
        UnionMembership({}),
        applicable_target_types=[Tgt1],
        goal_description="the `foo` goal",
    )
    assert "However, you only specified target and file arguments with these target types:" in str(
        exc
    )
