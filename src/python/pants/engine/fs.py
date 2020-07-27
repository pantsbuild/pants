# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable, Optional, Tuple

from pants.engine.collection import Collection
from pants.engine.rules import RootRule, side_effecting
from pants.option.custom_types import GlobExpansionConjunction as GlobExpansionConjunction
from pants.option.global_options import GlobMatchErrorBehavior as GlobMatchErrorBehavior
from pants.util.dirutil import maybe_read_file, safe_delete, safe_file_dump
from pants.util.meta import frozen_after_init

if TYPE_CHECKING:
    from pants.engine.internals.scheduler import SchedulerSession


@dataclass(frozen=True)
class FileContent:
    """The content of a file."""

    path: str
    content: bytes
    is_executable: bool = False

    def __repr__(self) -> str:
        return f"FileContent(path={self.path}, content=(len:{len(self.content)}), is_executable={self.is_executable})"


class DigestContents(Collection[FileContent]):
    """The file contents of a Digest."""


class CreateDigest(Collection[FileContent]):
    """A request to create a Digest with the input FileContent values.

    This does _not_ actually materialize the digest to the build root. You must use
    `engine.fs.Workspace` in a `@goal_rule` to save the resulting digest to disk.
    """


@frozen_after_init
@dataclass(unsafe_hash=True)
class PathGlobs:
    """A wrapper around sets of filespecs to include and exclude.

    The syntax supported is roughly Git's glob syntax.

    NB: this object is interpreted from within Snapshot::lift_path_globs() -- that method will need
    to be aware of any changes to this object's definition.
    """

    globs: Tuple[str, ...]
    glob_match_error_behavior: GlobMatchErrorBehavior
    conjunction: GlobExpansionConjunction
    description_of_origin: str

    def __init__(
        self,
        globs: Iterable[str],
        glob_match_error_behavior: GlobMatchErrorBehavior = GlobMatchErrorBehavior.ignore,
        conjunction: GlobExpansionConjunction = GlobExpansionConjunction.any_match,
        description_of_origin: Optional[str] = None,
    ) -> None:
        """
        :param globs: globs to match, e.g. `foo.txt` or `**/*.txt`. To exclude something, prefix it
                      with `!`, e.g. `!ignore.py`.
        :param glob_match_error_behavior: whether to warn or error upon match failures
        :param conjunction: whether all `globs` must match or only at least one must match
        :param description_of_origin: a human-friendly description of where this PathGlobs request
                                      is coming from, used to improve the error message for
                                      unmatched globs. For example, this might be the text string
                                      "the option `--isort-config`".
        """
        self.globs = tuple(sorted(globs))
        self.glob_match_error_behavior = glob_match_error_behavior
        self.conjunction = conjunction
        self.description_of_origin = description_of_origin or ""
        self.__post_init__()

    def __post_init__(self) -> None:
        if self.glob_match_error_behavior == GlobMatchErrorBehavior.ignore:
            if self.description_of_origin:
                raise ValueError(
                    "You provided a `description_of_origin` value when `glob_match_error_behavior` is set to "
                    "`ignore`. The `ignore` value means that the engine will never generate an error when "
                    "the globs are generated, so `description_of_origin` won't end up ever being used. "
                    "Please either change `glob_match_error_behavior` to `warn` or `error`, or remove "
                    "`description_of_origin`."
                )
        else:
            if not self.description_of_origin:
                raise ValueError(
                    "Please provide a `description_of_origin` so that the error message is more helpful to "
                    "users when their globs fail to match."
                )


@dataclass(frozen=True)
class Digest:
    """A Digest is a content-digest fingerprint, and a length of underlying content.

    These are used both to reference digests of strings/bytes/content, and as an opaque handle to a
    set of files known about by the engine.

    The contents of file sets referenced opaquely can be inspected by requesting a FilesContent for
    it.
    """

    fingerprint: str
    serialized_bytes_length: int

    @classmethod
    def _path(cls, digested_path):
        return f"{digested_path.rstrip(os.sep)}.digest"

    @classmethod
    def clear(cls, digested_path):
        """Clear any existing Digest file adjacent to the given digested_path."""
        safe_delete(cls._path(digested_path))

    @classmethod
    def load(cls, digested_path):
        """Load a Digest from a `.digest` file adjacent to the given digested_path.

        :return: A Digest, or None if the Digest did not exist.
        """
        read_file = maybe_read_file(cls._path(digested_path))
        if read_file:
            fingerprint, length = read_file.split(":")
            return Digest(fingerprint, int(length))
        else:
            return None

    def dump(self, digested_path):
        """Dump this Digest object adjacent to the given digested_path."""
        payload = f"{self.fingerprint}:{self.serialized_bytes_length}"
        safe_file_dump(self._path(digested_path), payload=payload)


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
class Snapshot:
    """A Snapshot is a collection of file paths and dir paths fingerprinted by their names/content.

    Snapshots are used to make it easier to isolate process execution by fixing the contents of the
    files being operated on and easing their movement to and from isolated execution sandboxes.
    """

    digest: Digest
    files: Tuple[str, ...]
    dirs: Tuple[str, ...]


@dataclass(frozen=True)
class DigestSubset:
    """A request to get a subset of a digest.

    Example:

        result = await Get(Digest, DigestSubset(original_digest, PathGlobs(["subdir1", "f.txt"]))
    """

    digest: Digest
    globs: PathGlobs


@dataclass(unsafe_hash=True)
class MergeDigests:
    digests: Tuple[Digest, ...]

    def __init__(self, digests: Iterable[Digest]) -> None:
        """A request to merge several digests into one single digest.

        This will fail if there are any conflicting changes, such as two digests having the same
        file but with different content.

        Example:

            result = await Get(Digest, MergeDigests([digest1, digest2])
        """
        self.digests = tuple(digests)

    def __post_init__(self) -> None:
        non_digests = [v for v in self.digests if not isinstance(v, Digest)]  # type: ignore[unreachable]
        if non_digests:
            formatted_non_digests = "\n".join(f"* {v}" for v in non_digests)
            raise ValueError(f"Not all arguments are digests:\n\n{formatted_non_digests}")


@dataclass(frozen=True)
class RemovePrefix:
    """A request to remove the specified prefix path from every file and directory in the digest.

    This will fail if there are any files or directories in the original input digest without the
    specified digest.

    Example:

        result = await Get(Digest, RemovePrefix(input_digest, "my_dir")
    """

    digest: Digest
    prefix: str


@dataclass(frozen=True)
class AddPrefix:
    """A request to add the specified prefix path to every file and directory in the digest.

    Example:

        result = await Get(Digest, AddPrefix(input_digest, "my_dir")
    """

    digest: Digest
    prefix: str


@dataclass(frozen=True)
class UrlToFetch:
    url: str
    digest: Digest


@side_effecting
@dataclass(frozen=True)
class Workspace:
    """A handle for operations that mutate the local filesystem."""

    _scheduler: "SchedulerSession"

    def write_digest(self, digest: Digest, *, path_prefix: Optional[str] = None) -> None:
        """Write a digest to disk, relative to the build root.

        You should not use this in a `for` loop due to slow performance. Instead, call `await
        Get(Digest, MergeDigests)` beforehand.
        """
        self._scheduler.write_digest(digest, path_prefix=path_prefix)


_EMPTY_FINGERPRINT = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
EMPTY_DIGEST = Digest(fingerprint=_EMPTY_FINGERPRINT, serialized_bytes_length=0)
EMPTY_SNAPSHOT = Snapshot(EMPTY_DIGEST, files=(), dirs=())


@dataclass(frozen=True)
class SourcesSnapshot:
    """Sources matched by command line specs.

    `@goal_rule`s may request this when they only need source files to operate and do not need any
    target information. This allows running on files with no owning targets.
    """

    snapshot: Snapshot


def create_fs_rules():
    """Creates rules that consume the intrinsic filesystem types."""
    return [
        RootRule(Workspace),
        RootRule(CreateDigest),
        RootRule(Digest),
        RootRule(MergeDigests),
        RootRule(PathGlobs),
        RootRule(RemovePrefix),
        RootRule(AddPrefix),
        RootRule(UrlToFetch),
        RootRule(DigestSubset),
    ]
