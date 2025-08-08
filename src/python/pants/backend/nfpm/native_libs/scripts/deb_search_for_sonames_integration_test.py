# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from .deb_search_for_sonames import deb_search_for_sonames


@pytest.mark.parametrize(
    "distro,distro_codename,debian_arch,sonames,expected",
    (
        pytest.param("debian", "bookworm", "amd64", ("libldap-2.5.so.0",), {"libldap-2.5-0"}),
        pytest.param("debian", "bookworm", "arm64", ("libldap-2.5.so.0",), {"libldap-2.5-0"}),
        pytest.param("ubuntu", "jammy", "amd64", ("libldap-2.5.so.0",), {"libldap-2.5-0"}),
        pytest.param("ubuntu", "jammy", "arm64", ("libldap-2.5.so.0",), {"libldap-2.5-0"}),
        pytest.param(
            "ubuntu", "foobar", "amd64", ("libldap-2.5.so.0",), set(), id="bad distro_codename"
        ),
        pytest.param(
            "ubuntu", "jammy", "foobar", ("libldap-2.5.so.0",), set(), id="bad debian_arch"
        ),
        pytest.param("ubuntu", "jammy", "amd64", ("foobarbaz-9.9.so.9",), set(), id="bad soname"),
        pytest.param(
            "ubuntu",
            "jammy",
            "amd64",
            ("libcurl.so",),  # the search api returns a table like this:
            # ------------------------------------------- | ----------------------------------------------------------- |
            # File                                        | Packages                                                    |
            # ------------------------------------------- | ----------------------------------------------------------- |
            # /usr/lib/cupt4-2/downloadmethods/libcurl.so | libcupt4-2-downloadmethod-curl                              |
            # /usr/lib/x86_64-linux-gnu/libcurl.so        | libcurl4-gnutls-dev, libcurl4-nss-dev, libcurl4-openssl-dev |
            # ------------------------------------------- | ----------------------------------------------------------- |
            {
                "libcupt4-2-downloadmethod-curl",
                "libcurl4-gnutls-dev",
                "libcurl4-nss-dev",
                "libcurl4-openssl-dev",
            },
            id="same file in multiple packages",
        ),
    ),
)
async def test_deb_search_for_sonames(
    distro: str,
    distro_codename: str,
    debian_arch: str,
    sonames: tuple[str, ...],
    expected: set[str],
):
    result = await deb_search_for_sonames(distro, distro_codename, debian_arch, sonames)
    assert result == expected
