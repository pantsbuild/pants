# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
from dataclasses import dataclass
from pathlib import PurePath
from typing import Dict, Iterable, Optional, Sequence, Set, Tuple

from pants.base.deprecated import deprecated_conditional
from pants.engine.collection import Collection
from pants.subsystem.subsystem import Subsystem
from pants.util.memo import memoized_method

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SourceRoot:
    path: str  # Relative path from the repo root.


class InvalidSourceRootPatternError(Exception):
    """Indicates an invalid pattern was provided."""


class NoSourceRootError(Exception):
    """Indicates we failed to map a source file to a source root."""


class AllSourceRoots(Collection[SourceRoot]):
    pass


class SourceRootPatternMatcher:
    # We perform pattern matching against absolute paths, where "/" represents the repo root.
    _repo_root = PurePath(os.path.sep)

    def __init__(self, root_patterns: Iterable[str]) -> None:
        for root_pattern in root_patterns:
            if ".." in root_pattern.split(os.path.sep):
                raise InvalidSourceRootPatternError(
                    f".. disallowed in source root pattern: {root_pattern}"
                )
        self._root_patterns = list(root_patterns)

    def get_patterns(self) -> Tuple[str, ...]:
        return tuple(self._root_patterns)

    def add_source_root(self, path):
        """Add the specified fixed source root, which must be relative to the buildroot.

        Useful in a limited set of circumstances, e.g., when unpacking sources from a jar with
        unknown structure.  Tests should prefer to use dirs that match our source root patterns
        instead of explicitly setting source roots here.
        """
        self._root_patterns.append(str(self._repo_root / path))

    def _match_root_patterns(self, putative_root: PurePath) -> bool:
        for pattern in self._root_patterns:
            if putative_root.match(pattern):
                return True
        return False

    def find_root(self, relpath: str) -> Optional[PurePath]:
        """Return the source root for the given path, relative to the repo root."""
        # Note: This is currently O(n) where n is the number of patterns, which
        # we expect to be small.  We can optimize if it becomes necessary.
        if ".." in relpath.split(os.path.sep):
            raise NoSourceRootError(f".. disallowed in source root searches: {relpath}")
        putative_root = self._repo_root / relpath
        while putative_root != self._repo_root:
            if self._match_root_patterns(putative_root):
                return putative_root.relative_to(self._repo_root)
            putative_root = putative_root.parent
        if self._match_root_patterns(putative_root):
            return putative_root.relative_to(self._repo_root)
        return None


class SourceRoots:
    """An interface for querying source roots."""

    # TODO: Can be simplified/merged into SourceRootPatternMatcher once the deprecated trie is gone.

    def __init__(
        self,
        root_patterns: Iterable[str],
        fail_if_unmatched: bool = True,
        source_root_config: Optional["SourceRootConfig"] = None,
    ) -> None:
        """Create an object for querying source roots via patterns in a trie.

        Non-test code should not instantiate directly. See SourceRootConfig.get_source_roots().
        """
        self._pattern_matcher = SourceRootPatternMatcher(root_patterns)
        # TODO: In 1.30.0.dev0 remove the trie entirely.
        self._trie = None if self._pattern_matcher.get_patterns() else source_root_config.create_trie()  # type: ignore[union-attr]
        self._fail_if_unmatched = fail_if_unmatched

    # We perform pattern matching against absolute paths, where "/" represents the repo root.
    _repo_root = PurePath(os.path.sep)

    def add_source_root(self, path):
        """Add the specified fixed source root, which must be relative to the buildroot.

        Useful in a limited set of circumstances, e.g., when unpacking sources from a jar with
        unknown structure.  Tests should prefer to use dirs that match our source root patterns
        instead of explicitly setting source roots here.
        """
        self._pattern_matcher.add_source_root(path)

    def strict_find_by_path(self, path: str) -> SourceRoot:
        """Find the source root for the given path.

        Raises an error if there is no known source root for the path.
        """
        matched_path = self._pattern_matcher.find_root(path)
        if matched_path:
            return SourceRoot(path=str(matched_path))
        if self._trie:
            matched = self._trie.find(path)
            if matched:
                return matched
        raise NoSourceRootError(
            f"Could not find a source root for `{path}`. See "
            f"https://pants.readme.io/docs/source-roots for how to define source roots."
        )

    def find_by_path(self, path: str) -> Optional[SourceRoot]:
        """Find the source root for the given path, or None.

        :param path: Find the source root for this path, relative to the buildroot.
        :return: A SourceRoot instance, or None if the path is not located under a source root
                 and `unmatched == fail`.

        TODO: Only v1 code should call this method. v2 code should use strict_find_by_path().
         Silently creating source roots on the fly is confusing legacy behavior that we shouldn't
         carry over into v2.
        """
        try:
            return self.strict_find_by_path(path)
        except NoSourceRootError:
            if self._fail_if_unmatched:
                return None
            # If no source root is found, use the path directly.
            return SourceRoot(path)

    def get_patterns(self) -> Set[str]:
        return self._trie.traverse() if self._trie else sorted(self._pattern_matcher.get_patterns())


class SourceRootConfig(Subsystem):
    """Configuration for roots of source trees."""

    options_scope = "source"

    _DEFAULT_LANG_CANONICALIZATIONS = {
        "jvm": ("java", "scala"),
        "protobuf": ("proto",),
        "py": ("python",),
        "golang": ("go",),
    }

    _DEFAULT_SOURCE_ROOT_PATTERNS = [
        "src/*",
        "src/main/*",
    ]

    _DEFAULT_TEST_ROOT_PATTERNS = [
        "test/*",
        "tests/*",
        "src/test/*",
    ]

    _DEFAULT_THIRDPARTY_ROOT_PATTERNS = [
        "3rdparty/*",
        "3rd_party/*",
        "thirdparty/*",
        "third_party/*",
    ]

    _DEFAULT_SOURCE_ROOTS = {
        # Our default patterns will detect src/go as a go source root.
        # However a typical repo might have src/go in the GOPATH, meaning src/go/src is the
        # actual source root (the root of the package namespace).
        # These fixed source roots will correct the patterns' incorrect guess.
        "src/go/src": ("go",),
        "src/main/go/src": ("go",),
    }

    _DEFAULT_TEST_ROOTS: Dict[str, Tuple[str, ...]] = {}

    _DEFAULT_THIRDPARTY_ROOTS: Dict[str, Tuple[str, ...]] = {}

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
            "--lang-canonicalizations",
            metavar="<map>",
            type=dict,
            fingerprint=True,
            default=cls._DEFAULT_LANG_CANONICALIZATIONS,
            advanced=True,
            removal_version="1.30.0.dev0",
            removal_hint="No longer necessary. Source roots are no longer associated with "
            "languages.",
            help="Map of language aliases to their canonical names.",
        )

        pattern_help_fmt = (
            'A list of source root patterns for {} code. Use a "*" wildcard path '
            "segment to match the language name, which will be canonicalized."
        )
        register(
            "--source-root-patterns",
            metavar="<list>",
            type=list,
            fingerprint=True,
            default=cls._DEFAULT_SOURCE_ROOT_PATTERNS,
            advanced=True,
            removal_version="1.30.0.dev0",
            removal_hint="Use --root-patterns instead.",
            help=pattern_help_fmt.format("source"),
        )
        register(
            "--test-root-patterns",
            metavar="<list>",
            type=list,
            fingerprint=True,
            default=cls._DEFAULT_TEST_ROOT_PATTERNS,
            advanced=True,
            removal_version="1.30.0.dev0",
            removal_hint="Use --root-patterns instead.",
            help=pattern_help_fmt.format("test"),
        )
        register(
            "--thirdparty-root-patterns",
            metavar="<list>",
            type=list,
            fingerprint=True,
            default=cls._DEFAULT_THIRDPARTY_ROOT_PATTERNS,
            advanced=True,
            removal_version="1.30.0.dev0",
            removal_hint="Use --root-patterns instead.",
            help=pattern_help_fmt.format("third-party"),
        )

        fixed_help_fmt = (
            "A map of source roots for {} code to list of languages. "
            "Useful when you want to enumerate fixed source roots explicitly, "
            "instead of relying on patterns."
        )
        register(
            "--source-roots",
            metavar="<map>",
            type=dict,
            fingerprint=True,
            default=cls._DEFAULT_SOURCE_ROOTS,
            advanced=True,
            removal_version="1.30.0.dev0",
            removal_hint="Use --root-patterns instead.",
            help=fixed_help_fmt.format("source"),
        )
        register(
            "--test-roots",
            metavar="<map>",
            type=dict,
            fingerprint=True,
            default=cls._DEFAULT_TEST_ROOTS,
            advanced=True,
            removal_version="1.30.0.dev0",
            removal_hint="Use --root-patterns instead.",
            help=fixed_help_fmt.format("test"),
        )
        register(
            "--thirdparty-roots",
            metavar="<map>",
            type=dict,
            fingerprint=True,
            default=cls._DEFAULT_THIRDPARTY_ROOTS,
            advanced=True,
            removal_version="1.30.0.dev0",
            removal_hint="Use --root-patterns instead.",
            help=fixed_help_fmt.format("third-party"),
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
    def get_source_roots(self):
        return SourceRoots(self.options.root_patterns, self.options.unmatched == "fail", self)

    def create_trie(self) -> "SourceRootTrie":
        """Create a trie of source root patterns from options."""
        trie = SourceRootTrie()
        options = self.get_options()

        legacy_patterns = []
        for category in ["source", "test", "thirdparty"]:
            # Add patterns.
            for pattern in options.get("{}_root_patterns".format(category), []):
                trie.add_pattern(pattern)
                legacy_patterns.append(pattern)
            # Add fixed source roots.
            for path, langs in options.get("{}_roots".format(category), {}).items():
                trie.add_fixed(path)
                legacy_patterns.append(f"^/{path}")
        # We need to issue a deprecation warning even if relying on the default values
        # of the deprecated options.
        deprecated_conditional(
            lambda: True,
            removal_version="1.30.0.dev0",
            entity_description="the *_root_patterns and *_roots options",
            hint_message="Explicitly list your source roots with the `root_patterns` option in "
            "the [source] scope. See https://pants.readme.io/docs/source-roots. "
            f"See your current roots with `{self.options.pants_bin_name} roots`.",
        )
        return trie


class SourceRootTrie:
    """A trie for efficiently finding the source root for a path.

    Finds the first outermost pattern that matches. E.g., the pattern src/* will match
    my/project/src/python/src/java/java.py on src/python, not on src/java.

    Implements fixed source roots by prepending a '^/' to them, and then prepending a '^' key to
    the path we're matching. E.g., ^/src/java/foo/bar will match both the fixed root ^/src/java and
    the pattern src/java, but ^/my/project/src/java/foo/bar will match only the pattern.
    """

    class InvalidPath(Exception):
        def __init__(self, path, reason):
            super().__init__(f"Invalid source root path or pattern: {path}. Reason: {reason}.")

    class Node:
        def __init__(self):
            self.children = {}
            self.is_terminal = False
            # We need an explicit terminal flag because not all terminals are leaf nodes,  e.g.,
            # if we have patterns src/* and src/main/* then the '*' is a terminal (for the first pattern)
            # but not a leaf.

        def get_child(self, key):
            """Return the child node for the given key, or None if no such child.

            :param key: The child to return.
            """
            # An exact match takes precedence over a wildcard match, to support situations such as
            # src/* and src/main/*.
            ret = self.children.get(key)
            if not ret and key != "^":
                ret = self.children.get("*")
            return ret

        def new_child(self, key):
            child = SourceRootTrie.Node()
            self.children[key] = child
            return child

        def subpatterns(self):
            if self.children:
                for key, child in self.children.items():
                    for sp in child.subpatterns():
                        if sp:
                            yield os.path.join(key, sp)
                        else:
                            yield key
            else:
                yield ""

    def __init__(self) -> None:
        self._root = SourceRootTrie.Node()

    def add_pattern(self, pattern):
        """Add a pattern to the trie."""
        self._do_add_pattern(pattern)

    def add_fixed(self, path):
        """Add a fixed source root to the trie."""
        if "*" in path:
            raise self.InvalidPath(path, "fixed path cannot contain the * character")
        fixed_path = os.path.join("^", path) if path else "^"
        self._do_add_pattern(fixed_path)

    def fixed(self):
        """Returns a list of just the fixed source roots in the trie."""
        for key, child in self._root.children.items():
            if key == "^":
                return list(child.subpatterns())
        return []

    def _do_add_pattern(self, pattern):
        if pattern != os.path.normpath(pattern):
            raise self.InvalidPath(pattern, "must be a normalized path")
        keys = pattern.split(os.path.sep)

        node = self._root
        for key in keys:
            # Can't use get_child, as we don't want to wildcard-match.
            child = node.children.get(key)
            if not child:
                child = node.new_child(key)
            node = child
        node.is_terminal = True

    def is_empty(self) -> bool:
        return not bool(self._root.children)

    def traverse(self) -> Set[str]:
        source_roots: Set[str] = set()

        def traverse_helper(node: SourceRootTrie.Node, path_components: Sequence[str]):
            for name in node.children:
                child = node.children[name]
                if child.is_terminal:
                    effective_path = "/".join([*path_components, name])
                    source_roots.add(effective_path)
                traverse_helper(node=child, path_components=[*path_components, name])

        traverse_helper(self._root, [])
        return source_roots

    def find(self, path) -> Optional[SourceRoot]:
        """Find the source root for the given path."""
        keys = ["^"] + path.split(os.path.sep)
        for i in range(len(keys)):
            # See if we have a match at position i.  We have such a match if following the path
            # segments into the trie, from the root, leads us to a terminal.
            node = self._root
            j = i
            while j < len(keys):
                child = node.get_child(keys[j])
                if child is None:
                    break
                else:
                    node = child
                    j += 1
            if node.is_terminal:
                if j == 1:  # The match was on the root itself.
                    path = ""
                else:
                    path = os.path.join(*keys[1:j])
                return SourceRoot(path)
            # Otherwise, try the next value of i.
        return None
