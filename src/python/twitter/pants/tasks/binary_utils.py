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

__author__ = 'jsirois'

import os
import subprocess

from contextlib import contextmanager

from twitter.common import log
from twitter.common.contextutil import environment_as, open_zip, temporary_file
from twitter.common.dirutil import safe_mkdir, safe_open, touch

from twitter.pants.base import Config
from twitter.pants.tasks import TaskError

_ID_BY_OS = {
  'linux': lambda release, machine: ('linux', machine),
  'darwin': lambda release, machine: ('darwin', release.split('.')[0]),
}


_PATH_BY_ID = {
  ('linux', 'x86_64'): [ 'linux', 'x86_64' ],
  ('linux', 'amd64'): [ 'linux', 'x86_64' ],
  ('linux', 'i386'): [ 'linux', 'i386' ],
  ('darwin', '9'): [ 'mac', '10.5' ],
  ('darwin', '10'): [ 'mac', '10.6' ],
  ('darwin', '11'): [ 'mac', '10.7' ],
}


def select_binary(base_path, version, name):
  """
    Selects a binary...
    Raises TaskError if no binary of the given version and name could be found.
  """
  # TODO(John Sirois): finish doc of the path structure expexcted under base_path
  sysname, _, release, _, machine = os.uname()
  os_id = _ID_BY_OS[sysname.lower()]
  if os_id:
    middle_path = _PATH_BY_ID[os_id(release, machine)]
    if middle_path:
      binary_path = os.path.join(base_path, *(middle_path + [version, name]))
      log.debug('Selected %s binary at: %s' % (name, binary_path))
      if os.path.exists(binary_path):
        return binary_path
      else:
        raise TaskError('Selected binary %s does not exist!' % binary_path)
  raise TaskError('Cannot generate thrift code for: %s' % [sysname, release, machine])


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


@contextmanager
def safe_classpath(logger=None):
  """
    Yields to a block in an environment with no CLASSPATH.  This is useful to ensure hermetic java
    invocations.
  """
  classpath = os.getenv('CLASSPATH')
  if classpath:
    logger = logger or log.warn
    logger('Scrubbing CLASSPATH=%s' % classpath)
  with environment_as(CLASSPATH=None):
    yield


def runjava(jvmargs=None, classpath=None, main=None, args=None):
  """Spawns a java process with the supplied configuration and returns its exit code."""
  cmd = ['java']
  if jvmargs:
    cmd.extend(jvmargs)
  if classpath:
    cmd.extend(('-cp' if main else '-jar', os.pathsep.join(classpath)))
  if main:
    cmd.append(main)
  if args:
    cmd.extend(args)

  log.debug('Executing: %s' % ' '.join(cmd))
  with safe_classpath():
    return subprocess.call(cmd)


def nailgun_profile_classpath(nailgun_task, profile, ivy_jar=None, ivy_settings=None):
  return profile_classpath(
    profile,
    java_runner=nailgun_task.runjava,
    config=nailgun_task.context.config,
    ivy_jar=ivy_jar,
    ivy_settings=ivy_settings
  )


def profile_classpath(profile, java_runner=None, config=None, ivy_jar=None, ivy_settings=None):
  # TODO(John Sirois): consider rework when ant backend is gone and there is no more need to share
  # path structure

  java_runner = java_runner or runjava

  config = config or Config.load()

  profile_dir = config.get('ivy-profiles', 'workdir')
  profile_libdir = os.path.join(profile_dir, '%s.libs' % profile)
  profile_check = '%s.checked' % profile_libdir
  if not os.path.exists(profile_check):
    # TODO(John Sirois): refactor IvyResolve to share ivy invocation command line bits
    ivy_classpath = [ivy_jar] if ivy_jar else config.getlist('ivy', 'classpath')

    safe_mkdir(profile_libdir)
    ivy_settings = ivy_settings or config.get('ivy', 'ivy_settings')
    ivy_xml = os.path.join(profile_dir, '%s.ivy.xml' % profile)
    ivy_args = [
      '-settings', ivy_settings,
      '-ivy', ivy_xml,

      # TODO(John Sirois): this pattern omits an [organisation]- prefix to satisfy IDEA jar naming
      # needs for scala - isolate this hack to idea.py where it belongs
      '-retrieve', '%s/[artifact]-[revision](-[classifier]).[ext]' % profile_libdir,

      '-sync',
      '-symlink',
      '-types', 'jar', 'bundle',
      '-confs', 'default'
    ]
    result = java_runner(classpath=ivy_classpath, main='org.apache.ivy.Main', args=ivy_args)
    if result != 0:
      raise TaskError('Failed to load profile %s, ivy exit code %d' % (profile, result))
    touch(profile_check)


  return [os.path.join(profile_libdir, jar) for jar in os.listdir(profile_libdir)]


def open(*files):
  """Attempts to open the given files using the preferred native viewer or editor."""
  if files:
    if os.uname()[0].lower() != 'darwin':
      print('Sorry, open currently only supports OSX')
    else:
      subprocess.Popen(['open'] + list(files))


def safe_extract(path, dest_dir):
  """
    OS X's python 2.6.1 has a bug in zipfile that makes it unzip directories as regular files.
    This method should work on for python 2.6-3.x.
  """

  with open_zip(path) as zip:
    for path in zip.namelist():
      # While we're at it, we also perform this safety test.
      if path.startswith('/') or path.startswith('..'):
        raise ValueError('Jar file contains unsafe path: %s' % path)
      if not path.endswith('/'):  # Ignore directories. extract() will create parent dirs as needed.
        zip.extract(path, dest_dir)
