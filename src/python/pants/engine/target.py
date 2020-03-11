# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar, Iterable, List, Optional, Type, Union

from pants.engine.rules import UnionRule, union
from pants.util.collections import ensure_str_list
from pants.util.memo import memoized_property
from pants.util.meta import classproperty


@dataclass(frozen=True)
class Field(ABC):
    unhydrated: Any
    alias: ClassVar[str]

    @abstractmethod
    @memoized_property
    def hydrated(self) -> Any:
        """Validate and hydrate self.unhydrated into a value usable by downstream rules.

        All validation and hydration should happen here, such as converting a field that might be
        a single string or a list of strings to always being a list of strings.

        This property is memoized because hydration and validation can often be costly. This
        hydration will only happen when a downstream rule explicitly requests this field.
        """


class Target(ABC):
    @classproperty
    @abstractmethod
    def field_type(cls) -> Type:
        """This is used to tell the engine what typed fields the target has.

        For example, if you have a PythonLibraryTarget, you will create a corresponding
        PythonLibraryField class, which is annotated with `@union`. Then, you would set
        PythonLibraryTarget.field_type to PythonLibraryTarget. Finally, in the file's rules()
        function, you'd register a UnionRule(PythonLibraryField, MyField) for every field belonging
        to that target type.

            @union
            class PythonLibraryField:
                pass


            class PythonLibraryTarget:
                field_type = PythonLibraryTarget


            def rules():
                return [
                    UnionRule(PythonLibraryField, Sources),
                    UnionRules(PythonLibraryField, Compatibility),
                    ...
                ]
        """

    def get(self, field: Type[Field]) -> Field:
        pass


@dataclass(frozen=True)
class Sources(Field):
    unhydrated: Optional[Iterable[str]] = None
    alias: ClassVar[str] = "sources"

    # TODO: this needs to call the engine. How could we do that?
    #  Async property and `await my_target.sources`?
    @memoized_property
    def hydrated(self):
        return self.unhydrated


@dataclass(frozen=True)
class BinarySources(Sources):

    @memoized_property
    def hydrated(self):
        if self.unhydrated is not None and len(list(self.unhydrated)) not in [0, 1]:
            raise ValueError("TODO")
        return super().hydrated


@dataclass(frozen=True)
class Compatibility(Field):
    unhydrated: Optional[Union[str, Iterable[str]]] = None
    alias: ClassVar[str] = "compatibility"

    @memoized_property
    def hydrated(self) -> Optional[List[str]]:
        if self.unhydrated is None:
            return None
        return ensure_str_list(self.unhydrated)


@dataclass(frozen=True)
class Coverage(Field):
    unhydrated: Optional[Union[str, Iterable[str]]] = None
    alias: ClassVar[str] = "coverage"

    @memoized_property
    def hydrated(self) -> Optional[List[str]]:
        if self.unhydrated is None:
            return None
        return ensure_str_list(self.unhydrated)


@dataclass(frozen=True)
class Timeout(Field):
    unhydrated: Optional[int] = None
    alias: ClassVar[str] = "timeout"

    @memoized_property
    def hydrated(self) -> Optional[int]:
        if self.unhydrated is None:
            return None
        if not isinstance(self.unhydrated, int):
            raise ValueError("")
        if self.unhydrated < 0:
            raise ValueError("")
        return self.unhydrated


@dataclass(frozen=True)
class EntryPoint(Field):
    unhydrated: Optional[str] = None
    alias: ClassVar[str] = "entry_point"

    @memoized_property
    def hydrated(self) -> Optional[str]:
        return self.unhydrated


@dataclass(frozen=True)
class ZipSafe(Field):
    unhydrated: bool = True
    alias: ClassVar[str] = "zip_safe"

    @memoized_property
    def hydrated(self) -> bool:
        return self.unhydrated


@dataclass(frozen=True)
class AlwaysWriteCache(Field):
    unhydrated: bool = False
    alias: ClassVar[str] = "always_write_cache"

    @memoized_property
    def hydrated(self) -> bool:
        return self.unhydrated


@union
class PythonBinaryField(Field):
    pass


@union
class PythonLibraryField(Field):
    pass


@union
class PythonTestsField(Field):
    pass


class PythonBinary(Target):
    alias = "python_binary"
    field_type = PythonBinaryField


class PythonLibrary(Target):
    alias = "python_library"
    field_type = PythonLibraryField


class PythonTests(Target):
    alias = "python_tests"
    field_type = PythonTestsField


def rules():
    common_fields = [Compatibility]
    binary_fields = [EntryPoint, ZipSafe, AlwaysWriteCache]
    library_fields = []
    test_fields = [Coverage, Timeout]

    union_rules = []
    for tgt_cls in [PythonBinary, PythonLibrary, PythonTests]:
        for field in common_fields:
            union_rules.append(UnionRule(tgt_cls.field_type, field))
    union_rules.extend(UnionRule(PythonBinary.field_type, field) for field in binary_fields)
    union_rules.extend(UnionRule(PythonLibrary.field_type, field) for field in library_fields)
    union_rules.extend(UnionRule(PythonTests.field_type, field) for field in test_fields)
    return union_rules
