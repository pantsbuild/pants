# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from abc import abstractmethod
from collections import OrderedDict
from zipfile import ZIP_DEFLATED

from pants.util.contextutil import open_tar, open_zip
from pants.util.dirutil import safe_walk
from pants.util.meta import AbstractClass
from pants.util.strutil import ensure_text


"""Support for wholesale archive creation and extraction in a uniform API across archive types."""


class Archiver(AbstractClass):

  @classmethod
  def extract(cls, path, outdir):
    """Extracts an archive's contents to the specified outdir."""
    raise NotImplementedError()

  @abstractmethod
  def create(self, basedir, outdir, name, prefix=None):
    """Creates an archive of all files found under basedir to a file at outdir of the given name.

    If prefix is specified, it should be prepended to all archive paths.
    """


class TarArchiver(Archiver):
  """An archiver that stores files in a tar file with optional compression."""

  @classmethod
  def extract(cls, path, outdir):
    with open_tar(path, errorlevel=1) as tar:
      tar.extractall(outdir)

  def __init__(self, mode, extension):
    Archiver.__init__(self)
    self.mode = mode
    self.extension = extension

  def create(self, basedir, outdir, name, prefix=None):
    basedir = ensure_text(basedir)
    tarpath = os.path.join(outdir, '{}.{}'.format(ensure_text(name), self.extension))
    with open_tar(tarpath, self.mode, dereference=True, errorlevel=1) as tar:
      tar.add(basedir, arcname=prefix or '.')
    return tarpath


class ZipArchiver(Archiver):
  """An archiver that stores files in a zip file with optional compression."""

  @classmethod
  def extract(cls, path, outdir, filter_func=None):
    """Extract from a zip file, with an optional filter

    :param string path: path to the zipfile to extract from
    :param string outdir: directory to extract files into
    :param function filter_func: optional filter with the filename as the parameter.  Returns True if
      the file should be extracted.
    """
    with open_zip(path) as archive_file:
      for name in archive_file.namelist():
        # While we're at it, we also perform this safety test.
        if name.startswith(b'/') or name.startswith(b'..'):
          raise ValueError('Zip file contains unsafe path: {}'.format(name))
        # Ignore directories. extract() will create parent dirs as needed.
        # OS X's python 2.6.1 has a bug in zipfile that makes it unzip directories as regular files.
        # This method should work on for python 2.6-3.x.
        # TODO(Eric Ayers) Pants no longer builds with python 2.6. Can this be removed?
        if not name.endswith(b'/'):
          if (not filter_func or filter_func(name)):
            archive_file.extract(name, outdir)

  def __init__(self, compression):
    Archiver.__init__(self)
    self.compression = compression

  def create(self, basedir, outdir, name, prefix=None):
    zippath = os.path.join(outdir, '{}.zip'.format(name))
    with open_zip(zippath, 'w', compression=ZIP_DEFLATED) as zip:
      for root, _, files in safe_walk(basedir):
        root = ensure_text(root)
        for file in files:
          file = ensure_text(file)
          full_path = os.path.join(root, file)
          relpath = os.path.relpath(full_path, basedir)
          if prefix:
            relpath = os.path.join(ensure_text(prefix), relpath)
          zip.write(full_path, relpath)
    return zippath


TAR = TarArchiver('w:', 'tar')
TGZ = TarArchiver('w:gz', 'tar.gz')
TBZ2 = TarArchiver('w:bz2', 'tar.bz2')
ZIP = ZipArchiver(ZIP_DEFLATED)

_ARCHIVER_BY_TYPE = OrderedDict(tar=TAR, tgz=TGZ, tbz2=TBZ2, zip=ZIP)

TYPE_NAMES = frozenset(_ARCHIVER_BY_TYPE.keys())


def archiver(typename):
  """Returns Archivers in common configurations.

  The typename must correspond to one of the following:
  'tar'   Returns a tar archiver that applies no compression and emits .tar files.
  'tgz'   Returns a tar archiver that applies gzip compression and emits .tar.gz files.
  'tbz2'  Returns a tar archiver that applies bzip2 compression and emits .tar.bz2 files.
  'zip'   Returns a zip archiver that applies standard compression and emits .zip files.
  """
  archiver = _ARCHIVER_BY_TYPE.get(typename)
  if not archiver:
    raise ValueError('No archiver registered for {!r}'.format(typename))
  return archiver


def archiver_for_path(path_name):
  """Returns an Archiver for the given path name.

  :param string path_name: The path name of the archive - need not exist.
  :raises: :class:`ValueError` If the path name does not uniquely identify a supported archive type.
  """
  if path_name.endswith('.tar.gz'):
    return TGZ
  elif path_name.endswith('.tar.bz2'):
    return TBZ2
  else:
    _, ext = os.path.splitext(path_name)
    if ext:
      ext = ext[1:]  # Trim leading '.'.
    if not ext:
      raise ValueError('Could not determine archive type of path {}'.format(path_name))
    return archiver(ext)
