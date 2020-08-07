# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re
import unittest
import unittest.mock
from textwrap import dedent
from typing import Iterable, Optional, cast

import pytest

from pants.base.exceptions import ResolveError
from pants.base.project_tree import Dir
from pants.base.specs import AddressSpecs, SiblingAddresses, SingleAddress
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.engine.addresses import (
    Address,
    Addresses,
    AddressesWithOrigins,
    AddressInput,
    AddressWithOrigin,
    BuildFileAddress,
    BuildFileAddresses,
)
from pants.engine.fs import Digest, DigestContents, FileContent, PathGlobs, Snapshot
from pants.engine.internals.build_files import (
    addresses_with_origins_from_address_specs,
    evaluate_preludes,
    parse_address_family,
    strip_address_origins,
)
from pants.engine.internals.mapper import AddressFamily, AddressMapper, AddressSpecsFilter
from pants.engine.internals.parser import BuildFilePreludeSymbols, Parser
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.internals.target_adaptor import TargetAdaptor
from pants.engine.rules import RootRule
from pants.engine.target import Target
from pants.testutil.engine.util import MockGet, Params, run_rule
from pants.testutil.option.util import create_options_bootstrapper
from pants.testutil.test_base import TestBase
from pants.util.frozendict import FrozenDict


def test_parse_address_family_empty() -> None:
    """Test that parsing an empty BUILD file results in an empty AddressFamily."""
    address_mapper = AddressMapper(
        parser=Parser(target_type_aliases=[], object_aliases=BuildFileAliases())
    )
    af = run_rule(
        parse_address_family,
        rule_args=[address_mapper, BuildFilePreludeSymbols(FrozenDict()), Dir("/dev/null")],
        mock_gets=[
            MockGet(
                product_type=DigestContents,
                subject_type=PathGlobs,
                mock=lambda _: DigestContents([FileContent(path="/dev/null/BUILD", content=b"")]),
            ),
        ],
    )
    assert len(af.name_to_target_adaptors) == 0


def resolve_addresses_with_origins_from_address_specs(
    address_specs: AddressSpecs,
    address_family: AddressFamily,
    *,
    tags: Optional[Iterable[str]] = None,
    exclude_patterns: Optional[Iterable[str]] = None
) -> AddressesWithOrigins:
    mapper = AddressMapper(Parser(target_type_aliases=[], object_aliases=BuildFileAliases()))
    specs_filter = AddressSpecsFilter(tags=tags, exclude_target_regexps=exclude_patterns)
    snapshot = Snapshot(Digest("xx", 2), ("root/BUILD",), ())
    addresses_with_origins = run_rule(
        addresses_with_origins_from_address_specs,
        rule_args=[address_specs, mapper, specs_filter],
        mock_gets=[
            MockGet(product_type=Snapshot, subject_type=PathGlobs, mock=lambda _: snapshot),
            MockGet(product_type=AddressFamily, subject_type=Dir, mock=lambda _: address_family,),
        ],
    )
    return cast(AddressesWithOrigins, addresses_with_origins)


def test_address_specs_duplicated() -> None:
    """Test that matching the same AddressSpec twice succeeds."""
    address_spec = SingleAddress("root", "root")
    address_family = AddressFamily(
        "root", {"root": ("root/BUILD", TargetAdaptor(type_alias="", name="root"))}
    )
    address_specs = AddressSpecs([address_spec, address_spec])

    addresses_with_origins = resolve_addresses_with_origins_from_address_specs(
        address_specs, address_family
    )
    assert len(addresses_with_origins) == 1
    awo = addresses_with_origins[0]
    assert str(awo.address) == "root"
    assert awo.origin == address_spec


def test_address_specs_tag_filter() -> None:
    """Test that targets are filtered based on `tags`."""
    address_specs = AddressSpecs([SiblingAddresses("root")], filter_by_global_options=True)
    address_family = AddressFamily(
        "root",
        {
            "a": ("root/BUILD", TargetAdaptor(type_alias="", name="a")),
            "b": ("root/BUILD", TargetAdaptor(type_alias="", name="b", tags={"integration"})),
            "c": ("root/BUILD", TargetAdaptor(type_alias="", name="c", tags={"not_integration"})),
        },
    )

    addresses_with_origins = resolve_addresses_with_origins_from_address_specs(
        address_specs, address_family, tags=["+integration"]
    )
    assert len(addresses_with_origins) == 1
    awo = addresses_with_origins[0]
    assert str(awo.address) == "root:b"
    assert awo.origin == SiblingAddresses("root")


def test_address_specs_fail_on_nonexistent() -> None:
    """Test that address specs referring to nonexistent targets raise a ResolveError."""
    address_family = AddressFamily(
        "root", {"a": ("root/BUILD", TargetAdaptor(type_alias="", name="a"))}
    )
    address_specs = AddressSpecs([SingleAddress("root", "b"), SingleAddress("root", "a")])

    expected_rx_str = re.escape("'b' was not found in namespace 'root'. Did you mean one of:\n  :a")
    with pytest.raises(ResolveError, match=expected_rx_str):
        resolve_addresses_with_origins_from_address_specs(address_specs, address_family)

    # Ensure that we still catch nonexistent targets later on in the list of command-line
    # address specs.
    address_specs = AddressSpecs([SingleAddress("root", "a"), SingleAddress("root", "b")])
    with pytest.raises(ResolveError, match=expected_rx_str):
        resolve_addresses_with_origins_from_address_specs(address_specs, address_family)


def test_address_specs_exclude_pattern() -> None:
    """Test that targets are filtered based on exclude patterns."""
    address_specs = AddressSpecs([SiblingAddresses("root")], filter_by_global_options=True)
    address_family = AddressFamily(
        "root",
        {
            "exclude_me": ("root/BUILD", TargetAdaptor(type_alias="", name="exclude_me")),
            "not_me": ("root/BUILD", TargetAdaptor(type_alias="", name="not_me")),
        },
    )

    addresses_with_origins = resolve_addresses_with_origins_from_address_specs(
        address_specs, address_family, exclude_patterns=[".exclude*"]
    )
    assert len(addresses_with_origins) == 1
    awo = addresses_with_origins[0]
    assert str(awo.address) == "root:not_me"
    assert awo.origin == SiblingAddresses("root")


def test_address_specs_exclude_pattern_with_single_address() -> None:
    """Test that single address targets are filtered based on exclude patterns."""
    address_specs = AddressSpecs([SingleAddress("root", "not_me")], filter_by_global_options=True)
    address_family = AddressFamily(
        "root", {"not_me": ("root/BUILD", TargetAdaptor(type_alias="", name="not_me"))}
    )
    assert not resolve_addresses_with_origins_from_address_specs(
        address_specs, address_family, exclude_patterns=["root.*"]
    )


def run_prelude_parsing_rule(prelude_content: str) -> BuildFilePreludeSymbols:
    address_mapper = unittest.mock.Mock()
    address_mapper.prelude_glob_patterns = ("prelude",)
    symbols = run_rule(
        evaluate_preludes,
        rule_args=[address_mapper],
        mock_gets=[
            MockGet(
                product_type=DigestContents,
                subject_type=PathGlobs,
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
    result = run_rule(
        strip_address_origins,
        rule_args=[AddressesWithOrigins([AddressWithOrigin(addr, SingleAddress("", "demo"))])],
    )
    assert list(result) == [addr]


class MockTgt(Target):
    alias = "mock_tgt"
    core_fields = ()


class BuildFileIntegrationTest(TestBase):
    @classmethod
    def target_types(cls):
        return [MockTgt]

    @classmethod
    def rules(cls):
        return (*super().rules(), RootRule(Addresses), RootRule(AddressInput))

    def test_resolve_address(self) -> None:
        def assert_is_expected(address_input: AddressInput, expected: Address) -> None:
            assert self.request_single_product(Address, address_input) == expected

        self.create_file("a/b/c.txt")
        assert_is_expected(
            AddressInput("a/b/c.txt"), Address("a/b", target_name=None, relative_file_path="c.txt")
        )
        assert_is_expected(
            AddressInput("a/b"), Address("a/b", target_name=None, relative_file_path=None)
        )

        assert_is_expected(
            AddressInput("a/b", target_component="c"), Address("a/b", target_name="c")
        )
        assert_is_expected(
            AddressInput("a/b/c.txt", target_component="c"),
            Address("a/b", relative_file_path="c.txt", target_name="c"),
        )

        # Top-level addresses will not have a path_component, unless they are a file address.
        self.create_file("f.txt")
        assert_is_expected(
            AddressInput("f.txt", target_component="original"),
            Address("", relative_file_path="f.txt", target_name="original"),
        )
        assert_is_expected(AddressInput("", target_component="t"), Address("", target_name="t"))

        with pytest.raises(ExecutionError) as exc:
            self.request_single_product(Address, AddressInput("a/b/fake"))
        assert "'a/b/fake' does not exist on disk" in str(exc.value)

    def test_target_adaptor_parsed_correctly(self) -> None:
        self.add_to_build_file(
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
        addr = Address.parse("helloworld")
        target_adaptor = self.request_single_product(
            TargetAdaptor, Params(addr, create_options_bootstrapper())
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

    def test_target_adaptor_not_found(self) -> None:
        bootstrapper = create_options_bootstrapper()
        with pytest.raises(ExecutionError) as exc:
            self.request_single_product(TargetAdaptor, Params(Address("helloworld"), bootstrapper))
        assert "Directory \\'helloworld\\' does not contain any BUILD files" in str(exc)

        self.add_to_build_file("helloworld", "mock_tgt(name='other_tgt')")
        expected_rx_str = re.escape(
            "'helloworld' was not found in namespace 'helloworld'. Did you mean one of:\n  :other_tgt"
        )
        with pytest.raises(ExecutionError, match=expected_rx_str):
            self.request_single_product(TargetAdaptor, Params(Address("helloworld"), bootstrapper))

    def test_build_file_address(self) -> None:
        self.create_file("helloworld/BUILD.ext", "mock_tgt()")
        bootstrapper = create_options_bootstrapper()

        def assert_bfa_resolved(address: Address) -> None:
            expected_bfa = BuildFileAddress(rel_path="helloworld/BUILD.ext", address=address)
            bfa = self.request_single_product(BuildFileAddress, Params(address, bootstrapper))
            assert bfa == expected_bfa
            bfas = self.request_single_product(
                BuildFileAddresses, Params(Addresses([address]), bootstrapper)
            )
            assert bfas == BuildFileAddresses([bfa])

        assert_bfa_resolved(Address("helloworld"))
        # File addresses should use their base target to find the BUILD file.
        assert_bfa_resolved(Address("helloworld", relative_file_path="f.txt"))
