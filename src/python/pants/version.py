# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import pkgutil

from packaging.version import Version


# Set this env var to override the version pants reports. Useful for testing.
_PANTS_VERSION_OVERRIDE = '_PANTS_VERSION_OVERRIDE'


VERSION: str = (
  os.environ.get(_PANTS_VERSION_OVERRIDE) or
  pkgutil.get_data(__name__, 'VERSION').decode().strip()  # type: ignore
)


PANTS_SEMVER = Version(VERSION)
