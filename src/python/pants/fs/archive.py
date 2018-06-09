# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import sys
from abc import abstractmethod
from collections import OrderedDict
from contextlib import contextmanager
from zipfile import ZIP_DEFLATED

from pants.util.contextutil import open_tar, open_zip, temporary_dir
from pants.util.dirutil import (is_executable, safe_concurrent_rename, safe_walk,
                                split_basename_and_dirname)
from pants.util.memo import memoized_classproperty
from pants.util.meta import AbstractClass
from pants.util.osutil import get_normalized_os_name
from pants.util.process_handler import subprocess
from pants.util.strutil import ensure_text


"""Support for wholesale archive creation and extraction in a uniform API across archive types."""


class Archiver(AbstractClass):

  def extract(self, path, outdir, concurrency_safe=False, **kwargs):
    """Extracts an archive's contents to the specified outdir with an optional filter.

    Keyword arguments are forwarded to the instance's self._extract() method.

    :API: public

    :param string path: path to the zipfile to extract from
    :param string outdir: directory to extract files into
    :param bool concurrency_safe: True to use concurrency safe method.  Concurrency safe extraction
      will be performed on a temporary directory and the extacted directory will then be renamed
      atomically to the outdir.  As a side effect, concurrency safe extraction will not allow
      overlay of extracted contents onto an existing outdir.
    """
    if concurrency_safe:
      with temporary_dir() as temp_dir:
        self._extract(path, temp_dir, **kwargs)
        safe_concurrent_rename(temp_dir, outdir)
    else:
      # Leave the existing default behavior unchanged and allows overlay of contents.
      self._extract(path, outdir, **kwargs)

  def _extract(self, path, outdir):
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

  def _extract(self, path_or_file, outdir, **kwargs):
    with open_tar(path_or_file, errorlevel=1, **kwargs) as tar:
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

  Invokes an xz executable to decompress a .tar.xz into a tar stream, which is piped into the
  extract() method.

  NB: This class will raise an error if used to create an archive! This class can only currently be
  used to extract from xz archives.
  """

  class XZArchiverError(Exception): pass

  # FIXME: move Platform#resolve_platform_specific() into somewhere common and consume it here after
  # #5815 is merged.
  @memoized_classproperty
  def _liblzma_shared_lib_filename(cls):
    normalized_os_name = get_normalized_os_name()
    if normalized_os_name == 'darwin':
      return 'liblzma.dylib'
    elif normalized_os_name == 'linux':
      return 'liblzma.so'
    else:
      raise cls.XZArchiverError("Unrecognized platform: {}.".format(normalized_os_name))

  def __init__(self, xz_binary_path, xz_library_path):

    # TODO: test these exceptions somewhere!
    if not is_executable(xz_binary_path):
      raise self.XZArchiverError(
        "The path {} does not name an existing executable file. An xz executable must be provided "
        "to decompress xz archives."
        .format(xz_binary_path))

    self._xz_binary_path = xz_binary_path

    if not os.path.isdir(xz_library_path):
      raise self.XZArchiverError(
        "The path {lib_dir} does not name an existing directory. A directory containing "
        "{dylib_filename} must be provided to decompress xz archives."
        .format(lib_dir=xz_library_path,
                dylib_filename=self._liblzma_shared_lib_filename))

    lib_lzma_dylib = os.path.join(xz_library_path, self._liblzma_shared_lib_filename)
    if not os.path.isfile(lib_lzma_dylib):
      raise self.XZArchiverError(
        "The path {lib_dir} names an existing directory, but it does not contain {dylib_filename}. "
        "A directory containing {dylib_filename} must be provided to decompress xz archives."
        .format(lib_dir=xz_library_path,
                dylib_filename=self._liblzma_shared_lib_filename))

    self._xz_library_path = xz_library_path

    super(XZCompressedTarArchiver, self).__init__('r|', 'tar.xz')

  @contextmanager
  def _invoke_xz(self, xz_input_file):
    """Run the xz command and yield a file object for its stdout.

    This allows streaming the decompressed tar archive directly into a tar decompression stream,
    which is significantly faster in practice than making a temporary file.
    """
    (xz_bin_dir, xz_filename) = split_basename_and_dirname(self._xz_binary_path)

    # FIXME: --threads=0 is supposed to use "the number of processor cores on the machine", but I
    # see no more than 100% cpu used at any point. This seems like it could be a bug? If performance
    # is an issue, investigate further.
    cmd = [xz_filename, '--decompress', '--stdout', '--keep', '--threads=0', xz_input_file]
    env = {
      # Isolate the path so we know we're using our provided version of xz.
      'PATH': xz_bin_dir,
    }

    # Only allow our xz's lib directory to resolve the liblzma.{so,dylib} dependency at runtime.
    normalized_os_name = get_normalized_os_name()
    if normalized_os_name == 'darwin':
      env['DYLD_FALLBACK_LIBRARY_PATH'] = self._xz_library_path
    elif normalized_os_name == 'linux':
      env['LD_LIBRARY_PATH'] = self._xz_library_path
    else:
      raise self.XZArchiverError("Unrecognized platform: {}.".format(normalized_os_name))

    try:
      # Pipe stderr to our own stderr, but leave stdout open so we can yield it.
      process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=sys.stderr,
        env=env)
    except OSError as e:
      raise self.XZArchiverError(
        "Error invoking xz with command {} and environment {} for input file {}: {}"
        .format(cmd, env, xz_input_file, e),
        e)

    # This is a file object.
    yield process.stdout

    rc = process.wait()
    if rc != 0:
      raise self.XZArchiverError(
        "Error decompressing xz input with command {} and environment {} for input file {}. "
        "Exit code was: {}. "
        .format(cmd, env, xz_input_file, rc))

  def _extract(self, path, outdir):
    with self._invoke_xz(path) as xz_decompressed_tar_stream:
      return super(XZCompressedTarArchiver, self)._extract(
        xz_decompressed_tar_stream, outdir, mode=self.mode)

  def create(self, *args, **kwargs):
    """
    :raises: :class:`NotImplementedError`
    """
    raise NotImplementedError("XZCompressedTarArchiver can only extract, not create archives!")


class ZipArchiver(Archiver):
  """An archiver that stores files in a zip file with optional compression.

  :API: public
  """

  def _extract(self, path, outdir, filter_func=None):
    """Extract from a zip file, with an optional filter.

    :param function filter_func: optional filter with the filename as the parameter.  Returns True
                                 if the file should be extracted."""
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


TAR = TarArchiver('w:', 'tar')
TGZ = TarArchiver('w:gz', 'tar.gz')
TBZ2 = TarArchiver('w:bz2', 'tar.bz2')
ZIP = ZipArchiver(ZIP_DEFLATED, 'zip')

_ARCHIVER_BY_TYPE = OrderedDict(
  tar=TAR,
  tgz=TGZ,
  tbz2=TBZ2,
  zip=ZIP)

archive_extensions = {
  name:archiver.extension for name, archiver in _ARCHIVER_BY_TYPE.items()
}

TYPE_NAMES = frozenset(_ARCHIVER_BY_TYPE.keys())
TYPE_NAMES_NO_PRESERVE_SYMLINKS = frozenset(['zip'])
TYPE_NAMES_PRESERVE_SYMLINKS = TYPE_NAMES - TYPE_NAMES_NO_PRESERVE_SYMLINKS


def create_archiver(typename):
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
    return create_archiver(ext)
