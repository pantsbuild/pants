# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
import posixpath
from contextlib import contextmanager

from twitter.common.collections import OrderedSet

from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.net.http.fetcher import Fetcher
from pants.subsystem.subsystem import Subsystem
from pants.util.contextutil import temporary_file
from pants.util.dirutil import chmod_plus_x, safe_delete, safe_open
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
    options_scope = 'binaries'

    @classmethod
    def register_options(cls, register):
      register('--baseurls', type=list, advanced=True,
               default=['https://dl.bintray.com/pantsbuild/bin/build-support'],
               help='List of urls from which binary tools are downloaded.  Urls are searched in '
                    'order until the requested path is found.')
      register('--fetch-timeout-secs', type=int, default=30, advanced=True,
               help='Timeout in seconds for url reads when fetching binary tools from the '
                    'repos specified by --baseurls')
      register('--path-by-id', type=dict, advanced=True,
               help='Maps output of uname for a machine to a binary search path.  e.g. '
               '{ ("darwin", "15"): ["mac", "10.11"]), ("linux", "arm32"): ["linux", "arm32"] }')

    @classmethod
    def create(cls):
      """
      :API: public
      """
      # NB: create is a class method to ~force binary fetch location to be global.
      options = cls.global_instance().get_options()
      return BinaryUtil(options.baseurls, options.fetch_timeout_secs, options.pants_bootstrapdir,
                        options.path_by_id)

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
      raise self.MissingMachineInfo('Update --binaries-path-by-id to find binaries for {!r}'
                                    .format(os_id))
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

  @contextmanager
  def _select_binary_stream(self, name, binary_path, fetcher=None):
    """Select a binary matching the current os and architecture.

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

  def select_binary(self, supportdir, version, name):
    """Selects a binary matching the current os and architecture.

    :param string supportdir: The path the `name` binaries are stored under.
    :param string version: The version number of the binary to select.
    :param string name: The name of the binary to fetch.
    :raises: :class:`pants.binary_util.BinaryUtil.BinaryNotFound` if no binary of the given version
      and name could be found for the current platform.
    """
    # TODO(John Sirois): finish doc of the path structure expected under base_path.
    binary_path = self._select_binary_base_path(supportdir, version, name)
    return self._fetch_binary(name=name, binary_path=binary_path)

  def select_script(self, supportdir, version, name):
    """Selects a platform-independent script.

    :param string supportdir: The path the `name` scripts are stored under.
    :param string version: The version number of the script to select.
    :param string name: The name of the script to fetch.
    :raises: :class:`pants.binary_util.BinaryUtil.BinaryNotFound` if no script of the given version
      and name could be found.
    """
    binary_path = os.path.join(supportdir, version, name)
    return self._fetch_binary(name=name, binary_path=binary_path)

  def _fetch_binary(self, name, binary_path):
    bootstrap_dir = os.path.realpath(os.path.expanduser(self._pants_bootstrapdir))
    bootstrapped_binary_path = os.path.join(bootstrap_dir, binary_path)
    if not os.path.exists(bootstrapped_binary_path):
      downloadpath = bootstrapped_binary_path + '~'
      try:
        with self._select_binary_stream(name, binary_path) as stream:
          with safe_open(downloadpath, 'wb') as bootstrapped_binary:
            bootstrapped_binary.write(stream())
          os.rename(downloadpath, bootstrapped_binary_path)
          chmod_plus_x(bootstrapped_binary_path)
      finally:
        safe_delete(downloadpath)

    logger.debug('Selected {binary} binary bootstrapped to: {path}'
                 .format(binary=name, path=bootstrapped_binary_path))
    return bootstrapped_binary_path
