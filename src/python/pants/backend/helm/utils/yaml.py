# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from abc import ABCMeta
from collections import defaultdict
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any, Callable, Generic, Iterable, Iterator, Mapping, Optional, Type, TypeVar

from pants.engine.collection import Collection
from pants.util.frozendict import FrozenDict


@dataclass(unsafe_hash=True)
class YamlPath:
    """Simple implementation of YAML paths using `/` syntax and being the single slash the path to
    the root."""

    _elements: tuple[str, ...]
    _absolute: bool

    def __init__(self, elements: Iterable[str], *, absolute: bool) -> None:
        object.__setattr__(self, "_elements", tuple(elements))
        object.__setattr__(self, "_absolute", absolute)

        if len(self._elements) == 0 and not self._absolute:
            raise ValueError("Relative YAML paths with no elements are not allowed.")

    @classmethod
    def parse(cls, path: str) -> YamlPath:
        """Parses a YAML path."""

        is_absolute = path.startswith("/")
        return cls([elem for elem in path.split("/") if elem], absolute=is_absolute)

    @classmethod
    def root(cls) -> YamlPath:
        """Returns a YamlPath that represents the root element."""

        return cls([], absolute=True)

    @classmethod
    def index(cls, idx: int) -> YamlPath:
        """Returns a relative YamlPath for the index value provided."""

        return cls([str(idx)], absolute=False)

    @property
    def parent(self) -> YamlPath | None:
        """Returns the path to the parent element unless this path is already the root."""

        if not self.is_root:
            return YamlPath(self._elements[:-1], absolute=self._absolute)
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
    def is_absolute(self) -> bool:
        """Returns `True` if this is an absolute path."""

        return self._absolute

    @property
    def is_root(self) -> bool:
        """Returns `True` if this path represents the root element."""

        return len(self._elements) == 0 and self._absolute

    @property
    def is_index(self) -> bool:
        """Returns `True` if this path is referencing an indexed item inside an array."""

        try:
            int(self.current)
            return True
        except ValueError:
            return False

    def to_relative(self) -> YamlPath:
        """Transforms this YamlPath instance into a relative path."""

        if not self._absolute:
            return self
        return YamlPath(self._elements, absolute=False)

    def __truediv__(self, other: str | int | YamlPath) -> YamlPath:
        if isinstance(other, str):
            other_path = YamlPath.parse(other)
        elif isinstance(other, int):
            other_path = YamlPath.index(other)
        else:
            other_path = other

        if other_path._absolute:
            raise ValueError("Can not append an absolute path to another path.")

        return YamlPath(self._elements + other_path._elements, absolute=self._absolute)

    def __iter__(self):
        return iter(self._elements)

    def __str__(self) -> str:
        path = "/".join(self._elements)
        if self._absolute:
            path = f"/{path}"
        return path


@dataclass(frozen=True)
class YamlElement(metaclass=ABCMeta):
    """Abstract base class for elements read from YAML files.

    `element_path` represents the location inside the YAML file where this element is.
    """

    element_path: YamlPath


T = TypeVar("T")
R = TypeVar("R")


class MutableYamlIndex(Generic[T]):
    """Represents a mutable collection of items that is indexed by the following keys:

    - the relative path of the YAML file
    - the document index inside the YAML file
    - the YAML path of the item
    """

    _data: dict[PurePath, dict[int, dict[YamlPath, T]]]

    def __init__(self) -> None:
        self._data = defaultdict(dict)

    def insert(
        self, *, file_path: PurePath, yaml_path: YamlPath, item: T, document_index: int = 0
    ) -> None:
        """Inserts an item at the given position in the index."""

        doc_index = self._data[file_path].get(document_index, {})
        if not doc_index:
            self._data[file_path][document_index] = doc_index

        doc_index[yaml_path] = item

    def frozen(self) -> FrozenYamlIndex[T]:
        """Transforms this collection into a frozen (immutable) one."""

        return FrozenYamlIndex(self)


@dataclass(frozen=True)
class _YamlDocumentIndexNode(Generic[T]):
    """Helper node item for the `FrozenYamlIndex` type."""

    paths: FrozenDict[YamlPath, T]

    @classmethod
    def empty(cls: Type[_YamlDocumentIndexNode[T]]) -> _YamlDocumentIndexNode[T]:
        return cls(paths=FrozenDict())

    def to_json_dict(self) -> dict[str, dict[str, str]]:
        items_dict: dict[str, str] = {}
        for path, item in self.paths.items():
            items_dict[str(path)] = str(item)
        return {"paths": items_dict}


@dataclass(frozen=True)
class FrozenYamlIndex(Generic[T]):
    """Represents a frozen collection of items that is indexed by the following keys:

    - the relative path of the YAML file
    - the document index inside the YAML file
    - the YAML path of the item
    """

    _data: FrozenDict[PurePath, Collection[_YamlDocumentIndexNode[T]]]

    def __init__(self, other: MutableYamlIndex[T]) -> None:
        data: dict[PurePath, Collection[_YamlDocumentIndexNode[T]]] = {}
        for file_path, doc_index in other._data.items():
            max_index = max(doc_index.keys())
            doc_list: list[_YamlDocumentIndexNode[T]] = [_YamlDocumentIndexNode.empty()] * (
                max_index + 1
            )

            for idx, item_map in doc_index.items():
                doc_list[idx] = _YamlDocumentIndexNode(paths=FrozenDict(item_map))

            data[file_path] = Collection(doc_list)
        object.__setattr__(self, "_data", FrozenDict(data))

    def transform_values(self, func: Callable[[T], Optional[R]]) -> FrozenYamlIndex[R]:
        """Transforms the values of the given indexed collection into those that are returned from
        the received function.

        The items that map to `None` in the given function are not included in the result.

        This is a combination of the `map` and `filter` higher-order functions into one so
        both operations are performed in a single pass.
        """

        mutable_index: MutableYamlIndex[R] = MutableYamlIndex()
        for file_path, doc_index, yaml_path, item in self:
            new_item = func(item)
            if new_item is not None:
                mutable_index.insert(
                    file_path=file_path,
                    document_index=doc_index,
                    yaml_path=yaml_path,
                    item=new_item,
                )
        return mutable_index.frozen()

    def values(self) -> Iterator[T]:
        """Returns an iterator over the values of this index."""
        for _, _, _, item in self:
            yield item

    def to_json_dict(self) -> dict[str, Any]:
        """Transforms this collection into a JSON-like dictionary that can be dumped later."""

        result = {}
        for file_path, documents in self._data.items():
            result[str(file_path)] = [doc_idx.to_json_dict() for doc_idx in documents]
        return result

    def __iter__(self):
        for file_path, doc_indexes in self._data.items():
            for idx, doc_index in enumerate(doc_indexes):
                for yaml_path, item in doc_index.paths.items():
                    yield file_path, idx, yaml_path, item


def _to_snake_case(str: str) -> str:
    """Translates a camel-case or kebab-case identifier into a snake-case one."""

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
