# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent
from typing import Iterable

import pytest

from pants.backend.codegen.thrift import thrift_parser
from pants.backend.codegen.thrift.target_types import ThriftSourceField
from pants.backend.codegen.thrift.thrift_parser import ParsedThrift, ParsedThriftRequest
from pants.engine.addresses import Address
from pants.testutil.rule_runner import QueryRule, RuleRunner


def parse(content: str, *, extra_namespace_directives: Iterable[str] = ()) -> ParsedThrift:
    rule_runner = RuleRunner(
        rules=[*thrift_parser.rules(), QueryRule(ParsedThrift, [ParsedThriftRequest])]
    )
    rule_runner.write_files({"f.thrift": content})
    return rule_runner.request(
        ParsedThrift,
        [
            ParsedThriftRequest(
                ThriftSourceField("f.thrift", Address("", target_name="t")),
                extra_namespace_directives=tuple(extra_namespace_directives),
            )
        ],
    )


def test_parse_thrift_imports() -> None:
    result = parse(
        dedent(
            """\
            include "double_quotes.thrift"
            include 'single_quotes.thrift'
            include 'mixed_quotes.thrift"
            include\t"tab.thrift"\t

            # Complex paths
            include "path/to_dir/f.thrift"
            include "path\\to_dir\\f.thrift"
            include "âčĘï.thrift"
            include "123.thrift"

            # Invalid includes
            include invalid.thrift
            ilude "invalid.thrift"
            include "invalid.trft"
            """
        )
    )
    assert set(result.imports) == {
        "double_quotes.thrift",
        "single_quotes.thrift",
        "mixed_quotes.thrift",
        "tab.thrift",
        "path/to_dir/f.thrift",
        "path\\to_dir\\f.thrift",
        "âčĘï.thrift",
        "123.thrift",
    }
    assert not result.namespaces


@pytest.mark.parametrize("namespace", ["my_mod", "path.to.my_mod", "path.to.âčĘï"])
def test_namespaces_valid(namespace: str) -> None:
    result = parse(
        dedent(
            f"""\
            namespace py {namespace}
            namespace java {namespace}
            """
        )
    )
    assert not result.imports
    assert dict(result.namespaces) == {"py": namespace, "java": namespace}


def test_namespaces_invalid() -> None:
    result = parse(
        dedent(
            """\
            namspc py invalid
            namespace âčĘï invalid
            """
        )
    )
    assert not result.imports
    assert not result.namespaces


def test_extra_namespace_directives() -> None:
    result = parse(
        dedent(
            """\
            #@namespace psd mynamespace
            """
        ),
        extra_namespace_directives=["#@namespace"],
    )
    assert not result.imports
    assert dict(result.namespaces) == {"psd": "mynamespace"}
