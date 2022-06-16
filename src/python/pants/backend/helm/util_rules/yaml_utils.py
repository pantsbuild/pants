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
    _elements: tuple[str, ...]

    def __init__(self, elements: Iterable[str]) -> None:
        self._elements = tuple(elements)

    @classmethod
    def parse(cls, path: str) -> YamlPath:
        return cls([elem for elem in path.split("/") if elem])

    @classmethod
    def root(cls) -> YamlPath:
        return cls([])

    @property
    def parent(self) -> YamlPath:
        if not self.is_root:
            return YamlPath(self._elements[:-1])
        return self

    @property
    def current(self) -> str:
        if self.is_root:
            return ""
        return self._elements[len(self._elements) - 1]

    @property
    def is_root(self) -> bool:
        return len(self._elements) == 0

    @property
    def is_index(self) -> bool:
        try:
            int(self.current)
            return True
        except ValueError:
            return False

    def __add__(self, other: YamlPath) -> YamlPath:
        return YamlPath(self._elements + other._elements)

    def __truediv__(self, other: str) -> YamlPath:
        return YamlPath([*self._elements, *YamlPath.parse(other)._elements])

    def __iter__(self):
        return iter(self._elements)

    def __str__(self) -> str:
        return f"/{'/'.join(self._elements)}"


@dataclass(frozen=True)
class YamlElement(metaclass=ABCMeta):
    element_path: YamlPath


T = TypeVar("T")


@dataclass(unsafe_hash=True)
@frozen_after_init
class YamlElements(Generic[T]):
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
