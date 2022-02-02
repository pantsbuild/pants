# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.packaging.pyoxidizer import subsystem
from pants.backend.python.packaging.pyoxidizer.rules import rules as pyoxidizer_rules
from pants.backend.python.packaging.pyoxidizer.target_types import PyOxidizerTarget


def rules():
    return [*pyoxidizer_rules(), *subsystem.rules()]


def target_types():
    return [PyOxidizerTarget]
