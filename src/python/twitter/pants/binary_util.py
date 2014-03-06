# ==================================================================================================
# Copyright 2011 Twitter, Inc.
# --------------------------------------------------------------------------------------------------
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this work except in compliance with the License.
# You may obtain a copy of the License in the LICENSE file, or at:
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==================================================================================================

from __future__ import print_function

import os
import posixpath
import subprocess

from contextlib import closing, contextmanager

from twitter.common import log
from twitter.common.contextutil import temporary_file
from twitter.common.dirutil import chmod_plus_x, safe_delete, safe_open
from twitter.common.lang import Compatibility

if Compatibility.PY3:
  import urllib.request as urllib_request
  import urllib.error as urllib_error
else:
  import urllib2 as urllib_request
  import urllib2 as urllib_error

from .base.config import Config
from .tasks.task_error import TaskError


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


def select_binary(base_path, version, name, config=None):
  """Selects a binary matching the current os and architecture.

  Raises TaskError if no binary of the given version and name could be found.
  """
  # TODO(John Sirois): finish doc of the path structure expexcted under base_path
  config = config or Config.load()
  bootstrap_dir = config.getdefault('pants_bootstrapdir')
  baseurl = config.getdefault('pants_support_baseurl')
  timeout_secs = config.getdefault('pants_support_fetch_timeout_secs', type=int, default=30)

  sysname, _, release, _, machine = os.uname()
  os_id = _ID_BY_OS[sysname.lower()]
  if os_id:
    middle_path = _PATH_BY_ID[os_id(release, machine)]
    if middle_path:
      binary_path = os.path.join(base_path, *(middle_path + [version, name]))
      bootstrapped_binary_path = os.path.join(bootstrap_dir, binary_path)
      if not os.path.exists(bootstrapped_binary_path):
        url = posixpath.join(baseurl, binary_path)
        log.info('Fetching %s binary from: %s' % (name, url))
        downloadpath = bootstrapped_binary_path + '~'
        try:
          with closing(urllib_request.urlopen(url, timeout=timeout_secs)) as binary:
            with safe_open(downloadpath, 'wb') as bootstrapped_binary:
              bootstrapped_binary.write(binary.read())

          os.rename(downloadpath, bootstrapped_binary_path)
          chmod_plus_x(bootstrapped_binary_path)
        except (IOError, urllib_error.HTTPError, urllib_error.URLError) as e:
          raise TaskError('Failed to fetch binary from %s: %s' % (url, e))
        finally:
          safe_delete(downloadpath)
      log.debug('Selected %s binary bootstrapped to: %s' % (name, bootstrapped_binary_path))
      return bootstrapped_binary_path
  raise TaskError('No %s binary found for: %s' % (name, (sysname, release, machine)))


@contextmanager
def safe_args(args,
              max_args=None,
              config=None,
              argfile=None,
              delimiter='\n',
              quoter=None,
              delete=True):
  """
    Yields args if there are less than a limit otherwise writes args to an argfile and yields an
    argument list with one argument formed from the path of the argfile.

    :args The args to work with.
    :max_args The maximum number of args to let though without writing an argfile.  If not specified
              then the maximum will be loaded from config.
    :config Used to lookup the configured maximum number of args that can be passed to a subprocess;
            defaults to the default config and looks for key 'max_subprocess_args' in the DEFAULTS.
    :argfile The file to write args to when there are too many; defaults to a temporary file.
    :delimiter The delimiter to insert between args written to the argfile, defaults to '\n'
    :quoter A function that can take the argfile path and return a single argument value;
            defaults to:
            <code>lambda f: '@' + f<code>
    :delete If True deletes any arg files created upon exit from this context; defaults to True.
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
