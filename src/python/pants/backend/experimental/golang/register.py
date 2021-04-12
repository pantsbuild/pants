# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.experimental.golang import build, distribution, fmt, gofmt
from pants.backend.experimental.golang.target_types import GoBinary, GoPackage
from pants.engine.rules import collect_rules


def target_types():
    return [GoBinary, GoPackage]


def rules():
    return [
        *collect_rules(),
        *build.rules(),
        *distribution.rules(),
        *fmt.rules(),
        *gofmt.rules(),
    ]
