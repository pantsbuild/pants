# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os.path
from pathlib import Path, PurePath
from typing import Iterable

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

    def __init__(self, root_dir: str) -> None:
        self._root_dir = os.path.realpath(root_dir)

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
        if spec.endswith("::"):
            spec_path = spec[: -len("::")]
            return DescendantAddresses(directory=self._normalize_spec_path(spec_path))
        if spec.endswith(":"):
            spec_path = spec[: -len(":")]
            return SiblingAddresses(directory=self._normalize_spec_path(spec_path))
        if ":" in spec or "#" in spec:
            tgt_parts = spec.split(":", maxsplit=1)
            path_component = tgt_parts[0]
            if len(tgt_parts) == 1:
                target_component = None
                generated_parts = path_component.split("#", maxsplit=1)
                if len(generated_parts) == 1:
                    generated_component = None
                else:
                    path_component, generated_component = generated_parts
            else:
                generated_parts = tgt_parts[1].split("#", maxsplit=1)
                if len(generated_parts) == 1:
                    target_component = generated_parts[0]
                    generated_component = None
                else:
                    target_component, generated_component = generated_parts
            return AddressLiteralSpec(
                path_component=self._normalize_spec_path(path_component),
                target_component=target_component,
                generated_component=generated_component,
            )
        if spec.startswith("!"):
            return FileIgnoreSpec(spec[1:])
        if "*" in spec:
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
