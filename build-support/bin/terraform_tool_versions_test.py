#!/usr/bin/env python3
# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest
from terraform_tool_versions import (
    Link,
    VersionHash,
    get_info_for_version,
    is_prerelease,
    parse_download_url,
    parse_sha256sums_file,
)


def test_parse_download_url():
    expected_version = "1.2.3"
    expected_platform = "linux_amd64"

    url = f"https://releases.hashicorp.com/terraform/{expected_platform}/terraform_{expected_version}_{expected_platform}.zip"
    version, platform = parse_download_url(url)
    assert version == expected_version
    assert platform == expected_platform


def test_get_info_for_version():
    sha256sums_link = Link(
        "terraform_1.2.6_SHA256SUMS",
        "https://releases.hashicorp.com/terraform/1.2.6/terraform_1.2.6_SHA256SUMS",
    )
    keyed_signature_link = Link(
        "terraform_1.2.6_SHA256SUMS.72D7468F.sig",
        "https://releases.hashicorp.com/terraform/1.2.6/terraform_1.2.6_SHA256SUMS.72D7468F.sig",
    )
    signature_link = Link(
        "terraform_1.2.6_SHA256SUMS.sig",
        "https://releases.hashicorp.com/terraform/1.2.6/terraform_1.2.6_SHA256SUMS.sig",
    )

    links = [
        sha256sums_link,
        keyed_signature_link,
        signature_link,
        Link(
            "terraform_1.2.6_darwin_amd64.zip",
            "https://releases.hashicorp.com/terraform/1.2.6/terraform_1.2.6_darwin_amd64.zip",
        ),
        Link(
            "terraform_1.2.6_darwin_arm64.zip",
            "https://releases.hashicorp.com/terraform/1.2.6/terraform_1.2.6_darwin_arm64.zip",
        ),
    ]

    result = get_info_for_version(links)

    assert result.signature_link == signature_link
    assert result.sha256sums_link == sha256sums_link
    assert len(result.binary_links) == 2
    assert keyed_signature_link not in result.binary_links


sha256sums_file = """\
94d1efad05a06c879b9c1afc8a6f7acb2532d33864225605fc766ecdd58d9888  terraform_1.2.6_darwin_amd64.zip
452675f91cfe955a95708697a739d9b114c39ff566da7d9b31489064ceaaf66a  terraform_1.2.6_darwin_arm64.zip
1bedf7564838493f7cd9cb72544996c27dcfbbae9bf5436ef334e865515e6f24  terraform_1.2.6_freebsd_386.zip
353b21367e5eb9804cfba3140e786c5c149c10098b2a54aa5be3ec30c8425be0  terraform_1.2.6_freebsd_amd64.zip
47aa169b52c4b566f37d9f39f41cfc34ee2e4152641a9109c2767f48007b2457  terraform_1.2.6_freebsd_arm.zip
3d6c0dc8836dbfcfc82e6ba69891f21bfad6a09116e6ddf7a14187b8ee0acce5  terraform_1.2.6_linux_386.zip
9fd445e7a191317dcfc99d012ab632f2cc01f12af14a44dfbaba82e0f9680365  terraform_1.2.6_linux_amd64.zip
322755d11f0da11169cdb234af74ada5599046c698dccc125859505f85da2a20  terraform_1.2.6_linux_arm64.zip
ed49a5422ca51cbc90472a754979f9bbba5f0c39f6a0abe570e525bbae4e6540  terraform_1.2.6_linux_arm.zip
426d39f1b87bf5dbda3ebb4585483288dba09c36731d5cae146f29df0119036c  terraform_1.2.6_openbsd_386.zip
5b0c59ffe5f83363b20f74df428490b95ff81f53348f8c8394519768085f3eef  terraform_1.2.6_openbsd_amd64.zip
64e70edf5af0e77f54d111ae318282aebcdaa33e8dd545b93881fd421dc4d982  terraform_1.2.6_solaris_amd64.zip
f26acca0060c42c0e6fb81d268fbf4ab9baac3d5f34c8263ecdb48c0a78f905b  terraform_1.2.6_windows_386.zip
1e3c884cf32879646f97b8b6a253686710eb6e445d44097580a27511a49db88b  terraform_1.2.6_windows_amd64.zip"""

sha256sums_classes = [
    VersionHash(
        filename="terraform_1.2.6_darwin_amd64.zip",
        sha256sum="94d1efad05a06c879b9c1afc8a6f7acb2532d33864225605fc766ecdd58d9888",
    ),
    VersionHash(
        filename="terraform_1.2.6_darwin_arm64.zip",
        sha256sum="452675f91cfe955a95708697a739d9b114c39ff566da7d9b31489064ceaaf66a",
    ),
    VersionHash(
        filename="terraform_1.2.6_freebsd_386.zip",
        sha256sum="1bedf7564838493f7cd9cb72544996c27dcfbbae9bf5436ef334e865515e6f24",
    ),
    VersionHash(
        filename="terraform_1.2.6_freebsd_amd64.zip",
        sha256sum="353b21367e5eb9804cfba3140e786c5c149c10098b2a54aa5be3ec30c8425be0",
    ),
    VersionHash(
        filename="terraform_1.2.6_freebsd_arm.zip",
        sha256sum="47aa169b52c4b566f37d9f39f41cfc34ee2e4152641a9109c2767f48007b2457",
    ),
    VersionHash(
        filename="terraform_1.2.6_linux_386.zip",
        sha256sum="3d6c0dc8836dbfcfc82e6ba69891f21bfad6a09116e6ddf7a14187b8ee0acce5",
    ),
    VersionHash(
        filename="terraform_1.2.6_linux_amd64.zip",
        sha256sum="9fd445e7a191317dcfc99d012ab632f2cc01f12af14a44dfbaba82e0f9680365",
    ),
    VersionHash(
        filename="terraform_1.2.6_linux_arm64.zip",
        sha256sum="322755d11f0da11169cdb234af74ada5599046c698dccc125859505f85da2a20",
    ),
    VersionHash(
        filename="terraform_1.2.6_linux_arm.zip",
        sha256sum="ed49a5422ca51cbc90472a754979f9bbba5f0c39f6a0abe570e525bbae4e6540",
    ),
    VersionHash(
        filename="terraform_1.2.6_openbsd_386.zip",
        sha256sum="426d39f1b87bf5dbda3ebb4585483288dba09c36731d5cae146f29df0119036c",
    ),
    VersionHash(
        filename="terraform_1.2.6_openbsd_amd64.zip",
        sha256sum="5b0c59ffe5f83363b20f74df428490b95ff81f53348f8c8394519768085f3eef",
    ),
    VersionHash(
        filename="terraform_1.2.6_solaris_amd64.zip",
        sha256sum="64e70edf5af0e77f54d111ae318282aebcdaa33e8dd545b93881fd421dc4d982",
    ),
    VersionHash(
        filename="terraform_1.2.6_windows_386.zip",
        sha256sum="f26acca0060c42c0e6fb81d268fbf4ab9baac3d5f34c8263ecdb48c0a78f905b",
    ),
    VersionHash(
        filename="terraform_1.2.6_windows_amd64.zip",
        sha256sum="1e3c884cf32879646f97b8b6a253686710eb6e445d44097580a27511a49db88b",
    ),
]


def test_parse_sha256sums_file():
    sha256sums = parse_sha256sums_file(sha256sums_file)
    assert sha256sums == sha256sums_classes


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("1.2.3", False),
        ("1.2.3-rc1", True),
        ("1.2.3-beta1", True),
        ("1.2.3-alpha20220413", True),
    ],
    ids=["standard_release", "rc", "beta", "alpha"],
)
def test_is_prerelease(version, expected):
    assert is_prerelease("terraform_" + version) == expected
