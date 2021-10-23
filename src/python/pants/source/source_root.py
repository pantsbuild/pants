# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
import logging
import os
from dataclasses import dataclass
from pathlib import PurePath
from typing import Iterable

from pants.build_graph.address import Address
from pants.engine.collection import DeduplicatedCollection
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.fs import PathGlobs, Paths
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import Target
from pants.option.subsystem import Subsystem
from pants.util.docutil import doc_url
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.memo import memoized_method
from pants.util.meta import frozen_after_init

logger = logging.getLogger(__name__)


@dataclass(frozen=True, order=True)
class SourceRoot:
    # Relative path from the buildroot.  Note that a source root at the buildroot
    # is represented as ".".
    path: str


@dataclass(frozen=True)
class OptionalSourceRoot:
    source_root: SourceRoot | None


class SourceRootError(Exception):
    """An error related to SourceRoot computation."""

    def __init__(self, msg: str):
        super().__init__(f"{msg}See {doc_url('source-roots')} for how to define source roots.")


class InvalidSourceRootPatternError(SourceRootError):
    """Indicates an invalid pattern was provided."""


class InvalidMarkerFileError(SourceRootError):
    """Indicates an invalid marker file was provided."""


class NoSourceRootError(SourceRootError):
    """Indicates we failed to map a source file to a source root."""

    def __init__(self, path: str | PurePath, extra_msg: str = ""):
        super().__init__(f"No source root found for `{path}`. {extra_msg}")


# We perform pattern matching against absolute paths, where "/" represents the repo root.
_repo_root = PurePath(os.path.sep)


@dataclass(frozen=True)
class SourceRootPatternMatcher:
    root_patterns: tuple[str, ...]

    def __post_init__(self) -> None:
        for root_pattern in self.root_patterns:
            if ".." in root_pattern.split(os.path.sep):
                raise InvalidSourceRootPatternError(
                    f"`..` disallowed in source root pattern: {root_pattern}. "
                )

    def get_patterns(self) -> tuple[str, ...]:
        return tuple(self.root_patterns)

    def matches_root_patterns(self, relpath: PurePath) -> bool:
        """Does this putative root match a pattern?"""
        # Note: This is currently O(n) where n is the number of patterns, which
        # we expect to be small.  We can optimize if it becomes necessary.
        putative_root = _repo_root / relpath
        for pattern in self.root_patterns:
            if putative_root.match(pattern):
                return True
        return False


class SourceRootConfig(Subsystem):
    options_scope = "source"
    help = "Configuration for roots of source trees."

    DEFAULT_ROOT_PATTERNS = ["/", "src", "src/python", "src/py"]

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--root-patterns",
            metavar='["pattern1", "pattern2", ...]',
            type=list,
            default=cls.DEFAULT_ROOT_PATTERNS,
            advanced=True,
            help="A list of source root suffixes. A directory with this suffix will be considered "
            "a potential source root. E.g., `src/python` will match `<buildroot>/src/python`, "
            "`<buildroot>/project1/src/python` etc. Prepend a `/` to anchor the match at the "
            "buildroot. E.g., `/src/python` will match `<buildroot>/src/python` but not "
            "`<buildroot>/project1/src/python`. A `*` wildcard will match a single path segment, "
            "e.g., `src/*` will match `<buildroot>/src/python` and `<buildroot>/src/rust`. "
            "Use `/` to signify that the buildroot itself is a source root. "
            f"See {doc_url('source-roots')}.",
        )
        register(
            "--marker-filenames",
            metavar="filename",
            type=list,
            member_type=str,
            default=None,
            advanced=True,
            help="The presence of a file of this name in a directory indicates that the directory "
            "is a source root. The content of the file doesn't matter, and may be empty. "
            "Useful when you can't or don't wish to centrally enumerate source roots via "
            "`root_patterns`.",
        )

    @memoized_method
    def get_pattern_matcher(self) -> SourceRootPatternMatcher:
        return SourceRootPatternMatcher(self.options.root_patterns)


@frozen_after_init
@dataclass(unsafe_hash=True)
class SourceRootsRequest:
    """Find the source roots for the given files and/or dirs."""

    files: tuple[PurePath, ...]
    dirs: tuple[PurePath, ...]

    def __init__(self, files: Iterable[PurePath], dirs: Iterable[PurePath]) -> None:
        self.files = tuple(sorted(files))
        self.dirs = tuple(sorted(dirs))
        self.__post_init__()

    def __post_init__(self) -> None:
        for path in itertools.chain(self.files, self.dirs):
            if ".." in str(path).split(os.path.sep):
                raise ValueError(f"SourceRootRequest cannot contain `..` segment: {path}")
            if path.is_absolute():
                raise ValueError(f"SourceRootRequest path must be relative: {path}")

    @classmethod
    def for_files(cls, file_paths: Iterable[str]) -> SourceRootsRequest:
        """Create a request for the source root for the given file."""
        return cls({PurePath(file_path) for file_path in file_paths}, ())


@dataclass(frozen=True)
class SourceRootRequest(EngineAwareParameter):
    """Find the source root for the given path.

    If you have multiple paths, particularly if many of them share parent directories, you'll get
    better performance with a `SourceRootsRequest` (see above) instead.
    """

    path: PurePath

    def __post_init__(self) -> None:
        if ".." in str(self.path).split(os.path.sep):
            raise ValueError(f"SourceRootRequest cannot contain `..` segment: {self.path}")
        if self.path.is_absolute():
            raise ValueError(f"SourceRootRequest path must be relative: {self.path}")

    @classmethod
    def for_file(cls, file_path: str) -> SourceRootRequest:
        """Create a request for the source root for the given file."""
        # The file itself cannot be a source root, so we may as well start the search
        # from its enclosing directory, and save on some superfluous checking.
        return cls(PurePath(file_path).parent)

    @classmethod
    def for_address(cls, address: Address) -> SourceRootRequest:
        # Note that we don't use for_file() here because the spec_path is a directory.
        return cls(PurePath(address.spec_path))

    @classmethod
    def for_target(cls, target: Target) -> SourceRootRequest:
        return cls.for_address(target.address)

    def debug_hint(self) -> str:
        return str(self.path)


@dataclass(frozen=True)
class SourceRootsResult:
    path_to_root: FrozenDict[PurePath, SourceRoot]


@dataclass(frozen=True)
class OptionalSourceRootsResult:
    path_to_optional_root: FrozenDict[PurePath, OptionalSourceRoot]


@rule
async def get_optional_source_roots(
    source_roots_request: SourceRootsRequest,
) -> OptionalSourceRootsResult:
    """Rule to request source roots that may not exist."""
    # A file cannot be a source root, so request for its parent.
    # In the typical case, where we have multiple files with the same parent, this can
    # dramatically cut down on the number of engine requests.
    dirs: set[PurePath] = set(source_roots_request.dirs)
    file_to_dir: dict[PurePath, PurePath] = {
        file: file.parent for file in source_roots_request.files
    }
    dirs.update(file_to_dir.values())

    dir_to_root: dict[PurePath, OptionalSourceRoot] = {}
    for d in dirs:
        root = await Get(OptionalSourceRoot, SourceRootRequest(d))
        dir_to_root[d] = root

    path_to_optional_root: dict[PurePath, OptionalSourceRoot] = {}
    for d in source_roots_request.dirs:
        path_to_optional_root[d] = dir_to_root[d]
    for f, d in file_to_dir.items():
        path_to_optional_root[f] = dir_to_root[d]

    return OptionalSourceRootsResult(path_to_optional_root=FrozenDict(path_to_optional_root))


@rule
async def get_source_roots(source_roots_request: SourceRootsRequest) -> SourceRootsResult:
    """Convenience rule to allow callers to request SourceRoots that must exist.

    That way callers don't have to unpack OptionalSourceRoots if they know they expect a SourceRoot
    to exist and are willing to error if it doesn't.
    """
    osrr = await Get(OptionalSourceRootsResult, SourceRootsRequest, source_roots_request)
    path_to_root = {}
    for path, osr in osrr.path_to_optional_root.items():
        if osr.source_root is None:
            raise NoSourceRootError(path)
        path_to_root[path] = osr.source_root
    return SourceRootsResult(path_to_root=FrozenDict(path_to_root))


@rule
async def get_optional_source_root(
    source_root_request: SourceRootRequest, source_root_config: SourceRootConfig
) -> OptionalSourceRoot:
    """Rule to request a SourceRoot that may not exist."""
    pattern_matcher = source_root_config.get_pattern_matcher()
    path = source_root_request.path

    # Check if the requested path itself is a source root.

    # A) Does it match a pattern?
    if pattern_matcher.matches_root_patterns(path):
        return OptionalSourceRoot(SourceRoot(str(path)))

    # B) Does it contain a marker file?
    marker_filenames = source_root_config.options.marker_filenames
    if marker_filenames:
        for marker_filename in marker_filenames:
            if (
                os.path.basename(marker_filename) != marker_filename
                or "*" in marker_filename
                or "!" in marker_filename
            ):
                raise InvalidMarkerFileError(
                    f"Marker filename must be a base name: {marker_filename}"
                )
        paths = await Get(Paths, PathGlobs([str(path / mf) for mf in marker_filenames]))
        if len(paths.files) > 0:
            return OptionalSourceRoot(SourceRoot(str(path)))

    # The requested path itself is not a source root, but maybe its parent is.
    if str(path) != ".":
        return await Get(OptionalSourceRoot, SourceRootRequest(path.parent))

    # The requested path is not under a source root.
    return OptionalSourceRoot(None)


@rule
async def get_source_root(source_root_request: SourceRootRequest) -> SourceRoot:
    """Convenience rule to allow callers to request a SourceRoot directly.

    That way callers don't have to unpack an OptionalSourceRoot if they know they expect a
    SourceRoot to exist and are willing to error if it doesn't.
    """
    optional_source_root = await Get(OptionalSourceRoot, SourceRootRequest, source_root_request)
    if optional_source_root.source_root is None:
        raise NoSourceRootError(source_root_request.path)
    return optional_source_root.source_root


class AllSourceRoots(DeduplicatedCollection[SourceRoot]):
    sort_input = True


@rule(desc="Compute all source roots", level=LogLevel.DEBUG)
async def all_roots(source_root_config: SourceRootConfig) -> AllSourceRoots:
    source_root_pattern_matcher = source_root_config.get_pattern_matcher()

    # Create globs corresponding to all source root patterns.
    pattern_matches: set[str] = set()
    for path in source_root_pattern_matcher.get_patterns():
        if path == "/":
            pattern_matches.add("**")
        elif path.startswith("/"):
            pattern_matches.add(f"{path[1:]}/")
        else:
            pattern_matches.add(f"**/{path}/")

    # Create globs for any marker files.
    marker_file_matches: set[str] = set()
    for marker_filename in source_root_config.options.marker_filenames:
        marker_file_matches.add(f"**/{marker_filename}")

    # Match the patterns against actual files, to find the roots that actually exist.
    pattern_paths, marker_paths = await MultiGet(
        Get(Paths, PathGlobs(globs=sorted(pattern_matches))),
        Get(Paths, PathGlobs(globs=sorted(marker_file_matches))),
    )

    responses = await MultiGet(
        itertools.chain(
            (Get(OptionalSourceRoot, SourceRootRequest(PurePath(d))) for d in pattern_paths.dirs),
            # We don't technically need to issue a SourceRootRequest for the marker files,
            # since we know that their immediately enclosing dir is a source root by definition.
            # However we may as well verify this formally, so that we're not replicating that
            # logic here.
            (Get(OptionalSourceRoot, SourceRootRequest(PurePath(f))) for f in marker_paths.files),
        )
    )
    all_source_roots = {
        response.source_root for response in responses if response.source_root is not None
    }
    return AllSourceRoots(all_source_roots)


def rules():
    return collect_rules()
