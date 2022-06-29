# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os.path
from pathlib import Path, PurePath
from typing import Iterable

from pants.base.build_environment import get_buildroot
from pants.base.glob_match_error_behavior import GlobMatchErrorBehavior
from pants.base.specs import (
    AddressLiteralSpec,
    DirGlobSpec,
    DirLiteralSpec,
    FileGlobSpec,
    FileLiteralSpec,
    RawSpecs,
    RecursiveGlobSpec,
    Spec,
    Specs,
)
from pants.engine.internals import native_engine
from pants.util.frozendict import FrozenDict


class SpecsParser:
    """Parses specs as passed from the command line.

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

    def parse_spec(self, spec: str) -> tuple[Spec, bool]:
        """Parse the given spec string and also return `true` if it's an ignore.

        :raises: CmdLineSpecParser.BadSpecError if the address selector could not be parsed.
        """
        is_ignore = False
        if spec.startswith("-"):
            is_ignore = True
            spec = spec[1:]

        (
            (
                path_component,
                target_component,
                generated_component,
                parameters,
            ),
            wildcard,
        ) = native_engine.address_spec_parse(spec)

        if wildcard == "::":
            return RecursiveGlobSpec(directory=self._normalize_spec_path(path_component)), is_ignore
        if wildcard == ":":
            return DirGlobSpec(directory=self._normalize_spec_path(path_component)), is_ignore
        if target_component or generated_component or parameters:
            return (
                AddressLiteralSpec(
                    path_component=self._normalize_spec_path(path_component),
                    target_component=target_component,
                    generated_component=generated_component,
                    parameters=FrozenDict(sorted(parameters)),
                ),
                is_ignore,
            )
        if "*" in path_component:
            return FileGlobSpec(spec), is_ignore
        if PurePath(spec).suffix:
            return FileLiteralSpec(self._normalize_spec_path(spec)), is_ignore
        spec_path = self._normalize_spec_path(spec)
        if spec_path == ".":
            return DirLiteralSpec(""), is_ignore
        # Some paths that look like dirs can actually be files without extensions.
        if Path(self._root_dir, spec_path).is_file():
            return FileLiteralSpec(spec_path), is_ignore
        return DirLiteralSpec(spec_path), is_ignore

    def parse_specs(
        self,
        specs: Iterable[str],
        *,
        description_of_origin: str,
        convert_dir_literal_to_address_literal: bool,
        unmatched_glob_behavior: GlobMatchErrorBehavior = GlobMatchErrorBehavior.error,
    ) -> Specs:
        include_specs = []
        ignore_specs = []
        for spec_str in specs:
            spec, is_ignore = self.parse_spec(spec_str)
            if is_ignore:
                ignore_specs.append(spec)
            else:
                include_specs.append(spec)

        includes = RawSpecs.create(
            include_specs,
            description_of_origin=description_of_origin,
            convert_dir_literal_to_address_literal=convert_dir_literal_to_address_literal,
            unmatched_glob_behavior=unmatched_glob_behavior,
            filter_by_global_options=True,
        )
        ignores = RawSpecs.create(
            ignore_specs,
            description_of_origin=description_of_origin,
            convert_dir_literal_to_address_literal=convert_dir_literal_to_address_literal,
            unmatched_glob_behavior=unmatched_glob_behavior,
            # By setting the below to False, we will end up matching some targets
            # that cannot have been resolved by the include specs. For example, if the user runs
            # `--filter-target-type=my_tgt :: !dir::`, the ignores may match targets that are not
            # my_tgt. However, there also is no harm in over-matching with ignores. Setting
            # this to False (over-conservatively?) ensures that if a user says to ignore
            # something, we definitely do.
            filter_by_global_options=False,
        )
        return Specs(includes, ignores)
