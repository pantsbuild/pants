# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from dataclasses import dataclass
from typing import Any, Iterable, Optional, Tuple

from pants.engine.objects import Collection
from pants.engine.rules import RootRule
from pants.option.custom_types import GlobExpansionConjunction
from pants.option.global_options import GlobMatchErrorBehavior
from pants.util.dirutil import maybe_read_file, safe_delete, safe_file_dump
from pants.util.meta import frozen_after_init


@dataclass(frozen=True)
class FileContent:
  """The content of a file."""
  path: str
  content: bytes
  is_executable: bool

  def __repr__(self):
    return 'FileContent(path={}, content=(len:{}), is_executable={})'.format(
      self.path,
      len(self.content),
      self.is_executable,
    )


FilesContent = Collection.of(FileContent)


class InputFilesContent(FilesContent):
  """A newtype wrapper for FilesContent.
  TODO(7710): This class is currently necessary because the engine
  otherwise finds a cycle between FilesContent <=> DirectoryDigest.
  """


@frozen_after_init
@dataclass(unsafe_hash=True)
class PathGlobs:
  """A wrapper around sets of filespecs to include and exclude.

  The syntax supported is roughly git's glob syntax.

  NB: this object is interpreted from within Snapshot::lift_path_globs() -- that method will need to
  be aware of any changes to this object's definition.
  """
  include: Tuple[str, ...]
  exclude: Tuple[str, ...]
  glob_match_error_behavior: GlobMatchErrorBehavior
  conjunction: GlobExpansionConjunction

  def __init__(
    self,
    include: Iterable[str],
    exclude: Iterable[str] = (),
    glob_match_error_behavior: GlobMatchErrorBehavior = GlobMatchErrorBehavior.ignore,
    conjunction: GlobExpansionConjunction = GlobExpansionConjunction.any_match
  ) -> None:
    self.include = tuple(include)
    self.exclude = tuple(exclude)
    self.glob_match_error_behavior = glob_match_error_behavior
    self.conjunction = conjunction


@dataclass(frozen=True)
class Digest:
  """A Digest is a content-digest fingerprint, and a length of underlying content.

  These are used both to reference digests of strings/bytes/content, and as an opaque handle to a
  set of files known about by the engine.

  The contents of file sets referenced opaquely can be inspected by requesting a FilesContent for
  it.

  In the future, it will be possible to inspect the file metadata by requesting a Snapshot for it,
  but at the moment we can't install rules which go both:
   PathGlobs -> Digest -> Snapshot
   PathGlobs -> Snapshot
  because it would lead to an ambiguity in the engine, and we have existing code which already
  relies on the latter existing. This can be resolved when ordering is removed from Snapshots. See
  https://github.com/pantsbuild/pants/issues/5802
  """
  fingerprint: str
  serialized_bytes_length: int

  @classmethod
  def _path(cls, digested_path):
    return '{}.digest'.format(digested_path.rstrip(os.sep))

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
      fingerprint, length = read_file.split(':')
      return Digest(fingerprint, int(length))
    else:
      return None

  def dump(self, digested_path):
    """Dump this Digest object adjacent to the given digested_path."""
    payload = '{}:{}'.format(self.fingerprint, self.serialized_bytes_length)
    safe_file_dump(self._path(digested_path), payload=payload)


@dataclass(frozen=True)
class PathGlobsAndRoot:
  """A set of PathGlobs to capture relative to some root (which may exist outside of the buildroot).

  If the `digest_hint` is set, it must be the Digest that we would expect to get if we were to
  expand and Digest the globs. The hint is an optimization that allows for bypassing filesystem
  operations in cases where the expected Digest is known, and the content for the Digest is already
  stored.
  """
  path_globs: PathGlobs
  root: str
  digest_hint: Optional[Digest] = None


@dataclass(frozen=True)
class Snapshot:
  """A Snapshot is a collection of file paths and dir paths fingerprinted by their names/content.

  Snapshots are used to make it easier to isolate process execution by fixing the contents
  of the files being operated on and easing their movement to and from isolated execution
  sandboxes.
  """
  directory_digest: Digest
  files: Tuple[str, ...]
  dirs: Tuple[str, ...]

  @property
  def is_empty(self):
    return self == EMPTY_SNAPSHOT


@dataclass(frozen=True)
class DirectoriesToMerge:
  directories: Tuple


@dataclass(frozen=True)
class DirectoryWithPrefixToStrip:
  directory_digest: Digest
  prefix: str


@dataclass(frozen=True)
class DirectoryWithPrefixToAdd:
  directory_digest: Digest
  prefix: str


@dataclass(frozen=True)
class DirectoryToMaterialize:
  """A request to materialize the contents of a directory digest at the provided path."""
  path: str
  directory_digest: Digest


DirectoriesToMaterialize = Collection.of(DirectoryToMaterialize)


@dataclass(frozen=True)
class MaterializeDirectoryResult:
  """Result of materializing a directory, contains the full output paths."""
  output_paths: Tuple[str, ...]


MaterializeDirectoriesResult = Collection.of(MaterializeDirectoryResult)


@dataclass(frozen=True)
class UrlToFetch:
  url: str
  digest: Digest


@dataclass(frozen=True)
class Workspace:
  """Abstract handle for operations that touch the real local filesystem."""
  _scheduler: Any

  def materialize_directories(self, directories_to_materialize: Tuple[DirectoryToMaterialize, ...]) -> MaterializeDirectoriesResult:
    return self._scheduler.materialize_directories(directories_to_materialize)


# TODO: don't recreate this in python, get this from fs::EMPTY_DIGEST somehow.
_EMPTY_FINGERPRINT = 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'


EMPTY_DIRECTORY_DIGEST = Digest(
  fingerprint=_EMPTY_FINGERPRINT,
  serialized_bytes_length=0
)

EMPTY_SNAPSHOT = Snapshot(
  directory_digest=EMPTY_DIRECTORY_DIGEST,
  files=(),
  dirs=()
)


def create_fs_rules():
  """Creates rules that consume the intrinsic filesystem types."""
  return [
    RootRule(Workspace),
    RootRule(InputFilesContent),
    RootRule(Digest),
    RootRule(DirectoriesToMerge),
    RootRule(PathGlobs),
    RootRule(DirectoryWithPrefixToStrip),
    RootRule(DirectoryWithPrefixToAdd),
    RootRule(UrlToFetch),
  ]
