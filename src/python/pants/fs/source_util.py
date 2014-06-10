# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from collections import defaultdict
import os
import re
import shutil

from twitter.common import log
from twitter.common.collections import OrderedSet
from twitter.common.contextutil import open_zip
from twitter.common.contextutil import open_tar
from twitter.common.contextutil import temporary_dir
from twitter.common.contextutil import temporary_file_path
from twitter.common.dirutil import safe_delete

from pants.base.build_environment import get_buildroot

def _zip_formats():
  return [ZipEntry, TarEntry,]

def _is_zipfile(path):
  return any(format.is_format(path) for format in _zip_formats())

def _zip_entries(path, ignore_hidden=True):
  for format in _zip_formats():
    if format.is_format(path):
      for entry in format.get_entries(path):
        if not (entry.name.startswith('.') and ignore_hidden):
          yield entry

def _filename(path):
  slash = path.rfind('/')
  if slash < 0:
    return path
  return path[slash+1:]

def pants_temp_dir():
  """Returns the temporary directory zipped sources are extracted into during expand_sources."""
  return os.path.join('.pants.d', 'tmp')

def _guess_package(path):
  package = os.path.relpath(path, get_buildroot())
  if os.path.isdir(package):
    return package
  return os.path.dirname(package)

def extract_temp_files(paths, name_map={}, temp_dir=None, source_filter=None):
  """Expands any zipped sources on the input path into temporary files.
  All paths on the input paths list which aren't zipped are simply included in the return list.
  :param paths: Input paths
  :param name_map: Map from paths to source names which can override the default behavior assumption
  that the source name of a file is simply its filename. Useful when compiling sources stored in
  temporary files, for example.
  :param temp_dir: Overrides the directory used to store temporary files (default pants_temp_dir()).
  :param source_filter: Optional predicate which can be used to skip unwanted files (eg, if you only
  want .proto files, you can input source_filter=lambda s: s.endswith('.proto')).
  :returns: A Closable list of file paths, relative to the build root (to be used with the 'with'
  statement).
  """
  files = [] # all the returned files (but not directories)
  temps = [] # the files and directories which should be deleted later
  if source_filter is None:
    source_filter = lambda x: True
  _temp_dir = temp_dir

  for path, source, reader in get_input_streams(paths, name_map):
    if not source_filter(source):
      continue
    if not _is_zipfile(path):
      files.append(path)
      continue
    if _temp_dir is None:
      # Use default temporary directory
      temp_dir = os.path.join(pants_temp_dir(), _guess_package(path))
      temp_dir = temp_dir.replace('/..', '')
      if not os.path.exists(temp_dir):
        temps.append(temp_dir)
        os.makedirs(temp_dir)
    fp = os.path.join(temp_dir, source)
    # Actually create the temp file and fill it with proper data
    with open(fp, 'w') as writer:
      writer.writelines(reader())
    fp = os.path.relpath(fp, get_buildroot())
    files.append(fp)
    temps.append(fp)

  return TemporaryFiles(files, temps)

def get_input_streams(paths, name_map={}, source_filter=None):
  """Returns tuples of source names and file reading functions, expanding any zipped sources.
  :param paths: Input sources (or zips)
  :param name_map: Map from paths to source names which can override the default behavior assumption
  that the source name of a file is simply its filename. Useful when compiling sources stored in
  temporary files, for example.
  :param source_filter: Optional predicate which can be used to skip unwanted files (eg, if you only
  want .proto files, you can input source_filter=lambda s: s.endswith('.proto')).
  :returns: Yields tuples in the form (path, source, reader) where path is the input path from the
  paths list, source is the 'filename' of the source, and reader is a callable that acts like
  readlines().
  """
  if source_filter is None:
    source_filter = lambda x: True

  for path in paths:
    if _is_zipfile(path):
      # Walk through the zip file, yielding entries
      # TODO(Garrett Malmquist): extend this to work with other kinds of compressed archives
      for entry in _zip_entries(path):
        if entry.name.endswith('/'):
          continue # skip directories
        source_name = _filename(entry.name)
        if source_filter(source_name):
          yield (path, source_name, lambda: entry.readlines())
    else:
      # Yield the source file
      with open(path, 'r') as handle:
        source_name = name_map[path] if name_map.has_key(path) else _filename(path)
        if source_filter(source_name):
          yield (path, source_name, lambda: handle.readlines())

class TemporaryFiles(object):
  """Closable object which returns a list of (possible temporary) file paths. Some (or all) of the
  files in the list may be deleted on exit (at the end of the with statement block).
  """
  def __init__(self, files, to_delete):
    self._files = files
    self._to_delete = to_delete

  def __enter__(self):
    return self._files

  def __exit__(self, type, value, traceback):
    for tmp in self._to_delete:
      if os.path.isdir(tmp):
        shutil.rmtree(tmp, ignore_errors=True)
      else:
        safe_delete(tmp)

class ArchiveEntry(object):
  """Abstract entry in a compressed archive."""
  def readlines(self):
    raise NotImplementedError()

  @property
  def name(self):
    raise NotImplementedError()

  @property
  def isdir(self):
    raise NotImplementedError()

  @classmethod
  def is_format(cls, path):
    raise NotImplementedError()

  @classmethod
  def get_entries(cls, path):
    raise NotImplementedError()


class ZipEntry(ArchiveEntry):
  """Wrapper for an entry in a .zip/.jar file."""
  def __init__(self, archive_file, archive_entry):
    self._archive_file = archive_file
    self._archive_entry = archive_entry

  def readlines(self):
    return self._archive_file.open(self._archive_entry, 'r').readlines()

  @property
  def name(self):
    return self._archive_entry.filename

  @property
  def isdir(self):
    return self._archive_entry.filename.endswith('/')

  @classmethod
  def is_format(cls, path):
    return any(path.endswith('.'+ext) for ext in ['zip', 'jar',])

  @classmethod
  def get_entries(cls, path):
    if cls.is_format(path):
      with open_zip(path) as archive:
        for entry in archive.infolist():
          yield ZipEntry(archive, entry)

class TarEntry(ArchiveEntry):
  """Wrapper for an entry in a .tar/.tar.gz/.tar.bz2 file."""
  def __init__(self, archive_file, archive_entry):
    self._archive_file = archive_file
    self._archive_entry = archive_entry

  def readlines(self):
    handle = self._archive_file.extractfile(self._archive_entry)
    lines = handle.readlines()
    handle.close()
    return lines

  @property
  def name(self):
    return self._archive_entry.name

  @property
  def isdir(self):
    return self._archive_entry.isdir()

  @classmethod
  def is_format(cls, path):
    return any(path.endswith('.'+ext) for ext in ['tar', 'tar.gz', 'tar.bz2', 'tgz',])

  @classmethod
  def get_entries(cls, path):
    if cls.is_format(path):
      with open_tar(path) as archive:
        for entry in archive.getmembers():
          yield TarEntry(archive, entry)
