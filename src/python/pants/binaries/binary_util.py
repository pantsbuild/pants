# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
import posixpath
import subprocess
from contextlib import closing, contextmanager

import six.moves.urllib.error as urllib_error
import six.moves.urllib.request as urllib_request
from twitter.common.collections import OrderedSet

from pants.base.exceptions import TaskError
from pants.option.custom_types import dict_option, list_option
from pants.subsystem.subsystem import Subsystem
from pants.util.contextutil import temporary_file
from pants.util.dirutil import chmod_plus_x, safe_delete, safe_open
from pants.util.osutil import get_os_id


_DEFAULT_PATH_BY_ID = {
  ('linux', 'x86_64'): ['linux', 'x86_64'],
  ('linux', 'amd64'): ['linux', 'x86_64'],
  ('linux', 'i386'): ['linux', 'i386'],
  ('linux', 'i686'): ['linux', 'i386'],
  ('darwin', '9'): ['mac', '10.5'],
  ('darwin', '10'): ['mac', '10.6'],
  ('darwin', '11'): ['mac', '10.7'],
  ('darwin', '12'): ['mac', '10.8'],
  ('darwin', '13'): ['mac', '10.9'],
  ('darwin', '14'): ['mac', '10.10'],
  ('darwin', '15'): ['mac', '10.11'],
}


logger = logging.getLogger(__name__)


class BinaryUtil(object):
  """Wraps utility methods for finding binary executables."""

  class Factory(Subsystem):
    options_scope = 'binaries'

    @classmethod
    def register_options(cls, register):
      register('--baseurls', type=list_option, advanced=True,
               default=['https://dl.bintray.com/pantsbuild/bin/build-support'],
               help='List of urls from which binary tools are downloaded.  Urls are searched in '
                    'order until the requested path is found.')
      register('--fetch-timeout-secs', type=int, default=30, advanced=True,
               help='Timeout in seconds for url reads when fetching binary tools from the '
                    'repos specified by --baseurls')
      register("--path-by-id", type=dict_option, advanced=True,
               help='Maps output of uname for a machine to a binary search path.  e.g. '
               '{ ("darwin", "15"): ["mac", "10.11"]), ("linux", "arm32"): ["linux", "arm32"] }')

    @classmethod
    def create(cls):
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

  class MissingBinaryUtilOptionsError(Exception):
    """Internal error. --supportdir and --version must be registered in register_options()"""
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

    sysname, _, release, _, machine = uname_func()
    try:
      os_id = get_os_id(uname_func=uname_func)
    except KeyError:
      os_id = None
    if os_id is None:
      raise self.MissingMachineInfo("Pants has no binaries for {}".format(sysname))

    try:
      middle_path = self._path_by_id[os_id]
    except KeyError:
      raise self.MissingMachineInfo(
        "Update --binaries-path-by-id to find binaries for {sysname} {machine} {release}.".format(
          sysname=sysname, release=release, machine=machine))
    return os.path.join(supportdir, *(middle_path + [version, name]))

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
      self._path_by_id.update(path_by_id)

  @contextmanager
  def _select_binary_stream(self, supportdir, version, name, url_opener=None):
    """Select a binary matching the current os and architecture.

    :param string supportdir: The path the `name` binaries are stored under.
    :param string version: The version number of the binary to select.
    :param string name: The name of the binary to fetch.
    :param url_opener: Optional argument used only for testing, to 'pretend' to open urls.
    :returns: a 'stream' to download it from a support directory. The returned 'stream' is actually
      a lambda function which returns the files binary contents.
    :raises: :class:`pants.binary_util.BinaryUtil.BinaryNotFound` if no binary of the given version
      and name could be found for the current platform.
    """

    if not self._baseurls:
      raise self.NoBaseUrlsError(
          'No urls are defined for the --pants-support-baseurls option.')
    binary_path = self._select_binary_base_path(supportdir, version, name)
    if url_opener is None:
      url_opener = lambda u: closing(urllib_request.urlopen(u, timeout=self._timeout_secs))

    downloaded_successfully = False
    accumulated_errors = []
    for baseurl in OrderedSet(self._baseurls):  # Wrap in OrderedSet because duplicates are wasteful.
      url = posixpath.join(baseurl, binary_path)
      logger.info('Attempting to fetch {name} binary from: {url} ...'.format(name=name, url=url))
      try:
        with url_opener(url) as binary:
          logger.info('Fetched {name} binary from: {url} .'.format(name=name, url=url))
          downloaded_successfully = True
          yield lambda: binary.read()
          break
      except (IOError, urllib_error.HTTPError, urllib_error.URLError, ValueError) as e:
        accumulated_errors.append('Failed to fetch binary from {url}: {error}'
                                  .format(url=url, error=e))
    if not downloaded_successfully:
      raise self.BinaryNotFound((supportdir, version, name), accumulated_errors)

  def select_binary(self, supportdir, version, name):
    """Selects a binary matching the current os and architecture.

    :param string supportdir: The path the `name` binaries are stored under.
    :param string version: The version number of the binary to select.
    :param string name: The name of the binary to fetch.
    :raises: :class:`pants.binary_util.BinaryUtil.BinaryNotFound` if no binary of the given version
      and name could be found for the current platform.
    """
    # TODO(John Sirois): finish doc of the path structure expected under base_path
    binary_path = self._select_binary_base_path(supportdir, version, name)
    bootstrap_dir = os.path.realpath(os.path.expanduser(self._pants_bootstrapdir))
    bootstrapped_binary_path = os.path.join(bootstrap_dir, binary_path)
    if not os.path.exists(bootstrapped_binary_path):
      downloadpath = bootstrapped_binary_path + '~'
      try:
        with self._select_binary_stream(supportdir, version, name) as stream:
          with safe_open(downloadpath, 'wb') as bootstrapped_binary:
            bootstrapped_binary.write(stream())
          os.rename(downloadpath, bootstrapped_binary_path)
          chmod_plus_x(bootstrapped_binary_path)
      finally:
        safe_delete(downloadpath)

    logger.debug('Selected {binary} binary bootstrapped to: {path}'
                 .format(binary=name, path=bootstrapped_binary_path))
    return bootstrapped_binary_path


@contextmanager
def safe_args(args,
              options,
              max_args=None,
              argfile=None,
              delimiter='\n',
              quoter=None,
              delete=True):
  """Yields args if there are less than a limit otherwise writes args to an argfile and yields an
  argument list with one argument formed from the path of the argfile.

  :param args: The args to work with.
  :param OptionValueContainer options: scoped options object for this task
  :param max_args: The maximum number of args to let though without writing an argfile.  If not
    specified then the maximum will be loaded from the --max-subprocess-args option.
  :param argfile: The file to write args to when there are too many; defaults to a temporary file.
  :param delimiter: The delimiter to insert between args written to the argfile, defaults to '\n'
  :param quoter: A function that can take the argfile path and return a single argument value;
    defaults to: <code>lambda f: '@' + f<code>
  :param delete: If True deletes any arg files created upon exit from this context; defaults to
    True.
  """
  max_args = max_args or options.max_subprocess_args
  if len(args) > max_args:
    def create_argfile(f):
      f.write(delimiter.join(args))
      f.close()
      return [quoter(f.name) if quoter else '@{}'.format(f.name)]

    if argfile:
      try:
        with safe_open(argfile, 'w') as fp:
          yield create_argfile(fp)
      finally:
        if delete and os.path.exists(argfile):
          os.unlink(argfile)
    else:
      with temporary_file(cleanup=delete) as fp:
        yield create_argfile(fp)
  else:
    yield args


def _mac_open(files):
  subprocess.call(['open'] + list(files))


def _linux_open(files):
  cmd = "xdg-open"
  if not _cmd_exists(cmd):
    raise TaskError("The program '{}' isn't in your PATH. Please install and re-run this "
                    "goal.".format(cmd))
  for f in list(files):
    subprocess.call([cmd, f])


# From: http://stackoverflow.com/questions/377017/test-if-executable-exists-in-python
def _cmd_exists(cmd):
  return subprocess.call(["/usr/bin/which", cmd], shell=False, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE) == 0

_OPENER_BY_OS = {
  'darwin': _mac_open,
  'linux': _linux_open
}


def ui_open(*files):
  """Attempts to open the given files using the preferred native viewer or editor."""
  if files:
    osname = os.uname()[0].lower()
    if not osname in _OPENER_BY_OS:
      print('Sorry, open currently not supported for ' + osname)
    else:
      _OPENER_BY_OS[osname](files)
