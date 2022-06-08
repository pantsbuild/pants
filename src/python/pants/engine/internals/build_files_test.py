# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import re
from textwrap import dedent
from typing import cast

import pytest

from pants.build_graph.address import BuildFileAddressRequest
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.engine.addresses import Address, AddressInput, BuildFileAddress
from pants.engine.fs import DigestContents, FileContent, PathGlobs
from pants.engine.internals.build_files import (
    AddressFamilyDir,
    BuildFileOptions,
    evaluate_preludes,
    parse_address_family,
)
from pants.engine.internals.parser import BuildFilePreludeSymbols, Parser
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.internals.target_adaptor import TargetAdaptor
from pants.engine.target import Dependencies, MultipleSourcesField, StringField, Tags, Target
from pants.testutil.rule_runner import MockGet, QueryRule, RuleRunner, run_rule_with_mocks
from pants.util.frozendict import FrozenDict


def test_parse_address_family_empty() -> None:
    """Test that parsing an empty BUILD file results in an empty AddressFamily."""
    af = run_rule_with_mocks(
        parse_address_family,
        rule_args=[
            Parser(build_root="", target_type_aliases=[], object_aliases=BuildFileAliases()),
            BuildFileOptions(("BUILD",)),
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
        rule_args=[BuildFileOptions((), prelude_globs=("prelude",))],
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


class ResolveField(StringField):
    alias = "resolve"


class MockTgt(Target):
    alias = "mock_tgt"
    core_fields = (Dependencies, MultipleSourcesField, Tags, ResolveField)


def test_resolve_address() -> None:
    rule_runner = RuleRunner(rules=[QueryRule(Address, (AddressInput,))])
    rule_runner.write_files({"a/b/c.txt": "", "f.txt": ""})

    def assert_is_expected(address_input: AddressInput, expected: Address) -> None:
        assert rule_runner.request(Address, [address_input]) == expected

    assert_is_expected(
        AddressInput("a/b/c.txt", description_of_origin="tests"),
        Address("a/b", target_name=None, relative_file_path="c.txt"),
    )
    assert_is_expected(
        AddressInput("a/b", description_of_origin="tests"),
        Address("a/b", target_name=None, relative_file_path=None),
    )

    assert_is_expected(
        AddressInput("a/b", target_component="c", description_of_origin="tests"),
        Address("a/b", target_name="c"),
    )
    assert_is_expected(
        AddressInput("a/b/c.txt", target_component="c", description_of_origin="tests"),
        Address("a/b", relative_file_path="c.txt", target_name="c"),
    )

    # Top-level addresses will not have a path_component, unless they are a file address.
    assert_is_expected(
        AddressInput("f.txt", target_component="original", description_of_origin="tests"),
        Address("", relative_file_path="f.txt", target_name="original"),
    )
    assert_is_expected(
        AddressInput("", target_component="t", description_of_origin="tests"),
        Address("", target_name="t"),
    )

    with pytest.raises(ExecutionError) as exc:
        rule_runner.request(Address, [AddressInput("a/b/fake", description_of_origin="tests")])
    assert "'a/b/fake' does not exist on disk" in str(exc.value)


@pytest.fixture
def target_adaptor_rule_runner() -> RuleRunner:
    return RuleRunner(rules=[QueryRule(TargetAdaptor, (Address,))], target_types=[MockTgt])


def test_target_adaptor_parsed_correctly(target_adaptor_rule_runner: RuleRunner) -> None:
    target_adaptor_rule_runner.write_files(
        {
            "helloworld/dir/BUILD": dedent(
                """\
                mock_tgt(
                    fake_field=42,
                    dependencies=[
                        # Because we don't follow dependencies or even parse dependencies, this
                        # self-cycle should be fine.
                        ":dir",
                        ":sibling",
                        "helloworld/util",
                        "helloworld/util:tests",
                    ],
                    build_file_dir=f"build file's dir is: {build_file_dir()}"
                )

                mock_tgt(name='t2')
                """
            )
        }
    )
    target_adaptor = target_adaptor_rule_runner.request(TargetAdaptor, [Address("helloworld/dir")])
    assert target_adaptor.name is None
    assert target_adaptor.type_alias == "mock_tgt"
    assert target_adaptor.kwargs["dependencies"] == [
        ":dir",
        ":sibling",
        "helloworld/util",
        "helloworld/util:tests",
    ]
    # NB: TargetAdaptors do not validate what fields are valid. The Target API should error
    # when encountering this, but it's fine at this stage.
    assert target_adaptor.kwargs["fake_field"] == 42
    assert target_adaptor.kwargs["build_file_dir"] == "build file's dir is: helloworld/dir"

    target_adaptor = target_adaptor_rule_runner.request(
        TargetAdaptor, [Address("helloworld/dir", target_name="t2")]
    )
    assert target_adaptor.name == "t2"
    assert target_adaptor.type_alias == "mock_tgt"


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
        rules=[QueryRule(BuildFileAddress, [BuildFileAddressRequest])], target_types=[MockTgt]
    )
    rule_runner.write_files({"helloworld/BUILD.ext": "mock_tgt()"})

    def assert_bfa_resolved(address: Address) -> None:
        expected_bfa = BuildFileAddress(address, "helloworld/BUILD.ext")
        bfa = rule_runner.request(
            BuildFileAddress, [BuildFileAddressRequest(address, description_of_origin="tests")]
        )
        assert bfa == expected_bfa

    assert_bfa_resolved(Address("helloworld"))
    # Generated targets should use their target generator's BUILD file.
    assert_bfa_resolved(Address("helloworld", generated_name="f.txt"))
    assert_bfa_resolved(Address("helloworld", relative_file_path="f.txt"))
