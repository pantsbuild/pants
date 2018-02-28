# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import hashlib
import logging
import os
import posixpath
from collections import namedtuple
from contextlib import contextmanager

from twitter.common.collections import OrderedSet

from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.hash_utils import hash_file
from pants.fs.archive import archiver as create_archiver
from pants.net.http.fetcher import Fetcher
from pants.subsystem.subsystem import Subsystem
from pants.util.contextutil import temporary_file
from pants.util.dirutil import chmod_plus_x, safe_concurrent_creation, safe_open
from pants.util.osutil import get_os_id


_DEFAULT_PATH_BY_ID = {
  ('linux', 'x86_64'): ('linux', 'x86_64'),
  ('linux', 'amd64'): ('linux', 'x86_64'),
  ('linux', 'i386'): ('linux', 'i386'),
  ('linux', 'i686'): ('linux', 'i386'),
  ('darwin', '9'): ('mac', '10.5'),
  ('darwin', '10'): ('mac', '10.6'),
  ('darwin', '11'): ('mac', '10.7'),
  ('darwin', '12'): ('mac', '10.8'),
  ('darwin', '13'): ('mac', '10.9'),
  ('darwin', '14'): ('mac', '10.10'),
  ('darwin', '15'): ('mac', '10.11'),
  ('darwin', '16'): ('mac', '10.12'),
  ('darwin', '17'): ('mac', '10.13'),
}


logger = logging.getLogger(__name__)


class BinaryUtil(object):
  """Wraps utility methods for finding binary executables.

  :API: public
  """

  class Factory(Subsystem):
    """
    :API: public
    """
    # N.B. `BinaryUtil` sources all of its options from bootstrap options, so that
    # `BinaryUtil` instances can be created prior to `Subsystem` bootstrapping. So
    # this options scope is unused, but required to remain a `Subsystem`.
    options_scope = 'binaries'

    @classmethod
    def create(cls):
      """
      :API: public
      """
      # NB: create is a class method to ~force binary fetch location to be global.
      options = cls.global_instance().get_options()
      return BinaryUtil(
        options.binaries_baseurls,
        options.binaries_fetch_timeout_secs,
        options.pants_bootstrapdir,
        options.binaries_path_by_id
      )

  class MissingMachineInfo(TaskError):
    """Indicates that pants was unable to map this machine's OS to a binary path prefix."""
    pass

  class BinaryNotFound(TaskError):

    def __init__(self, binary, accumulated_errors):
      super(BinaryUtil.BinaryNotFound, self).__init__(
          'Failed to fetch binary {binary} from any source: ({sources})'
          .format(binary=binary, sources=', '.join(accumulated_errors)))

  class NoBaseUrlsError(TaskError):
    """Indicates that no urls were specified in pants.ini."""
    pass

  class BinaryFileSpec(namedtuple('BinaryFileSpec', ['filename', 'checksum', 'digest'])):
    def __new__(cls, filename, checksum=None, digest=hashlib.sha1()):
      return super(BinaryUtil.BinaryFileSpec, cls).__new__(cls, filename, checksum, digest)

  def _select_binary_base_path(self, supportdir, version, name, uname_func=None):
    """Calculate the base path.

    Exposed for associated unit tests.
    :param supportdir: the path used to make a path under --pants_bootstrapdir.
    :param version: the version number of the tool used to make a path under --pants-bootstrapdir.
    :param name: name of the binary to search for. (e.g 'protoc')
    :param uname_func: method to use to emulate os.uname() in testing
    :returns: Base path used to select the binary file.
    """
    uname_func = uname_func or os.uname
    os_id = get_os_id(uname_func=uname_func)
    if not os_id:
      raise self.MissingMachineInfo('Pants has no binaries for {}'.format(' '.join(uname_func())))

    try:
      middle_path = self._path_by_id[os_id]
    except KeyError:
      raise self.MissingMachineInfo('Unable to find binary {name} version {version}. '
                                    'Update --binaries-path-by-id to find binaries for {os_id!r}'
                                    .format(name=name, version=version, os_id=os_id))
    return os.path.join(supportdir, *(middle_path + (version, name)))

  def __init__(self, baseurls, timeout_secs, bootstrapdir, path_by_id=None):
    """Creates a BinaryUtil with the given settings to define binary lookup behavior.

    This constructor is primarily used for testing.  Production code will usually initialize
    an instance using the BinaryUtil.Factory.create() method.

    :param baseurls: URL prefixes which represent repositories of binaries.
    :type baseurls: list of string
    :param int timeout_secs: Timeout in seconds for url reads.
    :param string bootstrapdir: Directory to use for caching binaries.  Uses this directory to
      search for binaries in, or download binaries to if needed.
    :param dict path_by_id: Additional mapping from (sysname, id) -> (os, arch) for tool
      directory naming
    """
    self._baseurls = baseurls
    self._timeout_secs = timeout_secs
    self._pants_bootstrapdir = bootstrapdir
    self._path_by_id = _DEFAULT_PATH_BY_ID.copy()
    if path_by_id:
      self._path_by_id.update((tuple(k), tuple(v)) for k, v in path_by_id.items())

  # TODO: Deprecate passing in an explicit supportdir? Seems like we should be able to
  # organize our binary hosting so that it's not needed.
  def select(self, supportdir, version, name, platform_dependent, archive_type):
    """Fetches a file, unpacking it if necessary."""
    if archive_type is None:
      return self._select_file(supportdir, version, name, platform_dependent)
    archiver = create_archiver(archive_type)
    return self._select_archive(supportdir, version, name, platform_dependent, archiver)

  def _select_file(self, supportdir, version, name, platform_dependent):
    """Generates a path to request a file and fetches the file located at that path.

    :param string supportdir: The path the `name` binaries are stored under.
    :param string version: The version number of the binary to select.
    :param string name: The name of the file to fetch.
    :param bool platform_dependent: Whether the file content differs depending
      on the current platform.
    :raises: :class:`pants.binary_util.BinaryUtil.BinaryNotFound` if no file of the given version
      and name could be found for the current platform.
    """
    binary_path = self._binary_path_to_fetch(supportdir, version, name, platform_dependent)
    return self._fetch_binary(name=name, binary_path=binary_path)

  def _select_archive(self, supportdir, version, name, platform_dependent, archiver):
    """Generates a path to fetch, fetches the archive file, and unpacks the archive.

    :param string supportdir: The path the `name` binaries are stored under.
    :param string version: The version number of the binary to select.
    :param string name: The name of the file to fetch.
    :param bool platform_dependent: Whether the file content differs depending
      on the current platform.
    :param archiver: The archiver object which provides the file extension and
      unpacks the archive.
    :type: :class:`pants.fs.archive.Archiver`
    :raises: :class:`pants.binary_util.BinaryUtil.BinaryNotFound` if no file of the given version
      and name could be found for the current platform.
    """
    full_name = '{}.{}'.format(name, archiver.extension)
    downloaded_file = self._select_file(supportdir, version, full_name, platform_dependent)
    # Use filename without rightmost extension as the directory name.
    unpacked_dirname, _ = os.path.splitext(downloaded_file)
    if not os.path.exists(unpacked_dirname):
      archiver.extract(downloaded_file, unpacked_dirname)
    return unpacked_dirname

  def _binary_path_to_fetch(self, supportdir, version, name, platform_dependent):
    if platform_dependent:
      # TODO(John Sirois): finish doc of the path structure expected under base_path.
      return self._select_binary_base_path(supportdir, version, name)
    return os.path.join(supportdir, version, name)

  def select_binary(self, supportdir, version, name):
    return self._select_file(
      supportdir, version, name, platform_dependent=True)

  def select_script(self, supportdir, version, name):
    return self._select_file(
      supportdir, version, name, platform_dependent=False)

  @contextmanager
  def _select_binary_stream(self, name, binary_path, fetcher=None):
    """Select a binary located at a given path.

    :param string binary_path: The path to the binary to fetch.
    :param fetcher: Optional argument used only for testing, to 'pretend' to open urls.
    :returns: a 'stream' to download it from a support directory. The returned 'stream' is actually
      a lambda function which returns the files binary contents.
    :raises: :class:`pants.binary_util.BinaryUtil.BinaryNotFound` if no binary of the given version
      and name could be found for the current platform.
    """

    if not self._baseurls:
      raise self.NoBaseUrlsError(
          'No urls are defined for the --pants-support-baseurls option.')
    downloaded_successfully = False
    accumulated_errors = []
    for baseurl in OrderedSet(self._baseurls):  # De-dup URLS: we only want to try each URL once.
      url = posixpath.join(baseurl, binary_path)
      logger.info('Attempting to fetch {name} binary from: {url} ...'.format(name=name, url=url))
      try:
        with temporary_file() as dest:
          fetcher = fetcher or Fetcher(get_buildroot())
          fetcher.download(url,
                           listener=Fetcher.ProgressListener(),
                           path_or_fd=dest,
                           timeout_secs=self._timeout_secs)
          logger.info('Fetched {name} binary from: {url} .'.format(name=name, url=url))
          downloaded_successfully = True
          dest.seek(0)
          yield lambda: dest.read()
          break
      except (IOError, Fetcher.Error, ValueError) as e:
        accumulated_errors.append('Failed to fetch binary from {url}: {error}'
                                  .format(url=url, error=e))
    if not downloaded_successfully:
      raise self.BinaryNotFound(binary_path, accumulated_errors)

  def _fetch_binary(self, name, binary_path):
    bootstrap_dir = os.path.realpath(os.path.expanduser(self._pants_bootstrapdir))
    bootstrapped_binary_path = os.path.join(bootstrap_dir, binary_path)
    if not os.path.exists(bootstrapped_binary_path):
      with safe_concurrent_creation(bootstrapped_binary_path) as downloadpath:
        with self._select_binary_stream(name, binary_path) as stream:
          with safe_open(downloadpath, 'wb') as bootstrapped_binary:
            bootstrapped_binary.write(stream())
          os.rename(downloadpath, bootstrapped_binary_path)
          chmod_plus_x(bootstrapped_binary_path)

    logger.debug('Selected {binary} binary bootstrapped to: {path}'
                 .format(binary=name, path=bootstrapped_binary_path))
    return bootstrapped_binary_path

  @staticmethod
  def _compare_file_checksums(filepath, checksum=None, digest=None):
    digest = digest or hashlib.sha1()

    if os.path.isfile(filepath) and checksum:
      return hash_file(filepath, digest=digest) == checksum

    return os.path.isfile(filepath)

  def is_bin_valid(self, basepath, binary_file_specs=()):
    """Check if this bin path is valid.

    :param string basepath: The absolute path where the binaries are stored under.
    :param BinaryFileSpec[] binary_file_specs: List of filenames and checksum for validation.
    """
    if not os.path.isdir(basepath):
      return False

    for f in binary_file_specs:
      filepath = os.path.join(basepath, f.filename)
      if not self._compare_file_checksums(filepath, f.checksum, f.digest):
        return False

    return True
