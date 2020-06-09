# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
from dataclasses import dataclass
from pathlib import PurePath
from typing import Iterable, Optional, Set, Tuple

from pants.engine.collection import DeduplicatedCollection
from pants.engine.rules import RootRule, SubsystemRule, rule
from pants.subsystem.subsystem import Subsystem
from pants.util.memo import memoized_method

logger = logging.getLogger(__name__)


@dataclass(frozen=True, order=True)
class SourceRoot:
    path: str  # Relative path from the repo root.


class SourceRootError(Exception):
    """An error related to SourceRoot computation."""

    def __init__(self, msg: str):
        super().__init__(
            f"{msg}See https://pants.readme.io/docs/source-roots for how to define source roots."
        )


class InvalidSourceRootPatternError(SourceRootError):
    """Indicates an invalid pattern was provided."""


class NoSourceRootError(SourceRootError):
    """Indicates we failed to map a source file to a source root."""

    def __init__(self, path: str, extra_msg: str = ""):
        super().__init__(f"No source root found for `{path}`. {extra_msg}")


class AllSourceRoots(DeduplicatedCollection[SourceRoot]):
    sort_input = True


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

    def _match_root_patterns(self, putative_root: PurePath) -> bool:
        for pattern in self.root_patterns:
            if putative_root.match(pattern):
                return True
        return False

    def find_root(self, relpath: str) -> Optional[PurePath]:
        """Return the source root for the given path, relative to the repo root."""
        # Note: This is currently O(n) where n is the number of patterns, which
        # we expect to be small.  We can optimize if it becomes necessary.
        if ".." in relpath.split(os.path.sep):
            raise NoSourceRootError(relpath, "`..` disallowed in source root searches. ")
        putative_root = _repo_root / relpath
        while putative_root != _repo_root:
            if self._match_root_patterns(putative_root):
                return putative_root.relative_to(_repo_root)
            putative_root = putative_root.parent
        if self._match_root_patterns(putative_root):
            return putative_root.relative_to(_repo_root)
        return None


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
        matched_path = self._pattern_matcher.find_root(path)
        if matched_path:
            return SourceRoot(path=str(matched_path))
        if self._fail_if_unmatched:
            return None
        # If no source root is found, use the path directly.
        return SourceRoot(path)

    def get_patterns(self) -> Set[str]:
        return set(self._pattern_matcher.get_patterns())


class SourceRootConfig(Subsystem):
    """Configuration for roots of source trees."""

    options_scope = "source"

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
            # For Python a good default might be the repo root, but that would be a bad default
            # for other languages, so best to have no default for now, and force users to be
            # explicit about this when integrating Pants.  It's a fairly trivial thing to do.
            default=[],
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

    path: str

    @classmethod
    def for_file(cls, file_path: str) -> "SourceRootRequest":
        """Create a request for the source root for the given file."""
        # The file itself cannot be a source root, so we may as well start the search
        # from its enclosing directory, and save on some superfluous checking.
        return cls(str(PurePath(file_path).parent))


@dataclass(frozen=True)
class OptionalSourceRoot:
    source_root: Optional[SourceRoot]


@rule
def get_source_root(
    source_root_request: SourceRootRequest, source_root_config: SourceRootConfig
) -> OptionalSourceRoot:
    """Rule to request a SourceRoot that may not exist."""
    matched_path = source_root_config.get_pattern_matcher().find_root(source_root_request.path)
    if matched_path:
        return OptionalSourceRoot(SourceRoot(path=str(matched_path)))
    else:
        return OptionalSourceRoot(None)


@rule
def get_source_root_strict(
    source_root_request: SourceRootRequest, source_root_config: SourceRootConfig
) -> SourceRoot:
    """Convenience rule to allow callers to request a SourceRoot directly.

    That way callers don't have to unpack an OptionalSourceRoot if they know they expect a
    SourceRoot to exist and are willing to error if it doesn't.
    """
    matched_path = source_root_config.get_pattern_matcher().find_root(source_root_request.path)
    if matched_path:
        return SourceRoot(path=str(matched_path))
    else:
        raise NoSourceRootError(source_root_request.path)


def rules():
    return [
        get_source_root,
        get_source_root_strict,
        SubsystemRule(SourceRootConfig),
        RootRule(SourceRootRequest),
    ]
