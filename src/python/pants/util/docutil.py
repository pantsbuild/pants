# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from __future__ import annotations

import shutil

from pants.engine.internals.native_engine import py_bin_name
from pants.version import MAJOR_MINOR, PANTS_SEMVER


# NB: This is not memoized because that would cause Pants to not pick up terminal resizing when
# using pantsd.
def terminal_width(*, fallback: int = 96, padding: int = 2) -> int:
    return shutil.get_terminal_size(fallback=(fallback, 24)).columns - padding


_VERSIONED_PREFIXES = ("docs/", "reference/")


def doc_url(path: str) -> str:
    """Return a URL to the specified `path` on the Pants website.

    The path should be the part of the URL after the domain, ignoring the version, e.g.:

    - to link to https://www.pantsbuild.org/community/getting-help, pass `"/community/getting-help"`

    - to link to the current version of
      https://www.pantsbuild.org/2.19/docs/python/overview/enabling-python-support, pass
      `"docs/python/overview/enabling-python-support"`
    """
    versioned = any(path.startswith(prefix) for prefix in _VERSIONED_PREFIXES)
    version_info = f"{MAJOR_MINOR}/" if versioned else ""
    return f"https://www.pantsbuild.org/{version_info}{path}"


def git_url(fp: str) -> str:
    """Link to code in pantsbuild/pants."""
    return f"https://github.com/pantsbuild/pants/blob/release_{PANTS_SEMVER}/{fp}"


def bin_name() -> str:
    """Return the Pants binary name, e.g. 'pants'.

    Can be configured with the pants_bin_name option.
    """
    return py_bin_name()
