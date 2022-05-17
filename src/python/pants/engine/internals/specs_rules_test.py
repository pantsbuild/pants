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
    MaybeEmptySiblingAddresses,
    SiblingAddresses,
)
from pants.build_graph.address import Address
from pants.engine.addresses import Addresses
from pants.engine.internals.build_files_test import (
    MockGeneratedTarget,
    MockGenerateTargetsRequest,
    MockTargetGenerator,
    MockTgt,
    generate_mock_generated_target,
)
from pants.engine.internals.parametrize import Parametrize
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.rules import QueryRule
from pants.engine.target import GenerateTargetsRequest
from pants.engine.unions import UnionRule
from pants.testutil.rule_runner import RuleRunner, engine_error
from pants.util.frozendict import FrozenDict

# -----------------------------------------------------------------------------------------------
# AddressSpecs
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
        target_types=[MockTgt, MockGeneratedTarget, MockTargetGenerator],
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
