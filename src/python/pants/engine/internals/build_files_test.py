# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re
import unittest
import unittest.mock
from textwrap import dedent
from typing import cast

import pytest

from pants.base.exceptions import ResolveError
from pants.base.project_tree import Dir
from pants.base.specs import AddressSpecs, SiblingAddresses, SingleAddress
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.engine.addresses import (
    Address,
    Addresses,
    AddressesWithOrigins,
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
from pants.engine.internals.mapper import AddressFamily, AddressMapper
from pants.engine.internals.parser import BuildFilePreludeSymbols, Parser, SymbolTable
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.internals.target_adaptor import TargetAdaptor
from pants.engine.rules import RootRule
from pants.engine.target import Target
from pants.testutil.engine.util import MockGet, run_rule
from pants.testutil.test_base import TestBase
from pants.util.frozendict import FrozenDict


def test_parse_address_family_empty() -> None:
    """Test that parsing an empty BUILD file results in an empty AddressFamily."""
    address_mapper = AddressMapper(parser=Parser(SymbolTable({}), BuildFileAliases()))
    af = run_rule(
        parse_address_family,
        rule_args=[address_mapper, BuildFilePreludeSymbols(FrozenDict()), Dir("/dev/null")],
        mock_gets=[
            MockGet(
                product_type=Snapshot,
                subject_type=PathGlobs,
                mock=lambda _: Snapshot(Digest("abc", 10), ("/dev/null/BUILD",), ()),
            ),
            MockGet(
                product_type=DigestContents,
                subject_type=Digest,
                mock=lambda _: DigestContents([FileContent(path="/dev/null/BUILD", content=b"")]),
            ),
        ],
    )
    assert len(af.name_to_target_adaptors) == 0


def resolve_addresses_with_origins_from_address_specs(
    address_specs: AddressSpecs, address_family: AddressFamily,
) -> AddressesWithOrigins:
    address_mapper = AddressMapper(Parser(SymbolTable({}), BuildFileAliases()))
    snapshot = Snapshot(Digest("xx", 2), ("root/BUILD",), ())
    addresses_with_origins = run_rule(
        addresses_with_origins_from_address_specs,
        rule_args=[address_mapper, address_specs],
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
    assert str(awo.address) == "root:root"
    assert awo.origin == address_spec


def test_address_specs_tag_filter() -> None:
    """Test that targets are filtered based on `tags`."""
    address_specs = AddressSpecs([SiblingAddresses("root")], tags=["+integration"])
    address_family = AddressFamily(
        "root",
        {
            "a": ("root/BUILD", TargetAdaptor(type_alias="", name="a")),
            "b": ("root/BUILD", TargetAdaptor(type_alias="", name="b", tags={"integration"})),
            "c": ("root/BUILD", TargetAdaptor(type_alias="", name="c", tags={"not_integration"})),
        },
    )

    addresses_with_origins = resolve_addresses_with_origins_from_address_specs(
        address_specs, address_family
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
    address_specs = AddressSpecs([SiblingAddresses("root")], exclude_patterns=tuple([".exclude*"]))
    address_family = AddressFamily(
        "root",
        {
            "exclude_me": ("root/BUILD", TargetAdaptor(type_alias="", name="exclude_me")),
            "not_me": ("root/BUILD", TargetAdaptor(type_alias="", name="not_me")),
        },
    )

    addresses_with_origins = resolve_addresses_with_origins_from_address_specs(
        address_specs, address_family
    )
    assert len(addresses_with_origins) == 1
    awo = addresses_with_origins[0]
    assert str(awo.address) == "root:not_me"
    assert awo.origin == SiblingAddresses("root")


def test_address_specs_exclude_pattern_with_single_address() -> None:
    """Test that single address targets are filtered based on exclude patterns."""
    address_specs = AddressSpecs(
        [SingleAddress("root", "not_me")], exclude_patterns=tuple(["root.*"])
    )
    address_family = AddressFamily(
        "root", {"not_me": ("root/BUILD", TargetAdaptor(type_alias="", name="not_me"))}
    )
    assert not resolve_addresses_with_origins_from_address_specs(address_specs, address_family)


def run_prelude_parsing_rule(prelude_content: str) -> BuildFilePreludeSymbols:
    address_mapper = unittest.mock.Mock()
    address_mapper.prelude_glob_patterns = ("prelude",)
    symbols = run_rule(
        evaluate_preludes,
        rule_args=[address_mapper],
        mock_gets=[
            MockGet(
                product_type=Snapshot,
                subject_type=PathGlobs,
                mock=lambda _: Snapshot(Digest("abc", 10), ("/dev/null/prelude",), ()),
            ),
            MockGet(
                product_type=DigestContents,
                subject_type=Digest,
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
        return (*super().rules(), RootRule(Addresses))

    def test_target_parsed_correctly(self) -> None:
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
        target_adaptor = self.request_single_product(TargetAdaptor, addr)
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

    def test_build_file_address(self) -> None:
        self.create_file("helloworld/BUILD.ext", "mock_tgt()")
        addr = Address.parse("helloworld")
        expected_bfa = BuildFileAddress(rel_path="helloworld/BUILD.ext", target_name="helloworld")
        bfa = self.request_single_product(BuildFileAddress, addr)
        assert bfa == expected_bfa
        bfas = self.request_single_product(BuildFileAddresses, Addresses([addr]))
        assert bfas == BuildFileAddresses([bfa])

    def test_build_file_address_generated_subtarget(self) -> None:
        self.create_file("helloworld/BUILD.ext", "mock_tgt(name='original')")
        addr = Address("helloworld", target_name="generated", generated_base_target_name="original")
        expected_bfa = BuildFileAddress(
            rel_path="helloworld/BUILD.ext",
            target_name="generated",
            generated_base_target_name="original",
        )
        bfa = self.request_single_product(BuildFileAddress, addr)
        assert bfa == expected_bfa
        bfas = self.request_single_product(BuildFileAddresses, Addresses([addr]))
        assert bfas == BuildFileAddresses([bfa])

    def test_address_not_found(self) -> None:
        with pytest.raises(ExecutionError) as exc:
            self.request_single_product(TargetAdaptor, Address.parse("helloworld"))
        assert "Directory \\'helloworld\\' does not contain any BUILD files" in str(exc)

        self.add_to_build_file("helloworld", "mock_tgt(name='other_tgt')")
        expected_rx_str = re.escape(
            "'helloworld' was not found in namespace 'helloworld'. Did you mean one of:\n  :other_tgt"
        )
        with pytest.raises(ExecutionError, match=expected_rx_str):
            self.request_single_product(TargetAdaptor, Address.parse("helloworld"))
