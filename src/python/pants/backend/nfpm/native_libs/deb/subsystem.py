# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.nfpm.native_libs.deb._constants import DEFAULT_DEB_DISTRO_PACKAGE_SEARCH_URLS
from pants.option.option_types import DictOption
from pants.option.subsystem import Subsystem
from pants.util.strutil import help_text


class DebSubsystem(Subsystem):
    options_scope = "deb"  # not "debian" to avoid conflicting with debian backend
    help = "Options for deb scripts in the nfpm.native_libs backend."

    distro_package_search_urls = DictOption[str](
        default=DEFAULT_DEB_DISTRO_PACKAGE_SEARCH_URLS,
        help=help_text(
            """
            A mapping of distro names to package search URLs.

            This is used when inspecting packaged native_libs to inject nfpm package deps.

            The key is a distro name and should be lowercase.

            Each value is a fully-qualified URL with scheme (`https://`), domain, and path
            (path is typically `/search`). The URL must point to an instance of the debian
            package search service, returning the API results in HTML format.
            """
        ),
        advanced=True,
    )
