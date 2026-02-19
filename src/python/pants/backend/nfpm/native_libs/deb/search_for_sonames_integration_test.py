# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Any

import pytest

from pants.backend.nfpm.native_libs.deb._constants import DEFAULT_DEB_DISTRO_PACKAGE_SEARCH_URLS
from pants.backend.nfpm.native_libs.deb.test_utils import TEST_CASES

# The relative import emphasizes that `search_for_sonames` is a standalone script that runs
# from a sandbox root (thus avoiding a dependency on the pants code structure).
from .search_for_sonames import deb_search_for_sonames


@pytest.mark.parametrize("distro,distro_codename,debian_arch,sonames,expected,_", TEST_CASES)
async def test_deb_search_for_sonames(
    distro: str,
    distro_codename: str,
    debian_arch: str,
    sonames: tuple[str, ...],
    expected: dict[str, dict[str, list[str]]],
    _: Any,  # unused. This is for the rule integration test.
):
    search_url = DEFAULT_DEB_DISTRO_PACKAGE_SEARCH_URLS[distro]
    result = await deb_search_for_sonames(search_url, distro_codename, debian_arch, sonames)
    assert result == expected
