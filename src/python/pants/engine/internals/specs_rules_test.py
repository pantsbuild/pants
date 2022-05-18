# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent
from typing import Iterable

import pytest

from pants.base.exceptions import ResolveError
from pants.base.specs import (
    AddressLiteralSpec,
    AddressSpec,
    AddressSpecs,
    AscendantAddresses,
    DescendantAddresses,
    FileGlobSpec,
    FileLiteralSpec,
    FilesystemSpec,
    FilesystemSpecs,
    MaybeEmptySiblingAddresses,
    SiblingAddresses,
    Specs,
)
from pants.base.specs_parser import SpecsParser
from pants.build_graph.address import Address
from pants.engine.addresses import Addresses
from pants.engine.fs import SpecsSnapshot
from pants.engine.internals.build_files_test import MockGeneratedTarget as MockGeneratedTargetAS
from pants.engine.internals.build_files_test import MockGenerateTargetsRequest
from pants.engine.internals.build_files_test import MockTargetGenerator as MockTargetGeneratorAS
from pants.engine.internals.build_files_test import MockTgt as MockTgtAS
from pants.engine.internals.build_files_test import generate_mock_generated_target
from pants.engine.internals.graph_test import MockGeneratedTarget as MockGeneratedTargetFS
from pants.engine.internals.graph_test import MockTarget as MockTargetFS
from pants.engine.internals.graph_test import MockTargetGenerator as MockTargetGeneratorFS
from pants.engine.internals.parametrize import Parametrize
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.rules import QueryRule
from pants.engine.target import FilteredTargets, GenerateTargetsRequest
from pants.engine.unions import UnionRule
from pants.testutil.rule_runner import RuleRunner, engine_error
from pants.util.frozendict import FrozenDict

# -----------------------------------------------------------------------------------------------
# AddressSpecs -> Targets
# -----------------------------------------------------------------------------------------------


@pytest.fixture
def address_specs_rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            generate_mock_generated_target,
            UnionRule(GenerateTargetsRequest, MockGenerateTargetsRequest),
            QueryRule(Addresses, [AddressSpecs]),
        ],
        objects={"parametrize": Parametrize},
        target_types=[MockTgtAS, MockGeneratedTargetAS, MockTargetGeneratorAS],
    )


def resolve_address_specs(
    rule_runner: RuleRunner,
    specs: Iterable[AddressSpec],
) -> set[Address]:
    result = rule_runner.request(Addresses, [AddressSpecs(specs, filter_by_global_options=True)])
    return set(result)


def test_address_specs_literals_vs_globs(address_specs_rule_runner: RuleRunner) -> None:
    address_specs_rule_runner.write_files(
        {
            "demo/BUILD": dedent(
                """\
                generator(sources=['**/*.txt'])
                """
            ),
            "demo/f1.txt": "",
            "demo/f2.txt": "",
            "demo/f[3].txt": "",
            "demo/subdir/f.txt": "",
            "demo/subdir/f.another_ext": "",
            "demo/subdir/BUILD": "mock_tgt(name='another_ext', sources=['f.another_ext'])",
            "another_dir/BUILD": "mock_tgt(sources=[])",
        }
    )

    def assert_resolved(spec: AddressSpec, expected: set[Address]) -> None:
        result = resolve_address_specs(address_specs_rule_runner, [spec])
        assert result == expected

    # Literals should be "one-in, one-out".
    assert_resolved(AddressLiteralSpec("demo"), {Address("demo")})
    assert_resolved(
        AddressLiteralSpec("demo/f1.txt"), {Address("demo", relative_file_path="f1.txt")}
    )
    assert_resolved(
        AddressLiteralSpec("demo", None, "f1.txt"), {Address("demo", generated_name="f1.txt")}
    )
    assert_resolved(
        AddressLiteralSpec("demo/subdir", "another_ext"),
        {Address("demo/subdir", target_name="another_ext")},
    )

    assert_resolved(
        # Match all targets that reside in `demo/`, either because explicitly declared there or
        # generated into that dir. Note that this does not include `demo#subdir/f2.ext`, even
        # though its target generator matches.
        SiblingAddresses("demo"),
        {
            Address("demo"),
            Address("demo", relative_file_path="f1.txt"),
            Address("demo", generated_name="f1.txt"),
            Address("demo", relative_file_path="f2.txt"),
            Address("demo", generated_name="f2.txt"),
            Address("demo", relative_file_path="f[[]3].txt"),
            Address("demo", generated_name="f[[]3].txt"),
        },
    )
    assert_resolved(
        # Should include all generated targets that reside in `demo/subdir`, even though their
        # target generator is in an ancestor.
        SiblingAddresses("demo/subdir"),
        {
            Address("demo", relative_file_path="subdir/f.txt"),
            Address("demo", generated_name="subdir/f.txt"),
            Address("demo/subdir", target_name="another_ext"),
        },
    )

    all_tgts_in_demo = {
        Address("demo"),
        Address("demo", relative_file_path="f1.txt"),
        Address("demo", generated_name="f1.txt"),
        Address("demo", relative_file_path="f2.txt"),
        Address("demo", generated_name="f2.txt"),
        Address("demo", relative_file_path="f[[]3].txt"),
        Address("demo", generated_name="f[[]3].txt"),
        Address("demo", relative_file_path="subdir/f.txt"),
        Address("demo", generated_name="subdir/f.txt"),
        Address("demo/subdir", target_name="another_ext"),
    }
    assert_resolved(DescendantAddresses("demo"), all_tgts_in_demo)
    assert_resolved(AscendantAddresses("demo/subdir"), all_tgts_in_demo)
    assert_resolved(
        AscendantAddresses("demo"),
        {
            Address("demo"),
            Address("demo", relative_file_path="f1.txt"),
            Address("demo", generated_name="f1.txt"),
            Address("demo", relative_file_path="f2.txt"),
            Address("demo", generated_name="f2.txt"),
            Address("demo", relative_file_path="f[[]3].txt"),
            Address("demo", generated_name="f[[]3].txt"),
        },
    )


def test_address_specs_deduplication(address_specs_rule_runner: RuleRunner) -> None:
    """When multiple specs cover the same address, we should deduplicate to one single Address."""
    address_specs_rule_runner.write_files(
        {"demo/f.txt": "", "demo/BUILD": "generator(sources=['f.txt'])"}
    )
    specs = [
        AddressLiteralSpec("demo"),
        SiblingAddresses("demo"),
        DescendantAddresses("demo"),
        AscendantAddresses("demo"),
        # We also include targets generated from `demo` to ensure that the final result has both
        # the generator and its generated targets.
        AddressLiteralSpec("demo", None, "f.txt"),
        AddressLiteralSpec("demo/f.txt"),
    ]
    assert resolve_address_specs(address_specs_rule_runner, specs) == {
        Address("demo"),
        Address("demo", generated_name="f.txt"),
        Address("demo", relative_file_path="f.txt"),
    }


def test_address_specs_filter_by_tag(address_specs_rule_runner: RuleRunner) -> None:
    address_specs_rule_runner.set_options(["--tag=+integration"])
    address_specs_rule_runner.write_files(
        {
            "demo/f.txt": "",
            "demo/BUILD": dedent(
                """\
                generator(name="a", sources=["f.txt"])
                generator(name="b", sources=["f.txt"], tags=["integration"])
                generator(name="c", sources=["f.txt"], tags=["ignore"])
                """
            ),
        }
    )
    assert resolve_address_specs(address_specs_rule_runner, [SiblingAddresses("demo")]) == {
        Address("demo", target_name="b"),
        Address("demo", target_name="b", relative_file_path="f.txt"),
        Address("demo", target_name="b", generated_name="f.txt"),
    }

    # The same filtering should work when given literal addresses, including generated targets and
    # file addresses.
    literals_result = resolve_address_specs(
        address_specs_rule_runner,
        [
            AddressLiteralSpec("demo", "a"),
            AddressLiteralSpec("demo", "b"),
            AddressLiteralSpec("demo", "c"),
            AddressLiteralSpec("demo/f.txt", "a"),
            AddressLiteralSpec("demo/f.txt", "b"),
            AddressLiteralSpec("demo", "a", "f.txt"),
            AddressLiteralSpec("demo", "b", "f.txt"),
            AddressLiteralSpec("demo", "c", "f.txt"),
        ],
    )
    assert literals_result == {
        Address("demo", target_name="b"),
        Address("demo", target_name="b", generated_name="f.txt"),
        Address("demo", target_name="b", relative_file_path="f.txt"),
    }


def test_address_specs_filter_by_exclude_pattern(address_specs_rule_runner: RuleRunner) -> None:
    address_specs_rule_runner.set_options(["--exclude-target-regexp=exclude_me.*"])
    address_specs_rule_runner.write_files(
        {
            "demo/f.txt": "",
            "demo/BUILD": dedent(
                """\
                generator(name="exclude_me", sources=["f.txt"])
                generator(name="not_me", sources=["f.txt"])
                """
            ),
        }
    )

    assert resolve_address_specs(address_specs_rule_runner, [SiblingAddresses("demo")]) == {
        Address("demo", target_name="not_me"),
        Address("demo", target_name="not_me", relative_file_path="f.txt"),
        Address("demo", target_name="not_me", generated_name="f.txt"),
    }

    # The same filtering should work when given literal addresses, including generated targets and
    # file addresses.
    literals_result = resolve_address_specs(
        address_specs_rule_runner,
        [
            AddressLiteralSpec("demo", "exclude_me"),
            AddressLiteralSpec("demo", "not_me"),
            AddressLiteralSpec("demo", "exclude_me", "f.txt"),
            AddressLiteralSpec("demo", "not_me", "f.txt"),
            AddressLiteralSpec("demo/f.txt", "exclude_me"),
            AddressLiteralSpec("demo/f.txt", "not_me"),
        ],
    )

    assert literals_result == {
        Address("demo", target_name="not_me"),
        Address("demo", target_name="not_me", relative_file_path="f.txt"),
        Address("demo", target_name="not_me", generated_name="f.txt"),
    }


def test_address_specs_do_not_exist(address_specs_rule_runner: RuleRunner) -> None:
    address_specs_rule_runner.write_files(
        {"real/f.txt": "", "real/BUILD": "mock_tgt(sources=['f.txt'])", "empty/BUILD": "# empty"}
    )

    def assert_resolve_error(specs: Iterable[AddressSpec], *, expected: str) -> None:
        with engine_error(contains=expected):
            resolve_address_specs(address_specs_rule_runner, specs)

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

    # SiblingAddresses requires at least one match.
    assert_resolve_error(
        [SiblingAddresses("fake")],
        expected="No targets found for the address glob `fake:`",
    )
    assert_resolve_error(
        [SiblingAddresses("empty")], expected="No targets found for the address glob `empty:`"
    )

    # MaybeEmptySiblingAddresses does not require any matches.
    assert not resolve_address_specs(
        address_specs_rule_runner, [MaybeEmptySiblingAddresses("fake")]
    )
    assert not resolve_address_specs(
        address_specs_rule_runner, [MaybeEmptySiblingAddresses("empty")]
    )

    # DescendantAddresses requires at least one match.
    assert_resolve_error(
        [DescendantAddresses("fake"), DescendantAddresses("empty")],
        expected="No targets found for these address globs: ['empty::', 'fake::']",
    )

    # AscendantAddresses does not require any matches.
    assert not resolve_address_specs(
        address_specs_rule_runner, [AscendantAddresses("fake"), AscendantAddresses("empty")]
    )


def test_address_specs_generated_target_does_not_belong_to_generator(
    address_specs_rule_runner: RuleRunner,
) -> None:
    address_specs_rule_runner.write_files(
        {
            "demo/f.txt": "",
            "demo/BUILD": dedent(
                """\
                generator(name='owner', sources=['f.txt'])
                generator(name='not_owner')
                """
            ),
        }
    )

    with pytest.raises(ExecutionError) as exc:
        resolve_address_specs(
            address_specs_rule_runner, [AddressLiteralSpec("demo/f.txt", "not_owner")]
        )
    assert (
        "The address `demo/f.txt:not_owner` was not generated by the target `demo:not_owner`"
    ) in str(exc.value)


def test_address_specs_parametrize(
    address_specs_rule_runner: RuleRunner,
) -> None:
    address_specs_rule_runner.write_files(
        {
            "demo/f.txt": "",
            "demo/BUILD": dedent(
                """\
                generator(sources=['f.txt'], resolve=parametrize("a", "b"))
                mock_tgt(sources=['f.txt'], name="not_gen", resolve=parametrize("a", "b"))
                """
            ),
        }
    )

    def assert_resolved(spec: AddressSpec, expected: set[Address]) -> None:
        assert resolve_address_specs(address_specs_rule_runner, [spec]) == expected

    not_gen_resolve_a = Address("demo", target_name="not_gen", parameters={"resolve": "a"})
    not_gen_resolve_b = Address("demo", target_name="not_gen", parameters={"resolve": "b"})
    generator_resolve_a = {
        Address("demo", generated_name="f.txt", parameters={"resolve": "a"}),
        Address("demo", relative_file_path="f.txt", parameters={"resolve": "a"}),
        Address("demo", parameters={"resolve": "a"}),
        Address("demo", target_name="not_gen", parameters={"resolve": "a"}),
    }
    generator_resolve_b = {
        Address("demo", generated_name="f.txt", parameters={"resolve": "b"}),
        Address("demo", relative_file_path="f.txt", parameters={"resolve": "b"}),
        Address("demo", parameters={"resolve": "b"}),
        Address("demo", target_name="not_gen", parameters={"resolve": "b"}),
    }

    assert_resolved(
        DescendantAddresses(""),
        {*generator_resolve_a, *generator_resolve_b, not_gen_resolve_a, not_gen_resolve_b},
    )

    # A literal address for a parameterized target works as expected.
    assert_resolved(
        AddressLiteralSpec(
            "demo", target_component="not_gen", parameters=FrozenDict({"resolve": "a"})
        ),
        {not_gen_resolve_a},
    )
    assert_resolved(
        AddressLiteralSpec("demo", parameters=FrozenDict({"resolve": "a"})),
        {Address("demo", parameters={"resolve": "a"})},
    )
    assert_resolved(
        AddressLiteralSpec(
            "demo", generated_component="f.txt", parameters=FrozenDict({"resolve": "a"})
        ),
        {Address("demo", generated_name="f.txt", parameters={"resolve": "a"})},
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
        AddressLiteralSpec("demo", generated_component="f.txt"),
        {Address("demo", generated_name="f.txt", parameters={"resolve": r}) for r in ("a", "b")},
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
            resolve_address_specs(address_specs_rule_runner, [spec])

    assert_errors(AddressLiteralSpec("demo", parameters=FrozenDict({"fake": "v"})))
    assert_errors(AddressLiteralSpec("demo", parameters=FrozenDict({"resolve": "fake"})))


# -----------------------------------------------------------------------------------------------
# FilesystemSpecs -> Targets
# -----------------------------------------------------------------------------------------------


@pytest.fixture
def filesystem_specs_rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            QueryRule(Addresses, [FilesystemSpecs]),
            QueryRule(Addresses, [Specs]),
            QueryRule(FilteredTargets, [Specs]),
        ],
        target_types=[MockTargetFS, MockTargetGeneratorFS, MockGeneratedTargetFS],
    )


def resolve_filesystem_specs(
    rule_runner: RuleRunner,
    specs: Iterable[FilesystemSpec],
) -> list[Address]:
    result = rule_runner.request(Addresses, [FilesystemSpecs(specs)])
    return sorted(result)


def test_filesystem_specs_literal_file(filesystem_specs_rule_runner: RuleRunner) -> None:
    filesystem_specs_rule_runner.write_files(
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
    assert resolve_filesystem_specs(
        filesystem_specs_rule_runner, [FileLiteralSpec("demo/f1.txt")]
    ) == [
        Address("demo", target_name="not-generator"),
        Address("demo", target_name="generator", relative_file_path="f1.txt"),
    ]


def test_filesystem_specs_glob(filesystem_specs_rule_runner: RuleRunner) -> None:
    filesystem_specs_rule_runner.write_files(
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
    filesystem_specs_rule_runner.set_options(["--tag=-skip", "--exclude-target-regexp=skip-me"])
    all_unskipped_addresses = [
        Address("demo", target_name="not-generator"),
        Address("demo", target_name="generator", relative_file_path="f1.txt"),
        Address("demo", target_name="generator", relative_file_path="f2.txt"),
    ]

    assert (
        resolve_filesystem_specs(filesystem_specs_rule_runner, [FileGlobSpec("demo/*.txt")])
        == all_unskipped_addresses
    )
    # We should deduplicate between glob and literal specs.
    assert (
        resolve_filesystem_specs(
            filesystem_specs_rule_runner,
            [FileGlobSpec("demo/*.txt"), FileLiteralSpec("demo/f1.txt")],
        )
        == all_unskipped_addresses
    )


def test_filesystem_specs_nonexistent_file(filesystem_specs_rule_runner: RuleRunner) -> None:
    spec = FileLiteralSpec("demo/fake.txt")
    with engine_error(contains='Unmatched glob from file/directory arguments: "demo/fake.txt"'):
        resolve_filesystem_specs(filesystem_specs_rule_runner, [spec])

    filesystem_specs_rule_runner.set_options(["--owners-not-found-behavior=ignore"])
    assert not resolve_filesystem_specs(filesystem_specs_rule_runner, [spec])


def test_filesystem_specs_no_owner(filesystem_specs_rule_runner: RuleRunner) -> None:
    filesystem_specs_rule_runner.write_files({"no_owners/f.txt": ""})
    # Error for literal specs.
    with pytest.raises(ExecutionError) as exc:
        resolve_filesystem_specs(filesystem_specs_rule_runner, [FileLiteralSpec("no_owners/f.txt")])
    assert "No owning targets could be found for the file `no_owners/f.txt`" in str(exc.value)

    # Do not error for glob specs.
    assert not resolve_filesystem_specs(
        filesystem_specs_rule_runner, [FileGlobSpec("no_owners/*.txt")]
    )


# -----------------------------------------------------------------------------------------------
# Specs -> Targets
# -----------------------------------------------------------------------------------------------


def test_resolve_addresses_from_specs(filesystem_specs_rule_runner: RuleRunner) -> None:
    """This tests that we correctly handle resolving from both address and filesystem specs."""
    filesystem_specs_rule_runner.write_files(
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
    specs = SpecsParser(filesystem_specs_rule_runner.build_root).parse_specs(
        [*no_interaction_specs, *multiple_files_specs]
    )

    result = filesystem_specs_rule_runner.request(Addresses, [specs])
    assert set(result) == {
        Address("fs_spec", relative_file_path="f.txt"),
        Address("address_spec"),
        Address("multiple_files"),
        Address("multiple_files", relative_file_path="f2.txt"),
    }


def test_filtered_targets(filesystem_specs_rule_runner: RuleRunner) -> None:
    filesystem_specs_rule_runner.write_files(
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
            filesystem_specs_rule_runner.set_options([f"--tag={tags_option}"])
        result = filesystem_specs_rule_runner.request(FilteredTargets, [specs])
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


# -----------------------------------------------------------------------------------------------
# SpecsSnapshot
# -----------------------------------------------------------------------------------------------


def test_resolve_specs_snapshot() -> None:
    """This tests that convert filesystem specs and/or address specs into a single snapshot.

    Some important edge cases:
    - When a filesystem spec refers to a file without any owning target, it should be included
      in the snapshot.
    - If a file is covered both by an address spec and by a filesystem spec, we should merge it
      so that the file only shows up once.
    """
    rule_runner = RuleRunner(
        rules=[QueryRule(SpecsSnapshot, (Specs,))], target_types=[MockTargetFS]
    )
    rule_runner.write_files(
        {"demo/f1.txt": "", "demo/f2.txt": "", "demo/BUILD": "target(sources=['*.txt'])"}
    )
    specs = SpecsParser(rule_runner.build_root).parse_specs(
        ["demo:demo", "demo/f1.txt", "demo/BUILD"]
    )
    result = rule_runner.request(SpecsSnapshot, [specs])
    assert result.snapshot.files == ("demo/BUILD", "demo/f1.txt", "demo/f2.txt")
