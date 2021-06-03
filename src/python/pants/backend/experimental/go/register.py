# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.go import build, distribution
from pants.backend.go.target_types import GoBinary, GoPackage


def target_types():
    return [GoBinary, GoPackage]


def rules():
    return [*build.rules(), *distribution.rules()]
