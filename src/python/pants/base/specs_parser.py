# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os.path
from pathlib import Path, PurePath
from typing import Iterable

from pants.base.build_environment import get_buildroot
from pants.base.specs import (
    AddressLiteralSpec,
    AddressSpec,
    AddressSpecs,
    DescendantAddresses,
    DirLiteralSpec,
    FileGlobSpec,
    FileIgnoreSpec,
    FileLiteralSpec,
    FilesystemSpec,
    FilesystemSpecs,
    SiblingAddresses,
    Specs,
)
from pants.engine.internals import native_engine
from pants.util.frozendict import FrozenDict
from pants.util.ordered_set import OrderedSet


class SpecsParser:
    """Parses address and filesystem specs as passed from the command line.

    See the `specs` module for more information on the types of objects returned.
    This class supports some flexibility in the path portion of the spec to allow for more natural
    command line use cases like tab completion leaving a trailing / for directories and relative
    paths, i.e. both of these::

      ./src/::
      /absolute/path/to/project/src/::

    Are valid command line specs even though they are not a valid BUILD file specs.  They're both
    normalized to::

      src::
    """

    class BadSpecError(Exception):
        """Indicates an unparseable command line selector."""

    def __init__(self, root_dir: str | None = None) -> None:
        self._root_dir = os.path.realpath(root_dir or get_buildroot())

    def _normalize_spec_path(self, path: str) -> str:
        is_abs = not path.startswith("//") and os.path.isabs(path)
        if is_abs:
            path = os.path.realpath(path)
            if os.path.commonprefix([self._root_dir, path]) != self._root_dir:
                raise self.BadSpecError(
                    f"Absolute spec path {path} does not share build root {self._root_dir}"
                )
        else:
            if path.startswith("//"):
                path = path[2:]
            path = os.path.join(self._root_dir, path)

        normalized = os.path.relpath(path, self._root_dir)
        if normalized == ".":
            normalized = ""
        return normalized

    def parse_spec(self, spec: str) -> AddressSpec | FilesystemSpec:
        """Parse the given spec into an `AddressSpec` or `FilesystemSpec` object.

        :raises: CmdLineSpecParser.BadSpecError if the address selector could not be parsed.
        """
        (
            is_ignored,
            (
                path_component,
                target_component,
                generated_component,
                parameters,
            ),
            wildcard,
        ) = native_engine.address_spec_parse(spec)

        def assert_not_ignored(spec_descriptor: str) -> None:
            if is_ignored:
                raise self.BadSpecError(
                    f"The {spec_descriptor} spec `{spec}` does not support ignore (`!`) syntax."
                )

        if wildcard == "::":
            assert_not_ignored("address wildcard")
            return DescendantAddresses(directory=self._normalize_spec_path(path_component))
        if wildcard == ":":
            assert_not_ignored("address wildcard")
            return SiblingAddresses(directory=self._normalize_spec_path(path_component))
        if target_component or generated_component or parameters:
            assert_not_ignored("address")
            return AddressLiteralSpec(
                path_component=self._normalize_spec_path(path_component),
                target_component=target_component,
                generated_component=generated_component,
                parameters=FrozenDict(sorted(parameters)),
            )
        if is_ignored:
            return FileIgnoreSpec(path_component)
        if "*" in path_component:
            return FileGlobSpec(spec)
        if PurePath(spec).suffix:
            return FileLiteralSpec(self._normalize_spec_path(spec))
        spec_path = self._normalize_spec_path(spec)
        if spec_path == ".":
            return DirLiteralSpec("")
        # Some paths that look like dirs can actually be files without extensions.
        if Path(self._root_dir, spec_path).is_file():
            return FileLiteralSpec(spec_path)
        return DirLiteralSpec(spec_path)

    def parse_specs(self, specs: Iterable[str]) -> Specs:
        address_specs: OrderedSet[AddressSpec] = OrderedSet()
        filesystem_specs: OrderedSet[FilesystemSpec] = OrderedSet()
        for spec_str in specs:
            parsed_spec = self.parse_spec(spec_str)
            if isinstance(parsed_spec, AddressSpec):
                address_specs.add(parsed_spec)
            elif isinstance(parsed_spec, DirLiteralSpec):
                address_specs.add(parsed_spec.to_address_literal())
            else:
                filesystem_specs.add(parsed_spec)

        return Specs(
            AddressSpecs(address_specs, filter_by_global_options=True),
            FilesystemSpecs(filesystem_specs),
        )
