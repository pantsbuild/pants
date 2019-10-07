# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import List


def properly_typed(x: int, y: List[str]) -> float:
    if x > 0:
        return 1.0
    if y:
        return 0.0
    return -1.0


returned_float = properly_typed(x="bad!", y={"should_be_a_list"})
print(f"{returned_float.upper()}")
