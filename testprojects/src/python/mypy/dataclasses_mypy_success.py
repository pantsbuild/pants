# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass


@dataclass(frozen=True)
class DC:
  a: int


# Running mypy on this is expected to pass, as it should deduce the right __init__() params from the
# @dataclass declaration.
x = DC(3)
