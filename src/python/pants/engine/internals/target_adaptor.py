# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Any

from typing_extensions import final


@final
class TargetAdaptor:
    """A light-weight object to store target information before being converted into the Target
    API."""

    def __init__(self, type_alias: str, name: str, **kwargs: Any) -> None:
        self.type_alias = type_alias
        self.name = name
        self.kwargs = kwargs

    def __repr__(self) -> str:
        return f"TargetAdaptor(type_alias={self.type_alias}, name={self.name})"

    def __eq__(self, other: Any | TargetAdaptor) -> bool:
        if not isinstance(other, TargetAdaptor):
            return NotImplemented
        return (
            self.type_alias == other.type_alias
            and self.name == other.name
            and self.kwargs == other.kwargs
        )
