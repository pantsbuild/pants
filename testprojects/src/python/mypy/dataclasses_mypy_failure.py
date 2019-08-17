# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass


@dataclass(frozen=True)
class DC:
  a: int


# Running mypy on this is expected to fail, because mypy should have deduced the constructor accepts
# exactly a single `int`, and the literal `"asdf"` should produce an easy-to-understand type check
# error when running mypy (not at runtime!).
x = DC("asdf")
