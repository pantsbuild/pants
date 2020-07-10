# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

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

    def _key(self):
        def hashable(value):
            if isinstance(value, dict):
                return tuple((k, hashable(v)) for k, v in value.items())
            if isinstance(value, list):
                return tuple(hashable(v) for v in value)
            if isinstance(value, set):
                return tuple(sorted(hashable(v) for v in value))
            return value

        return (self.type_alias, self.name, *sorted(hashable(self.kwargs)))

    def __hash__(self):
        return hash(self._key())

    def __eq__(self, other):
        if not isinstance(other, TargetAdaptor):
            return NotImplemented
        return self._key() == other._key()

    def __repr__(self):
        return f"TargetAdaptor(type_alias={self.type_alias}, name={self.name})"
