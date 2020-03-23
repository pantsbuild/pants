# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import List


def properly_typed(x: int, y: List[str]) -> float:
    if x > 0:
        return 1.0
    if y:
        return 0.0
    return -1.0


returned_float = properly_typed(x=0, y=["test"])
print(f"{returned_float * 2.3}")
