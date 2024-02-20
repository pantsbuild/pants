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


def doc_url(path: str, versioned: bool = True) -> str:
    """Return a URL to the specified `path` on the Pants website.

    Most URLs are associated with a particular pants version (e.g. docs for a backend), indicated
    with `versioned == True`, while some are ever-green and unversioned (e.g. info about the project
    governance).
    """
    version_info = f"{MAJOR_MINOR}/" if versioned else ""
    return f"https://www.pantsbuild.org/{version_info}{path}"


def git_url(fp: str) -> str:
    """Link to code in pantsbuild/pants."""
    return f"https://github.com/pantsbuild/pants/blob/release_{PANTS_SEMVER}/{fp}"


def bin_name() -> str:
    """Return the Pants binary name, e.g. './pants'."""
    # NB: This will be called at import-time in several files to define static help strings
    # (e.g. "help=f'run `{bin_name()} fmt`").
    #
    # Ideally, we'd assert this is set unconditionally before Pants imports any of the files which
    # use it, to give us complete confidence we won't be returning "./pants" in our help strings.
    #
    # However, this assumption really breaks down when we go to test pants (or a plugin author goes
    # to test their plugin). Therefore we give a fallback and have integration test(s) to assert
    # we've set this at the right point in time.
    #
    # Note that __PANTS_BIN_NAME is set in options_bootstrapper.py based on the value of the
    # pants_bin_name global option, so you cannot naively modify this by setting __PANTS_BIN_NAME
    # externally. You must set that option value in one of the usual ways.
    return os.environ.get("__PANTS_BIN_NAME", "./pants")  # noqa: PANTSBIN
