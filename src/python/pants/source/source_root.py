# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
import logging
import os
from dataclasses import dataclass
from pathlib import PurePath
from typing import Iterable, Optional, Set, Tuple, Union

from pants.engine.collection import DeduplicatedCollection
from pants.engine.fs import PathGlobs, Snapshot
from pants.engine.rules import RootRule, SubsystemRule, rule
from pants.engine.selectors import Get, MultiGet
from pants.subsystem.subsystem import Subsystem
from pants.util.memo import memoized_method

logger = logging.getLogger(__name__)


@dataclass(frozen=True, order=True)
class SourceRoot:
    # Relative path from the buildroot. Note that a source root at the buildroot
    # is represented as ".".
    path: str


class SourceRootError(Exception):
    """An error related to SourceRoot computation."""

    def __init__(self, msg: str):
        super().__init__(
            f"{msg}See https://pants.readme.io/docs/source-roots for how to define source roots."
        )


class InvalidSourceRootPatternError(SourceRootError):
    """Indicates an invalid pattern was provided."""


class InvalidMarkerFileError(SourceRootError):
    """Indicates an invalid marker file was provided."""


class NoSourceRootError(SourceRootError):
    """Indicates we failed to map a source file to a source root."""

    def __init__(self, path: Union[str, PurePath], extra_msg: str = ""):
        super().__init__(f"No source root found for `{path}`. {extra_msg}")


# We perform pattern matching against absolute paths, where "/" represents the repo root.
_repo_root = PurePath(os.path.sep)


@dataclass(frozen=True)
class SourceRootPatternMatcher:
    root_patterns: Tuple[str, ...]

    def __post_init__(self) -> None:
        for root_pattern in self.root_patterns:
            if ".." in root_pattern.split(os.path.sep):
                raise InvalidSourceRootPatternError(
                    f"`..` disallowed in source root pattern: {root_pattern}. "
                )

    def get_patterns(self) -> Tuple[str, ...]:
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


class SourceRoots:
    """An interface for querying source roots.

    This is a v1-only class. It exists only because in v1 we need to mutate the source roots (e.g.,
    when injecting a codegen target). v2 code should use the engine to get a SourceRoot or
    OptionalSourceRoot product for a SourceRootRequest subject (see rules below).
    """

    def __init__(self, root_patterns: Iterable[str], fail_if_unmatched: bool = True,) -> None:
        """Create an object for querying source roots.

        Non-test code should not instantiate directly. See SourceRootConfig.get_source_roots().
        """
        self._pattern_matcher = SourceRootPatternMatcher(tuple(root_patterns))
        self._fail_if_unmatched = fail_if_unmatched

    # We perform pattern matching against absolute paths, where "/" represents the repo root.
    _repo_root = PurePath(os.path.sep)

    def add_source_root(self, path):
        """Add the specified fixed source root, which must be relative to the buildroot.

        Useful in a limited set of circumstances, e.g., when unpacking sources from a jar with
        unknown structure.  Tests should prefer to use dirs that match our source root patterns
        instead of explicitly setting source roots here.
        """
        self._pattern_matcher = SourceRootPatternMatcher(
            (*self._pattern_matcher.root_patterns, path)
        )

    def find_by_path(self, path: str) -> Optional[SourceRoot]:
        """Find the source root for the given path, or None.

        :param path: Find the source root for this path, relative to the buildroot.
        :return: A SourceRoot instance, or None if the path is not located under a source root
                 and `unmatched == fail`.
        """
        matched_path = self._find_root(PurePath(path))
        if matched_path:
            return SourceRoot(path=str(matched_path))
        if self._fail_if_unmatched:
            return None
        # If no source root is found, use the path directly.
        return SourceRoot(path)

    def _find_root(self, relpath: PurePath) -> Optional[PurePath]:
        """Return the source root for the given path, relative to the repo root."""

        putative_root = _repo_root / relpath
        while putative_root != _repo_root:
            if self._pattern_matcher.matches_root_patterns(putative_root):
                return putative_root.relative_to(_repo_root)
            putative_root = putative_root.parent
        if self._pattern_matcher.matches_root_patterns(putative_root):
            return putative_root.relative_to(_repo_root)
        return None

    def get_patterns(self) -> Set[str]:
        return set(self._pattern_matcher.get_patterns())


class SourceRootConfig(Subsystem):
    """Configuration for roots of source trees."""

    options_scope = "source"

    DEFAULT_ROOT_PATTERNS = ["/", "src", "src/python", "src/py"]

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--unmatched",
            choices=["create", "fail"],
            default="create",
            advanced=True,
            fingerprint=True,
            help="Configures the behavior when sources are defined outside of any configured "
            "source root. `create` will cause a source root to be implicitly created at "
            "the definition location of the sources; `fail` will trigger an error.",
        )

        register(
            "--root-patterns",
            metavar='["pattern1", "pattern2", ...]',
            type=list,
            fingerprint=True,
            default=cls.DEFAULT_ROOT_PATTERNS,
            advanced=True,
            help="A list of source root suffixes. A directory with this suffix will be considered "
            "a potential source root. E.g., `src/python` will match `<buildroot>/src/python`, "
            "`<buildroot>/project1/src/python` etc. Prepend a `/` to anchor the match at the "
            "buildroot.  E.g., `/src/python` will match `<buildroot>/src/python` but not "
            "`<buildroot>/project1/src/python`.  A `*` wildcard will match a single path segment, "
            "e.g., `src/*` will match `<buildroot>/src/python` and `<buildroot>/src/rust`. "
            "Use `/` to signify that the buildroot itself is a source root. "
            "See https://pants.readme.io/docs/source-roots.",
        )

        register(
            "--marker-filenames",
            metavar="filename",
            type=list,
            member_type=str,
            fingerprint=True,
            default=None,
            advanced=True,
            help="The presence of a file of this name in a directory indicates that the directory "
            "is a source root.  The content of the file doesn't matter, and may be empty. "
            "Useful when you can't or don't wish to centrally enumerate source roots via "
            "--root-patterns.",
        )

    @memoized_method
    def get_pattern_matcher(self) -> SourceRootPatternMatcher:
        return SourceRootPatternMatcher(self.options.root_patterns)

    @memoized_method
    def get_source_roots(self) -> SourceRoots:
        # Only v1 code should call this method.
        return SourceRoots(self.options.root_patterns, self.options.unmatched == "fail")


@dataclass(frozen=True)
class SourceRootRequest:
    """Find the source root for the given path."""

    path: PurePath

    def __post_init__(self) -> None:
        if ".." in str(self.path).split(os.path.sep):
            raise ValueError(f"SourceRootRequest cannot contain `..` segment: {self.path}")
        if self.path.is_absolute():
            raise ValueError(f"SourceRootRequest path must be relative: {self.path}")

    @classmethod
    def for_file(cls, file_path: str) -> "SourceRootRequest":
        """Create a request for the source root for the given file."""
        # The file itself cannot be a source root, so we may as well start the search
        # from its enclosing directory, and save on some superfluous checking.
        return cls(PurePath(file_path).parent)


@dataclass(frozen=True)
class OptionalSourceRoot:
    source_root: Optional[SourceRoot]


@rule
async def get_source_root(
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
        # TODO: An intrinsic to check file existence at a fixed path?
        snapshot = await Get[Snapshot](PathGlobs([str(path / mf) for mf in marker_filenames]))
        if len(snapshot.files) > 0:
            return OptionalSourceRoot(SourceRoot(str(path)))

    # The requested path itself is not a source root, but maybe its parent is.
    if str(path) != ".":
        return await Get[OptionalSourceRoot](SourceRootRequest(path.parent))

    # The requested path is not under a source root.
    return OptionalSourceRoot(None)


@rule
async def get_source_root_strict(source_root_request: SourceRootRequest) -> SourceRoot:
    """Convenience rule to allow callers to request a SourceRoot directly.

    That way callers don't have to unpack an OptionalSourceRoot if they know they expect a
    SourceRoot to exist and are willing to error if it doesn't.
    """
    optional_source_root = await Get[OptionalSourceRoot](SourceRootRequest, source_root_request)
    if optional_source_root.source_root is None:
        raise NoSourceRootError(source_root_request.path)
    return optional_source_root.source_root


class AllSourceRoots(DeduplicatedCollection[SourceRoot]):
    sort_input = True


@rule
async def all_roots(source_root_config: SourceRootConfig) -> AllSourceRoots:
    source_root_pattern_matcher = source_root_config.get_pattern_matcher()

    # Create globs corresponding to all source root patterns.
    pattern_matches: Set[str] = set()
    for path in source_root_pattern_matcher.get_patterns():
        if path == "/":
            pattern_matches.add("**")
        elif path.startswith("/"):
            pattern_matches.add(f"{path[1:]}/")
        else:
            pattern_matches.add(f"**/{path}/")

    # Create globs for any marker files.
    marker_file_matches: Set[str] = set()
    for marker_filename in source_root_config.options.marker_filenames:
        marker_file_matches.add(f"**/{marker_filename}")

    # Match the patterns against actual files, to find the roots that actually exist.
    pattern_snapshot, marker_file_snapshot = await MultiGet(
        Get[Snapshot](PathGlobs(globs=sorted(pattern_matches))),
        Get[Snapshot](PathGlobs(globs=sorted(marker_file_matches))),
    )

    responses = await MultiGet(
        itertools.chain(
            (
                Get[OptionalSourceRoot](SourceRootRequest(PurePath(d)))
                for d in pattern_snapshot.dirs
            ),
            # We don't technically need to issue a SourceRootRequest for the marker files,
            # since we know that their immediately enclosing dir is a source root by definition.
            # However we may as well verify this formally, so that we're not replicating that
            # logic here.
            (
                Get[OptionalSourceRoot](SourceRootRequest(PurePath(f)))
                for f in marker_file_snapshot.files
            ),
        )
    )
    all_source_roots = {
        response.source_root for response in responses if response.source_root is not None
    }
    return AllSourceRoots(all_source_roots)


def rules():
    return [
        get_source_root,
        get_source_root_strict,
        all_roots,
        SubsystemRule(SourceRootConfig),
        RootRule(SourceRootRequest),
    ]
