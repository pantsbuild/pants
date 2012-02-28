# ==================================================================================================
# Copyright 2012 Twitter, Inc.
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

__author__ = 'Brian Wickman'

import errno
import os
import subprocess
import tarfile

from twitter.pants import get_buildroot
from twitter.common.dirutil import safe_mkdir, safe_rmtree
from twitter.common.lang import Compatibility
from twitter.common.python.interpreter import PythonInterpreter
from twitter.pants.tasks import Task, TaskError

StringIO = Compatibility.StringIO

if Compatibility.PY3:
  from urllib.request import urlopen
else:
  from urllib2 import urlopen

def setup_virtualenv_py(context):
  virtualenv_cache = context.config.get('python-setup', 'cache')
  virtualenv_target = context.config.get('python-setup', 'virtualenv_target')
  if not os.path.exists(virtualenv_cache):
    safe_mkdir(virtualenv_cache)
  if os.path.exists(os.path.join(virtualenv_target, 'virtualenv.py')):
    return True
  else:
    safe_mkdir(virtualenv_target)

  virtualenv_urls = context.config.getlist('python-setup', 'virtualenv_urls')
  tf = None
  for url in virtualenv_urls:
    try:
      ve_tgz = urlopen(url, timeout=5)
      ve_tgz_fp = StringIO(ve_tgz.read())
      ve_tgz_fp.seek(0)
      tf = tarfile.open(fileobj=ve_tgz_fp, mode='r:gz')
      break
    except Exception as e:
      context.log.warn('Failed to pull virtualenv from %s' % url)
      continue
  if not tf:
    raise TaskError('Could not download virtualenv!')
  try:
    tf.extractall(path=virtualenv_cache)
  except Exception as e:
    raise TaskError('Could not install virtualenv: %s' % e)
  context.log.info('Extracted %s' % url)

def subprocess_call(cmdline):
  po = subprocess.Popen(cmdline, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
  stdout, stderr = po.communicate()
  return (po.returncode, stdout, stderr)

def install_virtualenv(context, interpreter):
  virtualenv_cache = context.config.get('python-setup', 'cache')
  virtualenv_target = context.config.get('python-setup', 'virtualenv_target')
  pip_repos = context.config.getlist('python-setup', 'repos')
  if not os.path.exists(virtualenv_target):
    raise TaskError('Could not find installed virtualenv!')

  env_base = context.config.getdefault('pants_pythons')

  # setup $PYTHONS/bin/INTERPRETER => interpreter.binary
  env_bin = os.path.join(env_base, 'bin')
  safe_mkdir(env_bin)
  link_target = os.path.join(env_bin, str(interpreter.identity()))
  if os.path.exists(link_target):
    os.unlink(link_target)
  os.symlink(interpreter.binary(), link_target)

  # create actual virtualenv that can be used for synthesis of pants pex
  environment_install_path = os.path.join(env_base, str(interpreter.identity()))
  virtualenv_py = os.path.join(virtualenv_target, 'virtualenv.py')
  python_interpreter = interpreter.binary()

  if os.path.exists(os.path.join(environment_install_path, 'bin', 'python')) and (
     not context.options.setup_python_force):
    return True
  else:
    safe_rmtree(environment_install_path)
    safe_mkdir(environment_install_path)

  cmdline = '%s %s --distribute %s' % (
         python_interpreter,
         virtualenv_py,
         environment_install_path)
  context.log.info('Setting up %s...' % interpreter.identity())
  context.log.debug('Running %s' % cmdline)

  rc, stdout, stderr = subprocess_call(cmdline)
  if rc != 0:
    context.log.warn('Failed to install virtualenv: err=%s' % stderr)
    raise TaskError('Could not install virtualenv for %s' % interpreter.identity())

  def install_package(pkg):
    INSTALL_VIRTUALENV_PACKAGE = """
      source %(environment)s/bin/activate
      %(environment)s/bin/pip install --download-cache=%(cache)s \
         %(f_repositories)s --no-index -U %(package)s
    """ % {
      'environment': environment_install_path,
      'cache': virtualenv_cache,
      'f_repositories': ' '.join('-f %s' % repository for repository in pip_repos),
      'package': pkg
    }
    rc, stdout, stderr = subprocess_call(INSTALL_VIRTUALENV_PACKAGE)
    if rc != 0:
      context.log.warn('Failed to install %s' % pkg)
      context.log.debug('Stdout:\n%s\nStderr:\n%s\n' % (stdout, stderr))
    return rc == 0

  for package in context.config.getlist('python-setup', 'bootstrap_packages'):
    context.log.debug('Installing %s into %s' % (package, interpreter.identity()))
    if not install_package(package):
      context.log.warn('Failed to install %s into %s!' % (package, interpreter.identity()))
  return True


class SetupPythonEnvironment(Task):
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    option_group.add_option(mkflag("force"), dest="setup_python_force",
                            action="store_true", default=False,
                            help="Force clean and install.")
    option_group.add_option(mkflag("path"), dest="python_setup_paths",
                            action="append", default=[],
                            help="Add a path to search for interpreters, by default PATH.")

  def execute(self, _):
    setup_paths = self.context.options.python_setup_paths or os.getenv('PATH').split(':')
    self.context.log.debug('Finding interpreters in %s' % setup_paths)
    interpreters = PythonInterpreter.all(setup_paths)
    self.context.log.debug('Found %d interpreters' % len(interpreters))
    setup_virtualenv_py(self.context)

    for interpreter in interpreters:
      self.context.log.debug('Preparing %s' % interpreter)
      install_virtualenv(self.context, interpreter)
