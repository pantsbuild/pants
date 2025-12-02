# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

"""Constants for use in rule code and script tests."""


DEFAULT_DEB_DISTRO_PACKAGE_SEARCH_URLS: dict[str, str] = {
    "debian": "https://packages.debian.org/search",
    "ubuntu": "https://packages.ubuntu.com/search",
}
