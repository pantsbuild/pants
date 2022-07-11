# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from abc import ABCMeta
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any, Generic, Iterable, Iterator, Mapping, TypeVar

from pants.util.frozendict import FrozenDict
from pants.util.meta import frozen_after_init


@dataclass(unsafe_hash=True)
@frozen_after_init
class YamlPath:
    """Simple implementation of YAML paths using `/` syntax and being the single slash the path to
    the root."""

    _elements: tuple[str, ...]
    absolute: bool

    def __init__(self, elements: Iterable[str], *, absolute: bool) -> None:
        self._elements = tuple(elements)
        self.absolute = absolute

    @classmethod
    def parse(cls, path: str) -> YamlPath:
        """Parses a YAML path."""

        is_absolute = path.startswith("/")
        return cls([elem for elem in path.split("/") if elem], absolute=is_absolute)

    @classmethod
    def root(cls) -> YamlPath:
        """Returns a YamlPath that represents the root element."""

        return cls([], absolute=True)

    @property
    def parent(self) -> YamlPath | None:
        """Returns the path to the parent element unless this path is already the root."""

        if not self.is_root:
            return YamlPath(self._elements[:-1], absolute=self.absolute)
        return None

    @property
    def current(self) -> str:
        """Returns the name of the current element referenced by this path.

        The root element will return the empty string.
        """

        if self.is_root:
            return ""
        return self._elements[len(self._elements) - 1]

    @property
    def is_root(self) -> bool:
        """Returns `True` if this path represents the root element."""

        return len(self._elements) == 0

    @property
    def is_index(self) -> bool:
        """Returns `True` if this path is referencing an indexed item inside an array."""

        try:
            int(self.current)
            return True
        except ValueError:
            return False

    def __add__(self, other: YamlPath) -> YamlPath:
        if other.absolute:
            raise ValueError("Can not append an absolute path to another path.")
        return YamlPath(self._elements + other._elements, absolute=self.absolute)

    def __truediv__(self, other: str) -> YamlPath:
        return self + YamlPath.parse(other)

    def __iter__(self):
        return iter(self._elements)

    def __str__(self) -> str:
        path = "/".join(self._elements)
        if self.absolute:
            path = f"/{path}"
        return path


@dataclass(frozen=True)
class YamlElement(metaclass=ABCMeta):
    """Abstract base class for elements read from YAML files.

    `element_path` represents the location inside the YAML file where this element is.
    """

    element_path: YamlPath


T = TypeVar("T")


@dataclass(unsafe_hash=True)
@frozen_after_init
class YamlElements(Generic[T]):
    """Collection of values that are indexed by a file name and a YAML path inside the given
    file."""

    _data: FrozenDict[PurePath, FrozenDict[YamlPath, T]]

    def __init__(self, data: Mapping[PurePath, Mapping[YamlPath, T]] = {}) -> None:
        self._data = FrozenDict(
            {filename: FrozenDict(mapping) for filename, mapping in data.items() if mapping}
        )

    def items(self) -> Iterator[tuple[PurePath, YamlPath, T]]:
        for filename, path_mapping in self._data.items():
            for path, value in path_mapping.items():
                yield filename, path, value

    def file_paths(self) -> Iterable[PurePath]:
        return self._data.keys()

    def yaml_items(self, path: PurePath) -> Iterable[tuple[YamlPath, T]]:
        return self._data.get(path, {}).items()

    def values(self) -> Iterator[T]:
        for _, _, value in self.items():
            yield value


def _to_snake_case(str: str) -> str:
    """Translates an camel-case or kebab-case identifier by a snake-case one."""
    base_string = str.replace("-", "_")

    result = ""
    idx = 0
    for c in base_string:
        char_to_add = c
        if char_to_add.isupper():
            char_to_add = c.lower()
            if idx > 0:
                result += "_"
        result += char_to_add
        idx += 1

    return result


def snake_case_attr_dict(d: Mapping[str, Any]) -> dict[str, Any]:
    """Transforms all keys in the given mapping to be snake-case."""
    return {_to_snake_case(name): value for name, value in d.items()}
