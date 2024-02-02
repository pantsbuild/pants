# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.go import target_type_rules
from pants.backend.go.util_rules import (
    assembly,
    build_pkg,
    first_party_pkg,
    link,
    sdk,
    third_party_pkg,
    vendor,
)
from pants.backend.go.util_rules.vendor import (
    ParseVendorModulesMetadataRequest,
    ParseVendorModulesMetadataResult,
    VendoredModuleMetadata,
)
from pants.core.util_rules.archive import rules as archive_rules
from pants.engine.fs import rules as fs_rules
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *vendor.rules(),
            *first_party_pkg.rules(),
            *sdk.rules(),
            *third_party_pkg.rules(),
            *target_type_rules.rules(),
            *build_pkg.rules(),
            *link.rules(),
            *assembly.rules(),
            *fs_rules(),
            *archive_rules(),
            QueryRule(ParseVendorModulesMetadataResult, (ParseVendorModulesMetadataRequest,)),
        ]
    )
    rule_runner.set_options([], env_inherit=PYTHON_BOOTSTRAP_ENV)
    return rule_runner


def test_read_vendor_manifest(rule_runner: RuleRunner) -> None:
    snapshot = rule_runner.make_snapshot(
        {
            "module.txt": dedent(
                """\
            # golang.org/x/crypto v0.3.1-0.20221117191849-2c476679df9a
            ## explicit; go 1.17
            golang.org/x/crypto/chacha20
            golang.org/x/crypto/chacha20poly1305
            golang.org/x/crypto/cryptobyte
            golang.org/x/crypto/cryptobyte/asn1
            golang.org/x/crypto/hkdf
            golang.org/x/crypto/internal/alias
            golang.org/x/crypto/internal/poly1305
            # golang.org/x/net v0.2.1-0.20221117215542-ecf7fda6a59e
            ## explicit; go 1.17
            golang.org/x/net/dns/dnsmessage
            golang.org/x/net/http/httpguts
            golang.org/x/net/http/httpproxy
            golang.org/x/net/http2/hpack
            golang.org/x/net/idna
            golang.org/x/net/lif
            golang.org/x/net/nettest
            golang.org/x/net/route
            # golang.org/x/sys v0.2.1-0.20221110211117-d684c6f88669
            ## explicit; go 1.17
            golang.org/x/sys/cpu
            # golang.org/x/text v0.4.1-0.20221110184632-c8236a6712b1
            ## explicit; go 1.17
            golang.org/x/text/secure/bidirule
            golang.org/x/text/transform
            golang.org/x/text/unicode/bidi
            golang.org/x/text/unicode/norm
            """
            )
        }
    )
    result = rule_runner.request(
        ParseVendorModulesMetadataResult,
        [ParseVendorModulesMetadataRequest(digest=snapshot.digest, path="module.txt")],
    )
    assert result.modules == (
        VendoredModuleMetadata(
            module_import_path="golang.org/x/crypto",
            module_version="v0.3.1-0.20221117191849-2c476679df9a",
            package_import_paths=frozenset(
                [
                    "golang.org/x/crypto/chacha20",
                    "golang.org/x/crypto/chacha20poly1305",
                    "golang.org/x/crypto/cryptobyte",
                    "golang.org/x/crypto/cryptobyte/asn1",
                    "golang.org/x/crypto/hkdf",
                    "golang.org/x/crypto/internal/alias",
                    "golang.org/x/crypto/internal/poly1305",
                ]
            ),
            explicit=True,
            go_version="1.17",
        ),
        VendoredModuleMetadata(
            module_import_path="golang.org/x/net",
            module_version="v0.2.1-0.20221117215542-ecf7fda6a59e",
            package_import_paths=frozenset(
                [
                    "golang.org/x/net/dns/dnsmessage",
                    "golang.org/x/net/http/httpguts",
                    "golang.org/x/net/http/httpproxy",
                    "golang.org/x/net/http2/hpack",
                    "golang.org/x/net/idna",
                    "golang.org/x/net/lif",
                    "golang.org/x/net/nettest",
                    "golang.org/x/net/route",
                ]
            ),
            explicit=True,
            go_version="1.17",
        ),
        VendoredModuleMetadata(
            module_import_path="golang.org/x/sys",
            module_version="v0.2.1-0.20221110211117-d684c6f88669",
            package_import_paths=frozenset(
                [
                    "golang.org/x/sys/cpu",
                ]
            ),
            explicit=True,
            go_version="1.17",
        ),
        VendoredModuleMetadata(
            module_import_path="golang.org/x/text",
            module_version="v0.4.1-0.20221110184632-c8236a6712b1",
            package_import_paths=frozenset(
                [
                    "golang.org/x/text/secure/bidirule",
                    "golang.org/x/text/transform",
                    "golang.org/x/text/unicode/bidi",
                    "golang.org/x/text/unicode/norm",
                ]
            ),
            explicit=True,
            go_version="1.17",
        ),
    )
