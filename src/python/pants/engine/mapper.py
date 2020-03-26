# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, Tuple, Union, cast

from pants.base.exceptions import DuplicateNameError, MappingError, UnaddressableObjectError
from pants.build_graph.address import Address, BuildFileAddress
from pants.engine.objects import Serializable
from pants.engine.parser import Parser
from pants.util.memo import memoized_property
from pants.util.meta import frozen_after_init

ThinAddressableObject = Union[Serializable, Any]


@dataclass(frozen=True)
class AddressMap:
    """Maps addressable Serializable objects from a byte source.

    To construct an AddressMap, use `parse`.

    :param path: The path to the byte source this address map's objects were passed from.
    :param objects_by_name: A dict mapping from object name to the parsed 'thin' addressable object.
    """

    path: str
    objects_by_name: Dict[str, ThinAddressableObject]

    @classmethod
    def parse(cls, filepath: str, filecontent: bytes, parser: Parser) -> "AddressMap":
        """Parses a source for addressable Serializable objects.

        No matter the parser used, the parsed and mapped addressable objects are all 'thin'; ie: any
        objects they point to in other namespaces or even in the same namespace but from a separate
        source are left as unresolved pointers.

        :param filepath: The path to the byte source containing serialized objects.
        :param filecontent: The content of byte source containing serialized objects to be parsed.
        :param parser: The parser cls to use.
        """
        try:
            objects = parser.parse(filepath, filecontent)
        except Exception as e:
            raise MappingError(f"Failed to parse {filepath}:\n{e!r}")
        objects_by_name: Dict[str, ThinAddressableObject] = {}
        for obj in objects:
            if not Serializable.is_serializable(obj):
                raise UnaddressableObjectError("Parsed a non-serializable object: {!r}".format(obj))
            attributes = obj._asdict()

            name = attributes.get("name")
            if not name:
                raise UnaddressableObjectError("Parsed a non-addressable object: {!r}".format(obj))

            if name in objects_by_name:
                raise DuplicateNameError(
                    "An object already exists at {!r} with name {!r}: {!r}.  Cannot "
                    "map {!r}".format(filepath, name, objects_by_name[name], obj)
                )
            objects_by_name[name] = obj
        return cls(filepath, dict(sorted(objects_by_name.items())))


class DifferingFamiliesError(MappingError):
    """Indicates an attempt was made to merge address maps from different families together."""


@dataclass(frozen=True)
class AddressFamily:
    """Represents the family of addressed objects in a namespace.

    To create an AddressFamily, use `create`.

    An address family can be composed of the addressed objects from zero or more underlying address
    sources. An "empty" AddressFamily is legal, and is the result when there are not build files in a
    particular namespace.

    :param namespace: The namespace path of this address family.
    :param objects_by_name: A dict mapping from object name to the parsed 'thin' addressable object.
    """

    namespace: str
    objects_by_name: Dict[str, Tuple[str, ThinAddressableObject]]

    @classmethod
    def create(cls, spec_path: str, address_maps: Iterable[AddressMap]) -> "AddressFamily":
        """Creates an address family from the given set of address maps.

        :param spec_path: The directory prefix shared by all address_maps.
        :param address_maps: The family of maps that form this namespace.
        :raises: :class:`MappingError` if the given address maps do not form a family.
        """
        if spec_path == ".":
            spec_path = ""
        for address_map in address_maps:
            if not address_map.path.startswith(spec_path):
                raise DifferingFamiliesError(
                    "Expected AddressMaps to share the same parent directory {}, "
                    "but received: {}".format(spec_path, address_map.path)
                )

        objects_by_name: Dict[str, Tuple[str, ThinAddressableObject]] = {}
        for address_map in address_maps:
            current_path = address_map.path
            for name, obj in address_map.objects_by_name.items():
                previous = objects_by_name.get(name)
                if previous:
                    previous_path, _ = previous
                    raise DuplicateNameError(
                        "An object with name {name!r} is already defined in "
                        "{previous_path!r}, will not overwrite with {obj!r} from "
                        "{current_path!r}.".format(
                            name=name,
                            previous_path=previous_path,
                            obj=obj,
                            current_path=current_path,
                        )
                    )
                objects_by_name[name] = (current_path, obj)
        return AddressFamily(
            namespace=spec_path,
            objects_by_name={
                name: (path, obj) for name, (path, obj) in sorted(objects_by_name.items())
            },
        )

    @memoized_property
    def addressables(self) -> Dict[BuildFileAddress, ThinAddressableObject]:
        """Return a mapping from BuildFileAddress to thin addressable objects in this namespace.

        :rtype: dict from `BuildFileAddress` to thin addressable objects.
        """
        return {
            BuildFileAddress(rel_path=path, target_name=name): obj
            for name, (path, obj) in self.objects_by_name.items()
        }

    @property
    def addressables_as_address_keyed(self) -> Dict[Address, ThinAddressableObject]:
        """Identical to `addresses`, but with a `cast` to allow for type safe lookup of `Address`es.

        :rtype: dict from `Address` to thin addressable objects.
        """
        return cast(Dict[Address, ThinAddressableObject], self.addressables)

    def __hash__(self):
        return hash(self.namespace)

    def __repr__(self):
        return "AddressFamily(namespace={!r}, objects_by_name={!r})".format(
            self.namespace, list(self.objects_by_name.keys())
        )


@frozen_after_init
@dataclass(unsafe_hash=True)
class AddressMapper:
    """Configuration to parse build files matching a filename pattern."""

    parser: Parser
    build_patterns: Tuple[str, ...]
    build_ignore_patterns: Tuple[str, ...]
    exclude_target_regexps: Tuple[str, ...]
    subproject_roots: Tuple[str, ...]

    def __init__(
        self,
        parser: Parser,
        build_patterns: Optional[Iterable[str]] = None,
        build_ignore_patterns: Optional[Iterable[str]] = None,
        exclude_target_regexps: Optional[Iterable[str]] = None,
        subproject_roots: Optional[Iterable[str]] = None,
    ) -> None:
        """Create an AddressMapper.

        Both the set of files that define a mappable BUILD files and the parser used to parse those
        files can be customized.  See the `pants.engine.parsers` module for example parsers.

        :param parser: The BUILD file parser to use.
        :param build_patterns: A tuple of fnmatch-compatible patterns for identifying BUILD files
                              used to resolve addresses.
        :param build_ignore_patterns: A list of path ignore patterns used when searching for BUILD files.
        :param exclude_target_regexps: A list of regular expressions for excluding targets.
        """
        self.parser = parser
        self.build_patterns = tuple(build_patterns or ["BUILD", "BUILD.*"])
        self.build_ignore_patterns = tuple(build_ignore_patterns or [])
        self.exclude_target_regexps = tuple(exclude_target_regexps or [])
        self.subproject_roots = tuple(subproject_roots or [])

    def __repr__(self):
        return "AddressMapper(parser={}, build_patterns={})".format(
            self.parser, self.build_patterns
        )

    @memoized_property
    def exclude_patterns(self):
        return tuple(re.compile(pattern) for pattern in self.exclude_target_regexps)
