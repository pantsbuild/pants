# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from typing import Any

from packaging.version import Version as _Version

import pants._version

# Generate a inferrable dependency on the `pants._version` package and its associated resources.
from pants.util.resources import read_resource


# Simple derived class to enable comparison with strings in BUILD files.
class Version(_Version):
    def __hash__(self):
        # This is required to be directly implemented because we implement __eq__,
        # see the docs for object.__hash__:
        # https://docs.python.org/3/reference/datamodel.html#object.__hash__
        return super().__hash__()

    def __eq__(self, other: Any):
        if isinstance(other, str):
            other = Version(other)
        return super().__eq__(other)

    def __ne__(self, other: Any):
        if isinstance(other, str):
            other = Version(other)
        return super().__ne__(other)

    def __lt__(self, other: Any):
        if isinstance(other, str):
            other = Version(other)
        return super().__lt__(other)

    def __le__(self, other: Any):
        if isinstance(other, str):
            other = Version(other)
        return super().__le__(other)

    def __gt__(self, other: Any):
        if isinstance(other, str):
            other = Version(other)
        return super().__gt__(other)

    def __ge__(self, other: Any):
        if isinstance(other, str):
            other = Version(other)
        return super().__ge__(other)


# Set this env var to override the version pants reports. Useful for testing.
# Do not change. (see below)
_PANTS_VERSION_OVERRIDE = "_PANTS_VERSION_OVERRIDE"


VERSION: str = (
    # Do not remove/change this env var without coordinating with `pantsbuild/scie-pants` as it is
    # being used when bootstrapping Pants with a released version.
    os.environ.get(_PANTS_VERSION_OVERRIDE)
    or
    # NB: We expect VERSION to always have an entry and want a runtime failure if this is false.
    # NB: Since "pants" is the namespace for multiple packages, we need to put VERSION underneath
    # the tree that only the `pantsbuild.pants` package owns. Hence `pants._version`.
    # Furthermore, we can't outright move the file there from its previous home of pants/VERSION, as
    # (as of the time of writing) the Pants shim expects it at pants/VERSION. So we symlink the new
    # home to the old home, knowing that Pants is symlink oblivious when collecting sources.
    read_resource(pants._version.__name__, "VERSION").decode().strip()
)

PANTS_SEMVER = Version(VERSION)

# E.g. 2.0 or 2.2.
MAJOR_MINOR = f"{PANTS_SEMVER.major}.{PANTS_SEMVER.minor}"
