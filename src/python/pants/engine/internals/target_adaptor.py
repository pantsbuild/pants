# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any

from typing_extensions import final

from pants.build_graph.address import Address
from pants.engine.engine_aware import EngineAwareParameter


@dataclass(frozen=True)
class TextBlock:
    """Block of lines in a file."""

    start: int
    count: int


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

    __slots__ = ("type_alias", "name", "kwargs", "description_of_origin")

    def __init__(
        self,
        type_alias: str,
        name: str | None,
        __description_of_origin__: str,
        **kwargs: Any,
    ) -> None:
        self.type_alias = type_alias
        self.name = name
        self.kwargs = kwargs
        self.description_of_origin = __description_of_origin__

    def __repr__(self) -> str:
        return f"TargetAdaptor(type_alias={self.type_alias}, name={self.name}, origin={self.description_of_origin})"

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
