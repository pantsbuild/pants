# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any, Optional

from typing_extensions import final

from pants.build_graph.address import Address
from pants.engine.collection import Collection
from pants.engine.engine_aware import EngineAwareParameter
from pants.util.frozendict import FrozenDict


@dataclass(frozen=True)
class TextBlock:
    """Block of lines in a file.

    Lines are 1 indexed, `start` is inclusive, `end` is exclusive.
    """

    start: int
    end: int

    def __len__(self) -> int:
        return self.end - self.start

    def intersection(self, o: TextBlock) -> Optional[TextBlock]:
        """Returns the text block intersection or None if blocks are disjoint."""
        if self.end <= o.start:
            return None
        if o.end <= self.start:
            return None
        return TextBlock(
            start=max(self.start, o.start),
            end=min(self.end, o.end),
        )

    @classmethod
    def from_count(cls, start: int, count: int) -> TextBlock:
        """Convert (start, count) range to (start, end) range.

        Useful for unified diff conversion, see
        https://www.gnu.org/software/diffutils/manual/html_node/Detailed-Unified.html
        """
        return cls(start=start, end=start + count)


class TextBlocks(Collection[TextBlock]):
    pass


@dataclass(frozen=True)
class TargetAdaptorRequest(EngineAwareParameter):
    """Lookup the TargetAdaptor for an Address."""

    address: Address
    description_of_origin: str = dataclasses.field(hash=False, compare=False)

    def debug_hint(self) -> str:
        return self.address.spec


@final
class TargetAdaptor:
    """A light-weight object to store target information before being converted into the Target
    API."""

    __slots__ = ("type_alias", "name", "kwargs", "description_of_origin", "origin_text_blocks")

    def __init__(
        self,
        type_alias: str,
        name: str | None,
        __description_of_origin__: str,
        __origin_text_blocks__: FrozenDict[str, tuple[TextBlock, ...]] = FrozenDict(),
        **kwargs: Any,
    ) -> None:
        self.type_alias = type_alias
        self.name = name
        self.kwargs = kwargs
        self.description_of_origin = __description_of_origin__
        self.origin_text_blocks = __origin_text_blocks__

    def __repr__(self) -> str:
        maybe_blocks = f", {self.origin_text_blocks}" if self.origin_text_blocks else ""
        return f"TargetAdaptor(type_alias={self.type_alias}, name={self.name}, origin={self.description_of_origin}{maybe_blocks})"

    def __eq__(self, other: Any | TargetAdaptor) -> bool:
        if not isinstance(other, TargetAdaptor):
            return NotImplemented
        return (
            self.type_alias == other.type_alias
            and self.name == other.name
            and self.kwargs == other.kwargs
        )

    @property
    def name_explicitly_set(self) -> bool:
        return self.name is not None
