# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.experimental.python import user_lockfiles
from pants.backend.python.goals import lockfile, publish
from pants.backend.python.subsystems import twine
from pants.backend.python.util_rules import pex


def rules():
    return (
        *lockfile.rules(),
        *pex.rules(),
        *publish.rules(),
        *twine.rules(),
        *user_lockfiles.rules(),
    )
