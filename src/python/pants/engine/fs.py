# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pants.engine.objects import Collection
from pants.engine.rules import RootRule
from pants.option.custom_types import GlobExpansionConjunction
from pants.option.global_options import GlobMatchErrorBehavior
from pants.util.dirutil import maybe_read_file, safe_delete, safe_file_dump
from pants.util.objects import Exactly, datatype


class FileContent(datatype([('path', str), ('content', bytes), ('is_executable', bool)])):
  """The content of a file."""

  def __repr__(self):
    return 'FileContent(path={}, content=(len:{}), is_executable={})'.format(
      self.path,
      len(self.content),
      self.is_executable,
    )

  def __str__(self):
    return repr(self)


FilesContent = Collection.of(FileContent)


class InputFilesContent(FilesContent):
  """A newtype wrapper for FilesContent.
  TODO(7710): This class is currently necessary because the engine
  otherwise finds a cycle between FilesContent <=> DirectoryDigest.
  """


class PathGlobs(datatype([
    'include',
    'exclude',
    ('glob_match_error_behavior', GlobMatchErrorBehavior),
    ('conjunction', GlobExpansionConjunction),
])):
  """A wrapper around sets of filespecs to include and exclude.

  The syntax supported is roughly git's glob syntax.

  NB: this object is interpreted from within Snapshot::lift_path_globs() -- that method will need to
  be aware of any changes to this object's definition.
  """

  def __new__(cls, include, exclude=(), glob_match_error_behavior=None, conjunction=None):
    """Given various file patterns create a PathGlobs object (without using filesystem operations).

    :param include: A list of filespecs to include.
    :param exclude: A list of filespecs to exclude.
    :param GlobMatchErrorBehavior glob_match_error_behavior: How to respond to globs matching no
                                                             files.
    :param GlobExpansionConjunction conjunction: Whether all globs are expected to match at least
                                                 one file, or if any glob matching is ok.
    :rtype: :class:`PathGlobs`
    """
    return super().__new__(
      cls,
      include=tuple(include),
      exclude=tuple(exclude),
      glob_match_error_behavior=(glob_match_error_behavior or GlobMatchErrorBehavior.ignore),
      conjunction=(conjunction or GlobExpansionConjunction.any_match))


class Digest(datatype([('fingerprint', str), ('serialized_bytes_length', int)])):
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

  def __repr__(self):
    return '''Digest(fingerprint={}, serialized_bytes_length={})'''.format(
      self.fingerprint,
      self.serialized_bytes_length
    )

  def __str__(self):
    return repr(self)


class PathGlobsAndRoot(datatype([
    ('path_globs', PathGlobs),
    ('root', str),
    ('digest_hint', Exactly(Digest, type(None))),
])):
  """A set of PathGlobs to capture relative to some root (which may exist outside of the buildroot).

  If the `digest_hint` is set, it must be the Digest that we would expect to get if we were to
  expand and Digest the globs. The hint is an optimization that allows for bypassing filesystem
  operations in cases where the expected Digest is known, and the content for the Digest is already
  stored.
  """

  def __new__(cls, path_globs, root, digest_hint=None):
    return super().__new__(cls, path_globs, root, digest_hint)


class Snapshot(datatype([('directory_digest', Digest), ('files', tuple), ('dirs', tuple)])):
  """A Snapshot is a collection of file paths and dir paths fingerprinted by their names/content.

  Snapshots are used to make it easier to isolate process execution by fixing the contents
  of the files being operated on and easing their movement to and from isolated execution
  sandboxes.
  """

  @property
  def is_empty(self):
    return self == EMPTY_SNAPSHOT


class DirectoriesToMerge(datatype([('directories', tuple)])):
  pass


class DirectoryWithPrefixToStrip(datatype([('directory_digest', Digest), ('prefix', str)])):
  pass


class DirectoryToMaterialize(datatype([('path', str), ('directory_digest', Digest)])):
  """A request to materialize the contents of a directory digest at the provided path."""
  pass


class UrlToFetch(datatype([('url', str), ('digest', Digest)])):
  pass


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
    RootRule(InputFilesContent),
    RootRule(Digest),
    RootRule(DirectoriesToMerge),
    RootRule(PathGlobs),
    RootRule(DirectoryWithPrefixToStrip),
    RootRule(UrlToFetch),
  ]
