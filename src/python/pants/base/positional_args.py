# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Tuple

from dataclasses import dataclass


@dataclass(frozen=True)
class PositionalArgs:
  """The positional args provided to a pants run."""
  args: Tuple[str]
