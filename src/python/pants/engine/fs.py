# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Iterable, Optional, Tuple, Union

# Note: several of these types are re-exported as the public API of `engine/fs.py`.
from pants.base.glob_match_error_behavior import GlobMatchErrorBehavior as GlobMatchErrorBehavior
from pants.engine.collection import Collection
from pants.engine.engine_aware import SideEffecting
from pants.engine.internals.native_engine import EMPTY_DIGEST as EMPTY_DIGEST  # noqa: F401
from pants.engine.internals.native_engine import (  # noqa: F401
    EMPTY_FILE_DIGEST as EMPTY_FILE_DIGEST,
)
from pants.engine.internals.native_engine import EMPTY_SNAPSHOT as EMPTY_SNAPSHOT  # noqa: F401
from pants.engine.internals.native_engine import AddPrefix as AddPrefix
from pants.engine.internals.native_engine import Digest as Digest
from pants.engine.internals.native_engine import FileDigest as FileDigest
from pants.engine.internals.native_engine import MergeDigests as MergeDigests
from pants.engine.internals.native_engine import RemovePrefix as RemovePrefix
from pants.engine.internals.native_engine import Snapshot as Snapshot
from pants.engine.rules import QueryRule
from pants.util.meta import frozen_after_init

if TYPE_CHECKING:
    from pants.engine.internals.scheduler import SchedulerSession


@dataclass(frozen=True)
class Paths:
    """A Paths object is a collection of sorted file paths and dir paths.

    Paths is like a Snapshot, but has the performance optimization that it does not digest the files
    or save them to the LMDB store.
    """

    files: Tuple[str, ...]
    dirs: Tuple[str, ...]


@dataclass(frozen=True)
class FileContent:
    """The content of a file.

    This can be used to create a new Digest with `Get(Digest, CreateDigest)`. You can also get back
    a list of `FileContent` objects by using `Get(DigestContents, Digest)`.
    """

    path: str
    content: bytes
    is_executable: bool = False

    def __repr__(self) -> str:
        return (
            f"FileContent(path={self.path}, content=(len:{len(self.content)}), "
            f"is_executable={self.is_executable})"
        )


@dataclass(frozen=True)
class FileEntry:
    """An indirect reference to the content of a file by digest.

    This can be used to create a new Digest with `Get(Digest, CreateDigest)`. You can also get back
    a list of `FileEntry` objects by using `Get(DigestEntries, Digest)`.
    """

    path: str
    file_digest: FileDigest
    is_executable: bool = False


@dataclass(frozen=True)
class Directory:
    """The path to a directory.

    This can be used to create empty directories with `Get(Digest, CreateDigest)`.
    """

    path: str

    def __repr__(self) -> str:
        return f"Directory({repr(self.path)})"


class DigestContents(Collection[FileContent]):
    """The file contents of a Digest.

    Although the contents of the Digest are not memoized across `@rules` or across runs (each
    request for `DigestContents` will load the file content from disk), this API should still
    generally only be used for small inputs, since concurrency might mean that very many `@rule`s
    are holding `DigestContents` simultaneously.
    """


class DigestEntries(Collection[Union[FileEntry, Directory]]):
    """The indirect file contents of a Digest.

    DigestEntries is a collection of FileContent and Directory instances representing, respecively,
    actual files and empty directories present in the Digest.
    """


class CreateDigest(Collection[Union[FileContent, FileEntry, Directory]]):
    """A request to create a Digest with the input FileContent and/or Directory values.

    The engine will create any parent directories necessary, e.g. `FileContent('a/b/c.txt')` will
    result in `a/`, `a/b`, and `a/b/c.txt` being created. You only need to use `Directory` to
    create an empty directory.

    This does _not_ actually materialize the digest to the build root. You must use
    `engine.fs.Workspace` in a `@goal_rule` to save the resulting digest to disk.
    """


class GlobExpansionConjunction(Enum):
    """Describe whether to require that only some or all glob strings match in a target's sources.

    NB: this object is interpreted from within Snapshot::lift_path_globs() -- that method will need to
    be aware of any changes to this object's definition.
    """

    any_match = "any_match"
    all_match = "all_match"


@frozen_after_init
@dataclass(unsafe_hash=True)
class PathGlobs:
    globs: Tuple[str, ...]
    glob_match_error_behavior: GlobMatchErrorBehavior
    conjunction: GlobExpansionConjunction
    description_of_origin: str | None

    def __init__(
        self,
        globs: Iterable[str],
        glob_match_error_behavior: GlobMatchErrorBehavior = GlobMatchErrorBehavior.ignore,
        conjunction: GlobExpansionConjunction = GlobExpansionConjunction.any_match,
        description_of_origin: str | None = None,
    ) -> None:
        """A request to find files given a set of globs.

        The syntax supported is roughly Git's glob syntax. Use `*` for globs, `**` for recursive
        globs, and `!` for ignores.

        :param globs: globs to match, e.g. `foo.txt` or `**/*.txt`. To exclude something, prefix it
            with `!`, e.g. `!ignore.py`.
        :param glob_match_error_behavior: whether to warn or error upon match failures
        :param conjunction: whether all `globs` must match or only at least one must match
        :param description_of_origin: a human-friendly description of where this PathGlobs request
            is coming from, used to improve the error message for unmatched globs. For example,
            this might be the text string "the option `--isort-config`".
        """

        # NB: this object is interpreted from within Snapshot::lift_path_globs() -- that method
        # will need to be aware of any changes to this object's definition.
        self.globs = tuple(sorted(globs))
        self.glob_match_error_behavior = glob_match_error_behavior
        self.conjunction = conjunction
        self.description_of_origin = description_of_origin
        self.__post_init__()

    def __post_init__(self) -> None:
        if self.glob_match_error_behavior == GlobMatchErrorBehavior.ignore:
            if self.description_of_origin:
                raise ValueError(
                    "You provided a `description_of_origin` value when `glob_match_error_behavior` "
                    "is set to `ignore`. The `ignore` value means that the engine will never "
                    "generate an error when the globs are generated, so `description_of_origin` "
                    "won't end up ever being used. Please either change "
                    "`glob_match_error_behavior` to `warn` or `error`, or remove "
                    "`description_of_origin`."
                )
        else:
            if not self.description_of_origin:
                raise ValueError(
                    "Please provide a `description_of_origin` so that the error message is more "
                    "helpful to users when their globs fail to match."
                )


@dataclass(frozen=True)
class PathGlobsAndRoot:
    """A set of PathGlobs to capture relative to some root (which may exist outside of the
    buildroot).

    If the `digest_hint` is set, it must be the Digest that we would expect to get if we were to
    expand and Digest the globs. The hint is an optimization that allows for bypassing filesystem
    operations in cases where the expected Digest is known, and the content for the Digest is
    already stored.
    """

    path_globs: PathGlobs
    root: str
    digest_hint: Optional[Digest] = None


@dataclass(frozen=True)
class DigestSubset:
    """A request to get a subset of a digest.

    Example:

        result = await Get(Digest, DigestSubset(original_digest, PathGlobs(["subdir1", "f.txt"]))
    """

    digest: Digest
    globs: PathGlobs


@dataclass(frozen=True)
class DownloadFile:
    """Retrieve the contents of a file via an HTTP GET request or directly for local file:// URLs.

    To compute the `expected_digest`, manually download the file, then run `shasum -a 256` to
    compute the fingerprint and `wc -c` to compute the expected length of the downloaded file in
    bytes.
    """

    url: str
    expected_digest: FileDigest


@dataclass(frozen=True)
class Workspace(SideEffecting):
    """A handle for operations that mutate the local filesystem."""

    _scheduler: "SchedulerSession"
    _enforce_effects: bool = True

    def write_digest(
        self, digest: Digest, *, path_prefix: Optional[str] = None, side_effecting: bool = True
    ) -> None:
        """Write a digest to disk, relative to the build root.

        You should not use this in a `for` loop due to slow performance. Instead, call `await
        Get(Digest, MergeDigests)` beforehand.

        As an advanced usecase, if the digest is known to be written to a temporary or idempotent
        location, side_effecting=False may be passed to avoid tracking this write as a side effect.
        """
        if side_effecting:
            self.side_effected()
        self._scheduler.write_digest(digest, path_prefix=path_prefix)


@dataclass(frozen=True)
class SpecsPaths(Paths):
    """All files matched by command line specs.

    `@goal_rule`s may request this when they only need source files to operate and do not need any
    target information. This allows running on files with no owning targets.
    """


@dataclass(frozen=True)
class SnapshotDiff:
    our_unique_files: tuple[str, ...] = ()
    our_unique_dirs: tuple[str, ...] = ()
    their_unique_files: tuple[str, ...] = ()
    their_unique_dirs: tuple[str, ...] = ()
    changed_files: tuple[str, ...] = ()

    @classmethod
    def from_snapshots(cls, ours: Snapshot, theirs: Snapshot) -> "SnapshotDiff":
        return cls(*ours._diff(theirs))


def rules():
    # Keep in sync with `intrinsics.rs`.
    return (
        QueryRule(Digest, (CreateDigest,)),
        QueryRule(Digest, (PathGlobs,)),
        QueryRule(Digest, (AddPrefix,)),
        QueryRule(Digest, (RemovePrefix,)),
        QueryRule(Digest, (DownloadFile,)),
        QueryRule(Digest, (MergeDigests,)),
        QueryRule(Digest, (DigestSubset,)),
        QueryRule(DigestContents, (Digest,)),
        QueryRule(Snapshot, (Digest,)),
        QueryRule(Paths, (PathGlobs,)),
    )
