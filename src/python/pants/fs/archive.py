# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import gzip
import os
import re
import shutil
from abc import abstractmethod
from collections import OrderedDict
from zipfile import ZIP_DEFLATED

import lzma

from pants.util.contextutil import open_tar, open_zip, temporary_dir
from pants.util.dirutil import safe_concurrent_rename, safe_walk
from pants.util.meta import AbstractClass
from pants.util.strutil import ensure_text


"""Support for wholesale archive creation and extraction in a uniform API across archive types."""


class Archiver(AbstractClass):

  @classmethod
  def extract(cls, path, outdir, filter_func=None, concurrency_safe=False):
    """Extracts an archive's contents to the specified outdir with an optional filter.

    :API: public

    :param string path: path to the zipfile to extract from
    :param string outdir: directory to extract files into
    :param function filter_func: optional filter with the filename as the parameter.  Returns True
      if the file should be extracted.  Note that filter_func is ignored for non-zip archives.
    :param bool concurrency_safe: True to use concurrency safe method.  Concurrency safe extraction
      will be performed on a temporary directory and the extacted directory will then be renamed
      atomically to the outdir.  As a side effect, concurrency safe extraction will not allow
      overlay of extracted contents onto an existing outdir.
    """
    if concurrency_safe:
      with temporary_dir() as temp_dir:
        cls._extract(path, temp_dir, filter_func=filter_func)
        safe_concurrent_rename(temp_dir, outdir)
    else:
      # Leave the existing default behavior unchanged and allows overlay of contents.
      cls._extract(path, outdir, filter_func=filter_func)

  @classmethod
  def _extract(cls, path, outdir):
    raise NotImplementedError()

  @abstractmethod
  def create(self, basedir, outdir, name, prefix=None):
    """Creates an archive of all files found under basedir to a file at outdir of the given name.

    If prefix is specified, it should be prepended to all archive paths.
    """

  def __init__(self, extension):
    self.extension = extension


class TarArchiver(Archiver):
  """An archiver that stores files in a tar file with optional compression.

  :API: public
  """

  @classmethod
  def _extract(cls, path, outdir, **kwargs):
    with open_tar(path, errorlevel=1) as tar:
      tar.extractall(outdir)

  def __init__(self, mode, extension):
    """
    :API: public
    """
    super(TarArchiver, self).__init__(extension)
    self.mode = mode
    self.extension = extension

  def create(self, basedir, outdir, name, prefix=None, dereference=True):
    """
    :API: public
    """

    basedir = ensure_text(basedir)
    tarpath = os.path.join(outdir, '{}.{}'.format(ensure_text(name), self.extension))
    with open_tar(tarpath, self.mode, dereference=dereference, errorlevel=1) as tar:
      tar.add(basedir, arcname=prefix or '.')
    return tarpath


class XZCompressedTarArchiver(TarArchiver):
  """A workaround for the lack of xz support in Python 2.7.

  Upon receiving a request to extract a file located at <base>.tar.gz, this class will instead
  decompress the file <base>.tar.xz, then re-compress it with gzip to write into the adjacent
  <base>.tar.gz. <base>.tar.gz will then be extracted as usual.
  """

  def __init__(self):
    super(XZCompressedTarArchiver, self).__init__('w:gz', 'tar.gz')

  _TAR_GZ_PATTERN = re.compile('\.tar\.gz\Z')

  @classmethod
  def _get_xz_file_path(cls, path):
    if not cls._TAR_GZ_PATTERN.search(path):
      # TODO: test this! fix this message!
      raise ValueError("path {!r} must end in .tar.gz.".format(path))
    return cls._TAR_GZ_PATTERN.sub('.tar.xz', path)

  @classmethod
  def _extract(cls, path, outdir, **kwargs):
    xz_path = cls._get_xz_file_path(path)
    shutil.move(path, xz_path)
    with lzma.LZMAFile(xz_path) as xz_infile, open(path, 'wb') as gz_out_raw:
      with gzip.GzipFile('wb', fileobj=gz_out_raw) as gz_outfile:
        shutil.copyfileobj(xz_infile, gz_outfile)
    return super(XZCompressedTarArchiver, cls)._extract(path, outdir, **kwargs)


class ZipArchiver(Archiver):
  """An archiver that stores files in a zip file with optional compression.

  :API: public
  """

  @classmethod
  def _extract(cls, path, outdir, filter_func=None, **kwargs):
    """Extract from a zip file, with an optional filter."""
    with open_zip(path) as archive_file:
      for name in archive_file.namelist():
        # While we're at it, we also perform this safety test.
        if name.startswith(b'/') or name.startswith(b'..'):
          raise ValueError('Zip file contains unsafe path: {}'.format(name))
        if (not filter_func or filter_func(name)):
          archive_file.extract(name, outdir)

  def __init__(self, compression, extension):
    """
    :API: public
    """
    super(ZipArchiver, self).__init__(extension)
    self.compression = compression
    self.extension = extension

  def create(self, basedir, outdir, name, prefix=None):
    """
    :API: public
    """
    zippath = os.path.join(outdir, '{}.{}'.format(name, self.extension))
    with open_zip(zippath, 'w', compression=self.compression) as zip:
      # For symlinks, we want to archive the actual content of linked files but
      # under the relpath derived from symlink.
      for root, _, files in safe_walk(basedir, followlinks=True):
        root = ensure_text(root)
        for file in files:
          file = ensure_text(file)
          full_path = os.path.join(root, file)
          relpath = os.path.relpath(full_path, basedir)
          if prefix:
            relpath = os.path.join(ensure_text(prefix), relpath)
          zip.write(full_path, relpath)
    return zippath

def _make_tar_archiver(compression_type):
  compression_spec = 'w:{}'.format(compression_type)
  extension = 'tar.{}'.format(compression_type)
  return TarArchiver(compression_spec, extension)

TAR = _make_tar_archiver('')
TGZ = _make_tar_archiver('gz')
TBZ2 = _make_tar_archiver('bz2')
TXZ = XZCompressedTarArchiver()
ZIP = ZipArchiver(ZIP_DEFLATED, 'zip')

_ARCHIVER_BY_TYPE = OrderedDict(
  tar=TAR,
  tgz=TGZ,
  tbz2=TBZ2,
  txz=TXZ,
  zip=ZIP)

TYPE_NAMES = frozenset(_ARCHIVER_BY_TYPE.keys())
TYPE_NAMES_NO_PRESERVE_SYMLINKS = frozenset(['zip'])
TYPE_NAMES_PRESERVE_SYMLINKS = TYPE_NAMES - TYPE_NAMES_NO_PRESERVE_SYMLINKS


# TODO: Rename to `create_archiver`. Pretty much every caller of this method is going
# to want to put the return value into a variable named `archiver`.
def archiver(typename):
  """Returns Archivers in common configurations.

  :API: public

  The typename must correspond to one of the following:
  'tar'   Returns a tar archiver that applies no compression and emits .tar files.
  'tgz'   Returns a tar archiver that applies gzip compression and emits .tar.gz files.
  'tbz2'  Returns a tar archiver that applies bzip2 compression and emits .tar.bz2 files.
  'zip'   Returns a zip archiver that applies standard compression and emits .zip files.
  'jar'   Returns a jar archiver that applies no compression and emits .jar files.
    Note this is provided as a light way of zipping input files into a jar, without the
    need to prepare Manifest etc. For more advanced usages, please refer to :class:
    `pants.backend.jvm.subsystems.jar_tool.JarTool` or :class:
    `pants.backend.jvm.tasks.jar_task.JarTask`.
  """
  archiver = _ARCHIVER_BY_TYPE.get(typename)
  if not archiver:
    raise ValueError('No archiver registered for {!r}'.format(typename))
  return archiver


def archiver_for_path(path_name):
  """Returns an Archiver for the given path name.

  :API: public

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
