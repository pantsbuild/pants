# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re
from textwrap import dedent
from typing import Iterable, Optional, Set, cast

import pytest

from pants.base.exceptions import ResolveError
from pants.base.specs import (
    AddressLiteralSpec,
    AddressSpec,
    AddressSpecs,
    AscendantAddresses,
    DescendantAddresses,
    SiblingAddresses,
)
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.engine.addresses import (
    Address,
    AddressesWithOrigins,
    AddressInput,
    AddressWithOrigin,
    BuildFileAddress,
)
from pants.engine.fs import DigestContents, FileContent, PathGlobs
from pants.engine.internals.build_files import (
    AddressFamilyDir,
    evaluate_preludes,
    parse_address_family,
    strip_address_origins,
)
from pants.engine.internals.parser import BuildFilePreludeSymbols, Parser
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.internals.target_adaptor import TargetAdaptor
from pants.engine.target import Dependencies, Sources, Tags, Target
from pants.option.global_options import GlobalOptions
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.testutil.option_util import create_options_bootstrapper, create_subsystem
from pants.testutil.rule_runner import MockGet, QueryRule, RuleRunner, run_rule_with_mocks
from pants.util.frozendict import FrozenDict


def test_parse_address_family_empty() -> None:
    """Test that parsing an empty BUILD file results in an empty AddressFamily."""
    af = run_rule_with_mocks(
        parse_address_family,
        rule_args=[
            Parser(target_type_aliases=[], object_aliases=BuildFileAliases()),
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
            python_library()
        """
    )
    with pytest.raises(
        Exception,
        match="Import used in /dev/null/prelude at line 1\\. Import statements are banned",
    ):
        run_prelude_parsing_rule(prelude_content)


def test_strip_address_origin() -> None:
    addr = Address.parse("//:demo")
    result = run_rule_with_mocks(
        strip_address_origins,
        rule_args=[AddressesWithOrigins([AddressWithOrigin(addr, AddressLiteralSpec("", "demo"))])],
    )
    assert list(result) == [addr]


class MockTgt(Target):
    alias = "mock_tgt"
    core_fields = (Dependencies, Sources, Tags)


def test_resolve_address() -> None:
    rule_runner = RuleRunner(rules=[QueryRule(Address, (AddressInput,))])

    def assert_is_expected(address_input: AddressInput, expected: Address) -> None:
        assert rule_runner.request(Address, [address_input]) == expected

    rule_runner.create_file("a/b/c.txt")
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
    rule_runner.create_file("f.txt")
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
    target_adaptor_rule_runner.add_to_build_file(
        "helloworld",
        dedent(
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
        ),
    )
    addr = Address("helloworld")
    target_adaptor = target_adaptor_rule_runner.request(
        TargetAdaptor, [addr, create_options_bootstrapper()]
    )
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
    bootstrapper = create_options_bootstrapper()
    with pytest.raises(ExecutionError) as exc:
        target_adaptor_rule_runner.request(TargetAdaptor, [Address("helloworld"), bootstrapper])
    assert "Directory \\'helloworld\\' does not contain any BUILD files" in str(exc)

    target_adaptor_rule_runner.add_to_build_file("helloworld", "mock_tgt(name='other_tgt')")
    expected_rx_str = re.escape(
        "'helloworld' was not found in namespace 'helloworld'. Did you mean one of:\n  :other_tgt"
    )
    with pytest.raises(ExecutionError, match=expected_rx_str):
        target_adaptor_rule_runner.request(TargetAdaptor, [Address("helloworld"), bootstrapper])


def test_build_file_address() -> None:
    rule_runner = RuleRunner(
        rules=[QueryRule(BuildFileAddress, (Address,))], target_types=[MockTgt]
    )
    rule_runner.create_file("helloworld/BUILD.ext", "mock_tgt()")
    bootstrapper = create_options_bootstrapper()

    def assert_bfa_resolved(address: Address) -> None:
        expected_bfa = BuildFileAddress(rel_path="helloworld/BUILD.ext", address=address)
        bfa = rule_runner.request(BuildFileAddress, [address, bootstrapper])
        assert bfa == expected_bfa

    assert_bfa_resolved(Address("helloworld"))
    # File addresses should use their base target to find the BUILD file.
    assert_bfa_resolved(Address("helloworld", relative_file_path="f.txt"))


@pytest.fixture
def address_specs_rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[QueryRule(AddressesWithOrigins, (AddressSpecs,))],
        target_types=[MockTgt],
    )


def resolve_address_specs(
    rule_runner: RuleRunner,
    specs: Iterable[AddressSpec],
    bootstrapper: Optional[OptionsBootstrapper] = None,
) -> Set[AddressWithOrigin]:
    result = rule_runner.request(
        AddressesWithOrigins,
        [
            AddressSpecs(specs, filter_by_global_options=True),
            bootstrapper or create_options_bootstrapper(),
        ],
    )
    return set(result)


def test_address_specs_deduplication(address_specs_rule_runner: RuleRunner) -> None:
    """When multiple specs cover the same address, we should deduplicate to one single
    AddressWithOrigin.

    We should use the most specific origin spec possible, such as AddressLiteralSpec >
    SiblingAddresses.
    """
    address_specs_rule_runner.create_file("demo/f.txt")
    address_specs_rule_runner.add_to_build_file("demo", "mock_tgt(sources=['f.txt'])")
    # We also include a file address to ensure that that is included in the result.
    specs = [
        AddressLiteralSpec("demo", "demo"),
        AddressLiteralSpec("demo/f.txt", "demo"),
        SiblingAddresses("demo"),
        DescendantAddresses("demo"),
        AscendantAddresses("demo"),
    ]
    assert resolve_address_specs(address_specs_rule_runner, specs) == {
        AddressWithOrigin(Address("demo"), AddressLiteralSpec("demo", "demo")),
        AddressWithOrigin(
            Address("demo", relative_file_path="f.txt"),
            AddressLiteralSpec("demo/f.txt", "demo"),
        ),
    }


def test_address_specs_filter_by_tag(address_specs_rule_runner: RuleRunner) -> None:
    address_specs_rule_runner.create_file("demo/f.txt")
    address_specs_rule_runner.add_to_build_file(
        "demo",
        dedent(
            """\
            mock_tgt(name="a", sources=["f.txt"])
            mock_tgt(name="b", sources=["f.txt"], tags=["integration"])
            mock_tgt(name="c", sources=["f.txt"], tags=["ignore"])
            """
        ),
    )
    bootstrapper = create_options_bootstrapper(args=["--tag=+integration"])

    assert resolve_address_specs(
        address_specs_rule_runner, [SiblingAddresses("demo")], bootstrapper=bootstrapper
    ) == {AddressWithOrigin(Address("demo", target_name="b"), SiblingAddresses("demo"))}

    # The same filtering should work when given literal addresses, including file addresses.
    # For file addresses, we look up the `tags` field of the original base target.
    literals_result = resolve_address_specs(
        address_specs_rule_runner,
        [
            AddressLiteralSpec("demo", "a"),
            AddressLiteralSpec("demo", "b"),
            AddressLiteralSpec("demo", "c"),
            AddressLiteralSpec("demo/f.txt", "a"),
            AddressLiteralSpec("demo/f.txt", "b"),
            AddressLiteralSpec("demo/f.txt", "c"),
        ],
        bootstrapper=bootstrapper,
    )
    assert literals_result == {
        AddressWithOrigin(
            Address("demo", relative_file_path="f.txt", target_name="b"),
            AddressLiteralSpec("demo/f.txt", "b"),
        ),
        AddressWithOrigin(Address("demo", target_name="b"), AddressLiteralSpec("demo", "b")),
    }


def test_address_specs_filter_by_exclude_pattern(address_specs_rule_runner: RuleRunner) -> None:
    address_specs_rule_runner.create_file("demo/f.txt")
    address_specs_rule_runner.add_to_build_file(
        "demo",
        dedent(
            """\
            mock_tgt(name="exclude_me", sources=["f.txt"])
            mock_tgt(name="not_me", sources=["f.txt"])
            """
        ),
    )
    bootstrapper = create_options_bootstrapper(args=["--exclude-target-regexp=exclude_me.*"])

    assert resolve_address_specs(
        address_specs_rule_runner, [SiblingAddresses("demo")], bootstrapper=bootstrapper
    ) == {AddressWithOrigin(Address("demo", target_name="not_me"), SiblingAddresses("demo"))}

    # The same filtering should work when given literal addresses, including file addresses.
    # The filtering will operate against the normalized Address.spec.
    literals_result = resolve_address_specs(
        address_specs_rule_runner,
        [
            AddressLiteralSpec("demo", "exclude_me"),
            AddressLiteralSpec("demo", "not_me"),
            AddressLiteralSpec("demo/f.txt", "exclude_me"),
            AddressLiteralSpec("demo/f.txt", "not_me"),
        ],
        bootstrapper=bootstrapper,
    )

    assert literals_result == {
        AddressWithOrigin(
            Address("demo", relative_file_path="f.txt", target_name="not_me"),
            AddressLiteralSpec("demo/f.txt", "not_me"),
        ),
        AddressWithOrigin(
            Address("demo", target_name="not_me"), AddressLiteralSpec("demo", "not_me")
        ),
    }


def test_address_specs_do_not_exist(address_specs_rule_runner: RuleRunner) -> None:
    address_specs_rule_runner.create_file("real/f.txt")
    address_specs_rule_runner.add_to_build_file("real", "mock_tgt(sources=['f.txt'])")
    address_specs_rule_runner.add_to_build_file("empty", "# empty")

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

    # SiblingAddresses require the BUILD file to exist, but are okay if no targets are resolved.
    assert_resolve_error(
        [SiblingAddresses("fake")],
        expected=(
            "'fake' does not contain any BUILD files, but 'fake:' expected matching targets "
            "there."
        ),
    )
    assert not resolve_address_specs(address_specs_rule_runner, [SiblingAddresses("empty")])

    # DescendantAddresses requires at least one match, even if BUILD files exist.
    assert_resolve_error(
        [DescendantAddresses("fake"), DescendantAddresses("empty")],
        expected="Address spec 'fake::' does not match any targets",
    )

    # AscendantAddresses does not require any matches or BUILD files.
    assert not resolve_address_specs(
        address_specs_rule_runner, [AscendantAddresses("fake"), AscendantAddresses("empty")]
    )


def test_address_specs_file_does_not_belong_to_target(
    address_specs_rule_runner: RuleRunner,
) -> None:
    """Even if a file's address file exists and target exist, we should validate that the file
    actually belongs to that target."""
    address_specs_rule_runner.create_file("demo/f.txt")
    address_specs_rule_runner.add_to_build_file(
        "demo",
        dedent(
            """\
            mock_tgt(name='owner', sources=['f.txt'])
            mock_tgt(name='not_owner')
            """
        ),
    )

    with pytest.raises(ExecutionError) as exc:
        resolve_address_specs(
            address_specs_rule_runner, [AddressLiteralSpec("demo/f.txt", "not_owner")]
        )
    assert "does not match a file demo/f.txt" in str(exc.value)
