# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re
from textwrap import dedent
from typing import Iterable, Set, cast

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
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.engine.addresses import Address, Addresses, AddressInput, BuildFileAddress
from pants.engine.fs import DigestContents, FileContent, PathGlobs
from pants.engine.internals.build_files import (
    AddressFamilyDir,
    evaluate_preludes,
    parse_address_family,
)
from pants.engine.internals.parser import BuildFilePreludeSymbols, Parser
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.internals.target_adaptor import TargetAdaptor
from pants.engine.rules import Get, rule
from pants.engine.target import (
    Dependencies,
    GeneratedTargets,
    GenerateTargetsRequest,
    MultipleSourcesField,
    SourcesPaths,
    SourcesPathsRequest,
    Tags,
    Target,
    generate_file_level_targets,
)
from pants.engine.unions import UnionRule
from pants.option.global_options import GlobalOptions
from pants.testutil.option_util import create_subsystem
from pants.testutil.rule_runner import MockGet, QueryRule, RuleRunner, run_rule_with_mocks
from pants.util.frozendict import FrozenDict


def test_parse_address_family_empty() -> None:
    """Test that parsing an empty BUILD file results in an empty AddressFamily."""
    af = run_rule_with_mocks(
        parse_address_family,
        rule_args=[
            Parser(build_root="", target_type_aliases=[], object_aliases=BuildFileAliases()),
            create_subsystem(GlobalOptions, build_patterns=["BUILD"], build_ignore=[]),
            BuildFilePreludeSymbols(FrozenDict()),
            AddressFamilyDir("/dev/null"),
        ],
        mock_gets=[
            MockGet(
                output_type=DigestContents,
                input_type=PathGlobs,
                mock=lambda _: DigestContents([FileContent(path="/dev/null/BUILD", content=b"")]),
            ),
        ],
    )
    assert len(af.name_to_target_adaptors) == 0


def run_prelude_parsing_rule(prelude_content: str) -> BuildFilePreludeSymbols:
    symbols = run_rule_with_mocks(
        evaluate_preludes,
        rule_args=[create_subsystem(GlobalOptions, build_file_prelude_globs=["prelude"])],
        mock_gets=[
            MockGet(
                output_type=DigestContents,
                input_type=PathGlobs,
                mock=lambda _: DigestContents(
                    [FileContent(path="/dev/null/prelude", content=prelude_content.encode())]
                ),
            ),
        ],
    )
    return cast(BuildFilePreludeSymbols, symbols)


def test_prelude_parsing_good() -> None:
    result = run_prelude_parsing_rule("def foo(): return 1")
    assert result.symbols["foo"]() == 1


def test_prelude_parsing_syntax_error() -> None:
    with pytest.raises(
        Exception, match="Error parsing prelude file /dev/null/prelude: name 'blah' is not defined"
    ):
        run_prelude_parsing_rule("blah")


def test_prelude_parsing_illegal_import() -> None:
    prelude_content = dedent(
        """\
        import os
        def make_target():
            python_sources()
        """
    )
    with pytest.raises(
        Exception,
        match="Import used in /dev/null/prelude at line 1\\. Import statements are banned",
    ):
        run_prelude_parsing_rule(prelude_content)


class MockTgt(Target):
    alias = "mock_tgt"
    core_fields = (Dependencies, MultipleSourcesField, Tags)


class MockGeneratedTarget(Target):
    alias = "generated"
    core_fields = (Dependencies, MultipleSourcesField, Tags)


class MockTargetGenerator(Target):
    alias = "generator"
    core_fields = (Dependencies, MultipleSourcesField, Tags)


class MockGenerateTargetsRequest(GenerateTargetsRequest):
    generate_from = MockTargetGenerator


@rule
async def generate_mock_generated_target(request: MockGenerateTargetsRequest) -> GeneratedTargets:
    paths = await Get(SourcesPaths, SourcesPathsRequest(request.generator[MultipleSourcesField]))
    # Generate using both "file address" and "generated target" syntax.
    return GeneratedTargets(
        request.generator,
        [
            *generate_file_level_targets(
                MockGeneratedTarget,
                request.generator,
                paths.files,
                None,
                add_dependencies_on_all_siblings=True,
                use_generated_address_syntax=False,
            ).values(),
            *generate_file_level_targets(
                MockGeneratedTarget,
                request.generator,
                paths.files,
                None,
                add_dependencies_on_all_siblings=True,
                use_generated_address_syntax=True,
            ).values(),
        ],
    )


def test_resolve_address() -> None:
    rule_runner = RuleRunner(rules=[QueryRule(Address, (AddressInput,))])
    rule_runner.write_files({"a/b/c.txt": "", "f.txt": ""})

    def assert_is_expected(address_input: AddressInput, expected: Address) -> None:
        assert rule_runner.request(Address, [address_input]) == expected

    assert_is_expected(
        AddressInput("a/b/c.txt"), Address("a/b", target_name=None, relative_file_path="c.txt")
    )
    assert_is_expected(
        AddressInput("a/b"), Address("a/b", target_name=None, relative_file_path=None)
    )

    assert_is_expected(AddressInput("a/b", target_component="c"), Address("a/b", target_name="c"))
    assert_is_expected(
        AddressInput("a/b/c.txt", target_component="c"),
        Address("a/b", relative_file_path="c.txt", target_name="c"),
    )

    # Top-level addresses will not have a path_component, unless they are a file address.
    assert_is_expected(
        AddressInput("f.txt", target_component="original"),
        Address("", relative_file_path="f.txt", target_name="original"),
    )
    assert_is_expected(AddressInput("", target_component="t"), Address("", target_name="t"))

    with pytest.raises(ExecutionError) as exc:
        rule_runner.request(Address, [AddressInput("a/b/fake")])
    assert "'a/b/fake' does not exist on disk" in str(exc.value)


@pytest.fixture
def target_adaptor_rule_runner() -> RuleRunner:
    return RuleRunner(rules=[QueryRule(TargetAdaptor, (Address,))], target_types=[MockTgt])


def test_target_adaptor_parsed_correctly(target_adaptor_rule_runner: RuleRunner) -> None:
    target_adaptor_rule_runner.write_files(
        {
            "helloworld/BUILD": dedent(
                """\
                mock_tgt(
                    fake_field=42,
                    dependencies=[
                        # Because we don't follow dependencies or even parse dependencies, this
                        # self-cycle should be fine.
                        "helloworld",
                        ":sibling",
                        "helloworld/util",
                        "helloworld/util:tests",
                    ],
                )
                """
            )
        }
    )
    addr = Address("helloworld")
    target_adaptor = target_adaptor_rule_runner.request(TargetAdaptor, [addr])
    assert target_adaptor.name == "helloworld"
    assert target_adaptor.type_alias == "mock_tgt"
    assert target_adaptor.kwargs["dependencies"] == [
        "helloworld",
        ":sibling",
        "helloworld/util",
        "helloworld/util:tests",
    ]
    # NB: TargetAdaptors do not validate what fields are valid. The Target API should error
    # when encountering this, but it's fine at this stage.
    assert target_adaptor.kwargs["fake_field"] == 42


def test_target_adaptor_not_found(target_adaptor_rule_runner: RuleRunner) -> None:
    with pytest.raises(ExecutionError) as exc:
        target_adaptor_rule_runner.request(TargetAdaptor, [Address("helloworld")])
    assert "Directory \\'helloworld\\' does not contain any BUILD files" in str(exc)

    target_adaptor_rule_runner.write_files({"helloworld/BUILD": "mock_tgt(name='other_tgt')"})
    expected_rx_str = re.escape(
        "'helloworld' was not found in namespace 'helloworld'. Did you mean one of:\n  :other_tgt"
    )
    with pytest.raises(ExecutionError, match=expected_rx_str):
        target_adaptor_rule_runner.request(TargetAdaptor, [Address("helloworld")])


def test_build_file_address() -> None:
    rule_runner = RuleRunner(
        rules=[QueryRule(BuildFileAddress, (Address,))], target_types=[MockTgt]
    )
    rule_runner.write_files({"helloworld/BUILD.ext": "mock_tgt()"})

    def assert_bfa_resolved(address: Address) -> None:
        expected_bfa = BuildFileAddress(address, "helloworld/BUILD.ext")
        bfa = rule_runner.request(BuildFileAddress, [address])
        assert bfa == expected_bfa

    assert_bfa_resolved(Address("helloworld"))
    # Generated targets should use their target generator's BUILD file.
    assert_bfa_resolved(Address("helloworld", generated_name="f.txt"))
    assert_bfa_resolved(Address("helloworld", relative_file_path="f.txt"))


@pytest.fixture
def address_specs_rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            generate_mock_generated_target,
            UnionRule(GenerateTargetsRequest, MockGenerateTargetsRequest),
            QueryRule(Addresses, [AddressSpecs]),
        ],
        target_types=[MockTgt, MockGeneratedTarget, MockTargetGenerator],
    )


def resolve_address_specs(
    rule_runner: RuleRunner,
    specs: Iterable[AddressSpec],
) -> Set[Address]:
    result = rule_runner.request(Addresses, [AddressSpecs(specs, filter_by_global_options=True)])
    return set(result)


def test_address_specs_deduplication(address_specs_rule_runner: RuleRunner) -> None:
    """When multiple specs cover the same address, we should deduplicate to one single Address."""
    address_specs_rule_runner.write_files(
        {"demo/f.txt": "", "demo/BUILD": "mock_tgt(sources=['f.txt'])"}
    )
    specs = [
        AddressLiteralSpec("demo"),
        SiblingAddresses("demo"),
        DescendantAddresses("demo"),
        AscendantAddresses("demo"),
        # We also include a generated target and file address to ensure that that is included in
        # the result.
        AddressLiteralSpec("demo", None, "gen"),
        AddressLiteralSpec("demo/f.txt"),
    ]
    assert resolve_address_specs(address_specs_rule_runner, specs) == {
        Address("demo"),
        Address("demo", generated_name="gen"),
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
        Address("demo", target_name="b")
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
                mock_tgt(name="exclude_me", sources=["f.txt"])
                mock_tgt(name="not_me", sources=["f.txt"])
                """
            ),
        }
    )

    assert resolve_address_specs(address_specs_rule_runner, [SiblingAddresses("demo")]) == {
        Address("demo", target_name="not_me")
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
        with pytest.raises(ExecutionError) as exc:
            resolve_address_specs(address_specs_rule_runner, specs)
        assert expected in str(exc.value)

    # Literal addresses require both a BUILD file to exist and for a target to be resolved.
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

    # SiblingAddresses requires the BUILD file to exist and at least one match.
    assert_resolve_error(
        [SiblingAddresses("fake")],
        expected=(
            "'fake' does not contain any BUILD files, but 'fake:' expected matching targets "
            "there."
        ),
    )
    assert_resolve_error(
        [SiblingAddresses("empty")],
        expected="Address spec 'empty:' does not match any targets",
    )

    # MaybeEmptySiblingAddresses does not require a BUILD file to exist nor any matches.
    assert not resolve_address_specs(
        address_specs_rule_runner, [MaybeEmptySiblingAddresses("fake")]
    )
    assert not resolve_address_specs(
        address_specs_rule_runner, [MaybeEmptySiblingAddresses("empty")]
    )

    # DescendantAddresses requires at least one match, even if BUILD files exist.
    assert_resolve_error(
        [DescendantAddresses("fake"), DescendantAddresses("empty")],
        expected="Address spec 'fake::' does not match any targets",
    )

    # AscendantAddresses does not require any matches or BUILD files.
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
        f"The address `demo/f.txt:not_owner` is not generated by the `{MockTargetGenerator.alias}` "
        f"target `demo:not_owner`"
    ) in str(exc.value)
