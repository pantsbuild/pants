# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.goals import publish
from pants.backend.python.subsystems import twine
from pants.backend.python.util_rules import pex


def rules():
    return (*pex.rules(), *publish.rules(), *twine.rules())
