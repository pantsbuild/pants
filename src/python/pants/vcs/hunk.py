# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from dataclasses import dataclass

from pants.engine.collection import Collection


@dataclass(frozen=True)
class TextBlock:
    """Block of lines in a file.

    Lines are 1 indexed, `start` is inclusive.

    TextBlock is used as a part of unified diff hunk, thus it can be empty,
    i.e. count can be equeal to 0.
    """

    start: int
    count: int

    def __init__(self, start: int, count: int):
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "count", count)

        self.__post_init__()

    def __post_init__(self):
        if self.count < 0:
            raise ValueError(f"{self.count=} can't be negative")

    @property
    def end(self) -> int:
        return self.start + self.count


class TextBlocks(Collection[TextBlock]):
    pass


@dataclass(frozen=True)
class Hunk:
    """Hunk of difference in unified format.

    https://www.gnu.org/software/diffutils/manual/html_node/Detailed-Unified.html
    """

    left: TextBlock
    right: TextBlock
