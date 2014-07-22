# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from contextlib import closing, contextmanager
import os
import subprocess

import posixpath
from twitter.common import log
from twitter.common.collections import OrderedSet
from twitter.common.contextutil import temporary_file
from twitter.common.lang import Compatibility

from pants.base.config import Config
from pants.base.exceptions import TaskError
from pants.util.dirutil import chmod_plus_x, safe_delete, safe_open

if Compatibility.PY3:
  import urllib.request as urllib_request
  import urllib.error as urllib_error
else:
  import urllib2 as urllib_request
  import urllib2 as urllib_error


_ID_BY_OS = {
  'linux': lambda release, machine: ('linux', machine),
  'darwin': lambda release, machine: ('darwin', release.split('.')[0]),
}

_PATH_BY_ID = {
  ('linux', 'x86_64'):  ['linux', 'x86_64'],
  ('linux', 'amd64'):   ['linux', 'x86_64'],
  ('linux', 'i386'):    ['linux', 'i386'],
  ('darwin', '9'):      ['mac', '10.5'],
  ('darwin', '10'):     ['mac', '10.6'],
  ('darwin', '11'):     ['mac', '10.7'],
  ('darwin', '12'):     ['mac', '10.8'],
  ('darwin', '13'):     ['mac', '10.9'],
}


class BinaryUtil(object):
  """Wraps utility methods for finding binary executables."""

  class MissingMachineInfo(TaskError):
    """Indicates that pants was unable to map this machine's OS to a binary path prefix."""

  class BinaryNotFound(TaskError):
    def __init__(self, binary, accumulated_errors):
      super(BinaryUtil.BinaryNotFound, self).__init__(
          'Failed to fetch binary {binary} from any source: ({sources})'
          .format(binary=binary, sources=', '.join(accumulated_errors)))

  class NoBaseUrlsError(TaskError):
    """Indicates that no urls were specified in pants.ini."""

  def __init__(self, bootstrap_dir=None, baseurls=None, timeout=None, config=None,
               binary_base_path_strategy=None):
    """Creates a BinaryUtil with the given settings to define binary lookup behavior.

    Relevant settings may either be specified in the arguments, or will be loaded from the given
    config file.
    :param bootstrap_dir: Directory search for binaries in, or download binaries to if needed.
      Defaults to the value of 'pants_bootstrapdir' in config if unspecified.
    :param baseurls: List of url prefixes which represent repositories of binaries. Defaults to the
      value of 'pants_support_baseurls' in config if unspecified.
    :param timeout: Timeout in seconds for url reads. Defaults to the value of
      'pants_support_fetch_timeout_secs' in config if unspecified, or 30 seconds if that value isn't
      found in config.
    :param config: Config object to lookup parameters which are left unspecified as None. If config
      is left unspecified, it defaults to pants.ini via Config.load().
    :param binary_base_path_strategy: Optional function to override default select_binary_base_path
      behavior. Takes in parameters (base_path, version, name) and returns a relative path to a
      binary. This relative path is used both for appending to the baseurl to determine the full url
      to the binary, and as the path to the subfolder the binary is stored in under the bootstrap_dir.
    """
    if bootstrap_dir is None or baseurls is None or timeout is None:
      config = config or Config.load()
    if bootstrap_dir is None:
      bootstrap_dir = config.getdefault('pants_bootstrapdir')
    if baseurls is None:
      baseurls = config.getdefault('pants_support_baseurls', type=list, default=[])
    if timeout is None:
      timeout = config.getdefault('pants_support_fetch_timeout_secs', type=int, default=30)
    bootstrap_dir = os.path.realpath(os.path.expanduser(bootstrap_dir))

    self._boostrap_dir = bootstrap_dir
    self._timeout = timeout
    self._baseurls = baseurls
    self._binary_base_path_strategy = binary_base_path_strategy

  def select_binary_base_path(self, base_path, version, name):
    """Base path used to select the binary file, exposed for associated unit tests."""
    # If user-defined strategy function exists, use it instead of default behavior.
    if self._binary_base_path_strategy:
      return self.binary_base_path_strategy(base_path, version, name)

    sysname, _, release, _, machine = os.uname()
    os_id = _ID_BY_OS[sysname.lower()]
    if os_id:
      middle_path = _PATH_BY_ID[os_id(release, machine)]
      if middle_path:
        return os.path.join(base_path, *(middle_path + [version, name]))
    raise BinaryUtil.MissingMachineInfo('No {binary} binary found for: {machine_info}'
        .format(binary=name, machine_info=(sysname, release, machine)))

  @contextmanager
  def select_binary_stream(self, base_path, version, name, url_opener=None):
    """Select a binary matching the current os and architecture.

    :param url_opener: Optional argument used only for testing, to 'pretend' to open urls.
    :returns: a 'stream' to download it from a support directory. The returned 'stream' is actually
      a lambda function which returns the files binary contents.
    :raises: :class:`pants.binary_util.BinaryUtil.BinaryNotFound` if no binary of the given version
      and name could not be found.
    """
    baseurls = self._baseurls
    if not baseurls:
      raise BinaryUtil.NoBaseUrlsError(
          'No urls are defined under pants_support_baseurls in the DEFAULT section of pants.ini.')
    timeout_secs = self._timeout
    binary_path = self.select_binary_base_path(base_path, version, name)
    if url_opener is None:
      url_opener = lambda u: closing(urllib_request.urlopen(u, timeout=timeout_secs))

    downloaded_successfully = False
    accumulated_errors = []
    for baseurl in OrderedSet(baseurls): # Wrap in OrderedSet because duplicates are wasteful.
      url = posixpath.join(baseurl, binary_path)
      log.info('Attempting to fetch {name} binary from: {url} ...'.format(name=name, url=url))
      try:
        with url_opener(url) as binary:
          log.info('Fetched {name} binary from: {url} .'.format(name=name, url=url))
          downloaded_successfully = True
          yield lambda: binary.read()
          break
      except (IOError, urllib_error.HTTPError, urllib_error.URLError, ValueError) as e:
        accumulated_errors.append('Failed to fetch binary from {url}: {error}'
                                  .format(url=url, error=e))
    if not downloaded_successfully:
      raise BinaryUtil.BinaryNotFound((base_path, version, name), accumulated_errors)

  def select_binary(self, base_path, version, name):
    """Selects a binary matching the current os and architecture.

    :raises: :class:`pants.binary_util.BinaryUtil.BinaryNotFound` if no binary of the given version
      and name could be found.
    """
    # TODO(John Sirois): finish doc of the path structure expected under base_path
    bootstrap_dir = self._boostrap_dir
    binary_path = self.select_binary_base_path(base_path, version, name)
    bootstrapped_binary_path = os.path.join(bootstrap_dir, binary_path)
    if not os.path.exists(bootstrapped_binary_path):
      downloadpath = bootstrapped_binary_path + '~'
      try:
        with self.select_binary_stream(base_path, version, name) as stream:
          with safe_open(downloadpath, 'wb') as bootstrapped_binary:
            bootstrapped_binary.write(stream())
          os.rename(downloadpath, bootstrapped_binary_path)
          chmod_plus_x(bootstrapped_binary_path)
      finally:
        safe_delete(downloadpath)

    log.debug('Selected {binary} binary bootstrapped to: {path}'
              .format(binary=name, path=bootstrapped_binary_path))
    return bootstrapped_binary_path


@contextmanager
def safe_args(args,
              max_args=None,
              config=None,
              argfile=None,
              delimiter='\n',
              quoter=None,
              delete=True):
  """Yields args if there are less than a limit otherwise writes args to an argfile and yields an
  argument list with one argument formed from the path of the argfile.

  :param args: The args to work with.
  :param max_args: The maximum number of args to let though without writing an argfile.  If not
    specified then the maximum will be loaded from config.
  :param config: Used to lookup the configured maximum number of args that can be passed to a
    subprocess; defaults to the default config and looks for key 'max_subprocess_args' in the
    DEFAULTS.
  :param argfile: The file to write args to when there are too many; defaults to a temporary file.
  :param delimiter: The delimiter to insert between args written to the argfile, defaults to '\n'
  :param quoter: A function that can take the argfile path and return a single argument value;
    defaults to: <code>lambda f: '@' + f<code>
  :param delete: If True deletes any arg files created upon exit from this context; defaults to
    True.
  """
  max_args = max_args or (config or Config.load()).getdefault('max_subprocess_args', int, 10)
  if len(args) > max_args:
    def create_argfile(fp):
      fp.write(delimiter.join(args))
      fp.close()
      return [quoter(fp.name) if quoter else '@%s' % fp.name]

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
    raise TaskError("The program '%s' isn't in your PATH. Please install and re-run this "
                    "goal." % cmd)
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
