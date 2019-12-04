# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class JvmOptions:
  """VM Options for executing a JVM process."""
  options: Tuple[str, ...]
