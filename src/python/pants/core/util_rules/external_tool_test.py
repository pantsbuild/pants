# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.core.util_rules.external_tool import (
    ExternalTool,
    ExternalToolError,
    ExternalToolRequest,
    UnknownVersion,
)
from pants.engine.fs import Digest, UrlToFetch
from pants.engine.platform import Platform


class FooBar(ExternalTool):
    name = "foobar"
    default_version = "3.4.7"
    default_known_versions = [
        "3.2.0|darwin   |1102324cdaacd589e50b8b7770595f220f54e18a1d76ee3c445198f80ab865b8|123346",
        "3.2.0|linux_ppc|39e5d64b0f31117c94651c880d0a776159e49eab42b2066219569934b936a5e7|124443",
        "3.2.0|linux    |c0c667fb679a8221bed01bffeed1f80727c6c7827d0cbd8f162195efb12df9e4|121212",
        "3.4.7|darwin   |9d0e18cd74b918c7b3edd0203e75569e0c8caecb1367b3be409b45e28514f5be|123321",
        "3.4.7|linux    |a019dfc4b32d63c1392aa264aed2253c1e0c2fb09216f8e2cc269bbfb8bb49b5|134213",
    ]

    @classmethod
    def generate_url(cls, plat: Platform, version: str) -> str:
        if plat == Platform.darwin:
            plat_str = "osx-x86_64"
        elif plat == Platform.linux:
            plat_str = "linux-x86_64"
        else:
            raise ExternalToolError()
        return f"https://foobar.org/bin/v{version}/foobar-{version}-{plat_str}.tgz"

    @classmethod
    def generate_exe(cls, plat: Platform, version: str) -> str:
        return f"foobar-{version}/bin/foobar"


def test_generate_request() -> None:
    def do_test(
        expected_url: str, expected_length: int, expected_sha256: str, plat: Platform, version: str
    ) -> None:
        assert ExternalToolRequest(
            UrlToFetch(url=expected_url, digest=Digest(expected_sha256, expected_length)),
            f"foobar-{version}/bin/foobar",
        ) == FooBar.generate_request(plat, version, FooBar.default_known_versions)

    do_test(
        "https://foobar.org/bin/v3.2.0/foobar-3.2.0-osx-x86_64.tgz",
        123346,
        "1102324cdaacd589e50b8b7770595f220f54e18a1d76ee3c445198f80ab865b8",
        Platform.darwin,
        "3.2.0",
    )
    do_test(
        "https://foobar.org/bin/v3.4.7/foobar-3.4.7-linux-x86_64.tgz",
        134213,
        "a019dfc4b32d63c1392aa264aed2253c1e0c2fb09216f8e2cc269bbfb8bb49b5",
        Platform.linux,
        "3.4.7",
    )

    with pytest.raises(UnknownVersion):
        FooBar.generate_request(Platform.darwin, "9.9.9", FooBar.default_known_versions)


# Delete this test after ExternalTool.get_default_versions_and_digests() is removed.
def test_get_default_versions_and_digests() -> None:
    assert {
        "darwin": (
            "3.4.7",
            "9d0e18cd74b918c7b3edd0203e75569e0c8caecb1367b3be409b45e28514f5be",
            123321,
        ),
        "linux": (
            "3.4.7",
            "a019dfc4b32d63c1392aa264aed2253c1e0c2fb09216f8e2cc269bbfb8bb49b5",
            134213,
        ),
    } == FooBar.get_default_versions_and_digests()
