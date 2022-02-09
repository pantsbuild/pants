# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from __future__ import annotations

import os
import shutil

from pants.version import MAJOR_MINOR, PANTS_SEMVER


# NB: This is not memoized because that would cause Pants to not pick up terminal resizing when
# using pantsd.
def terminal_width(*, fallback: int = 96, padding: int = 2) -> int:
    return shutil.get_terminal_size(fallback=(fallback, 24)).columns - padding


def doc_url(slug: str) -> str:
    return f"https://www.pantsbuild.org/v{MAJOR_MINOR}/docs/{slug}"


def git_url(fp: str) -> str:
    """Link to code in pantsbuild/pants."""
    return f"https://github.com/pantsbuild/pants/blob/release_{PANTS_SEMVER}/{fp}"


def bin_name() -> str:
    """Return the Pants binary name, e.g. './pants'."""
    try:
        os.environ["PANTS_BIN_NAME"]
    except KeyError:
        raise AssertionError(
            "Expected 'PANTS_BIN_NAME' to be set. Please file a bug at "
            "https://github.com/pantsbuild/pants/issues with your Pants version and stack trace."
        )
