# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os

from future.utils import binary_type, text_type

from pants.engine.objects import Collection
from pants.engine.rules import RootRule
from pants.option.custom_types import GlobExpansionConjunction
from pants.option.global_options import GlobMatchErrorBehavior
from pants.util.dirutil import maybe_read_file, safe_delete, safe_file_dump
from pants.util.objects import Exactly, datatype


class FileContent(datatype([('path', text_type), ('content', binary_type)])):
  """The content of a file."""

  def __repr__(self):
    return 'FileContent(path={}, content=(len:{}))'.format(self.path, len(self.content))

  def __str__(self):
    return repr(self)


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
    return super(PathGlobs, cls).__new__(
      cls,
      include=tuple(include),
      exclude=tuple(exclude),
      glob_match_error_behavior=(glob_match_error_behavior or GlobMatchErrorBehavior.ignore),
      conjunction=(conjunction or GlobExpansionConjunction.any_match))


class Digest(datatype([('fingerprint', text_type), ('serialized_bytes_length', int)])):
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
  def _path(cls, directory):
    return '{}.digest'.format(directory.rstrip(os.sep))

  @classmethod
  def clear(cls, directory):
    """Clear any existing Digest file adjacent to the given directory."""
    safe_delete(cls._path(directory))

  @classmethod
  def load(cls, directory):
    """Load a Digest from a `.digest` file adjacent to the given directory.

    :return: A Digest, or None if the Digest did not exist.
    """
    read_file = maybe_read_file(cls._path(directory))
    if read_file:
      fingerprint, length = read_file.split(':')
      return Digest(fingerprint, int(length))
    else:
      return None

  def dump(self, directory):
    """Dump this Digest object adjacent to the given directory."""
    payload = '{}:{}'.format(self.fingerprint, self.serialized_bytes_length)
    safe_file_dump(self._path(directory), payload=payload)

  def __repr__(self):
    return '''Digest(fingerprint={}, serialized_bytes_length={})'''.format(
      self.fingerprint,
      self.serialized_bytes_length
    )

  def __str__(self):
    return repr(self)


class PathGlobsAndRoot(datatype([
    ('path_globs', PathGlobs),
    ('root', text_type),
    ('digest_hint', Exactly(Digest, type(None))),
])):
  """A set of PathGlobs to capture relative to some root (which may exist outside of the buildroot).

  If the `digest_hint` is set, it must be the Digest that we would expect to get if we were to
  expand and Digest the globs. The hint is an optimization that allows for bypassing filesystem
  operations in cases where the expected Digest is known, and the content for the Digest is already
  stored.
  """

  def __new__(cls, path_globs, root, digest_hint=None):
    return super(PathGlobsAndRoot, cls).__new__(cls, path_globs, root, digest_hint)


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


class DirectoryWithPrefixToStrip(datatype([('directory_digest', Digest), ('prefix', text_type)])):
  pass


class DirectoryToMaterialize(datatype([('path', text_type), ('directory_digest', Digest)])):
  """A request to materialize the contents of a directory digest at the provided path."""
  pass


class UrlToFetch(datatype([('url', text_type), ('digest', Digest)])):
  pass


FilesContent = Collection.of(FileContent)


# TODO: don't recreate this in python, get this from fs::EMPTY_DIGEST somehow.
_EMPTY_FINGERPRINT = 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'


EMPTY_DIRECTORY_DIGEST = Digest(
  fingerprint=text_type(_EMPTY_FINGERPRINT),
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
    RootRule(Digest),
    RootRule(DirectoriesToMerge),
    RootRule(PathGlobs),
    RootRule(DirectoryWithPrefixToStrip),
    RootRule(UrlToFetch),
  ]
