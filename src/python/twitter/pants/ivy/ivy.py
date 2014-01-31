# ==================================================================================================
# Copyright 2013 Twitter, Inc.
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

import hashlib
import os
import shutil

from twitter.common.collections import maybe_list
from twitter.common.contextutil import temporary_file
from twitter.common.dirutil import safe_delete, touch
from twitter.common.lang import Compatibility
from twitter.common.quantity import Amount, Time

from twitter.pants.base.config import Config
from twitter.pants.java import Executor, SubprocessExecutor
from twitter.pants.net.http.fetcher import Fetcher


class Bootstrapper(object):
  """Bootstraps a working ivy resolver.

  By default a working resolver will be bootstrapped from maven central and it will use standard
  public jar repositories and a standard ivy local cache directory to execute resolve operations.

  A combination of site configuration options and environment variables can be used to override this
  default setup.

  By default ivy will be bootstrapped from a stable ivy jar version found in maven central, but
  this can be over-ridden with the ``ivy / bootstrap_jar_url`` config option.  Additionally the
  bootstrapping will use a connect/read timeout of 1 second by default, but this can be raised by
  specifying a ``ivy / bootstrap_fetch_timeout_secs`` config value.

  After bootstrapping, ivy will re-resolve itself.  By default it does this via maven central, but
  a custom ivy tool classpath can be specified by using the ``ivy / ivy_profile`` option to point to
  a custom ivy profile ivy.xml.  This can be useful to upgrade ivy to a version released after pants
  or else mix in auxiliary jars that provide ivy plugins.

  Finally, by default the ivysettings.xml embedded in the ivy jar will be used in conjunction with
  the default ivy local cache directory of ~/.ivy2/cache.  To specify custom values for these you
  can either provide ``ivy / ivy_settings`` and ``ivy / cache_dir`` config values or supply these
  values via the ``PANTS_IVY_SETTINGS_XML`` and ``PANTS_IVY_CACHE_DIR`` environment variables
  respectively.  The environment variables will trump config values if present.
  """

  class Error(Exception):
    """Indicates an error bootstrapping an ivy classpath."""

  _DEFAULT_VERSION = '2.3.0'
  _DEFAULT_URL = ('http://repo1.maven.org/maven2/'
                  'org/apache/ivy/ivy/'
                  '%(version)s/ivy-%(version)s.jar' % {'version': _DEFAULT_VERSION})

  _INSTANCE = None

  @classmethod
  def instance(cls):
    """Returns the default global ivy bootstrapper."""
    if cls._INSTANCE is None:
      cls._INSTANCE = cls()
    return cls._INSTANCE

  @classmethod
  def default_ivy(cls, java_executor=None):
    """Returns an Ivy instance using the default global bootstrapper.

    By default runs ivy via a subprocess java executor.

    :param java_executor: the optional java executor to use
    :returns: an Ivy instance.
    :raises: Bootstrapper.Error if the default ivy instance could not be bootstrapped
    """
    return cls.instance().ivy(java_executor=java_executor)

  def __init__(self):
    """Creates an ivy bootstrapper."""
    self._config = Config.load()
    self._bootstrap_jar_url = self._config.get('ivy', 'bootstrap_jar_url',
                                               default=self._DEFAULT_URL)
    self._timeout = Amount(self._config.getint('ivy', 'bootstrap_fetch_timeout_secs', default=1),
                           Time.SECONDS)
    self._version_or_ivyxml = self._config.get('ivy', 'ivy_profile', default=self._DEFAULT_VERSION)
    self._classpath = None

  def ivy(self, java_executor=None):
    """Returns an ivy instance bootstrapped by this bootstrapper.

    :raises: Bootstrapper.Error if ivy could not be bootstrapped
    """
    return Ivy(self.classpath,
               java_executor=java_executor,
               ivy_settings=self.ivy_settings,
               ivy_cache_dir=self.ivy_cache_dir)

  @property
  def classpath(self):
    """Returns the bootstrapped ivy classpath as a list of jar paths.

    :raises: Bootstrapper.Error if the classpath could not be bootstrapped
    """
    if not self._classpath:
      self._classpath = self._bootstrap_ivy_classpath()
    return self._classpath

  @property
  def ivy_settings(self):
    """Returns the bootstrapped ivysettings.xml path.

    By default the ivy.ivy_settings value found in pants.ini but can be overridden by via the
    PANTS_IVY_SETTINGS_XML environment variable.  If neither is specified defaults to ivy's built
    in default ivysettings.xml of standard public resolvers.
    """
    return os.getenv('PANTS_IVY_SETTINGS_XML') or self._config.get('ivy', 'ivy_settings')

  @property
  def ivy_cache_dir(self):
    """Returns the bootstrapped ivy cache dir.

    By default the ivy.cache_dir value found in pants.ini but can be overridden via the
    PANTS_IVY_CACHE_DIR environment variable.  If neither is specified defaults to ivy's built
    in default cache dir; ie: ~/.ivy2/cache.
    """
    return (os.getenv('PANTS_IVY_CACHE_DIR')
            or self._config.get('ivy', 'cache_dir', default=os.path.expanduser('~/.ivy2/cache')))

  def _bootstrap_ivy_classpath(self, retry=True):
    # TODO(John Sirois): Extract a ToolCache class to control the path structure:
    # https://jira.twitter.biz/browse/DPB-283
    ivy_cache = os.path.join(self._config.getdefault('pants_cachedir'), 'tools', 'jvm', 'ivy')

    digest = hashlib.sha1()
    if os.path.isfile(self._version_or_ivyxml):
      with open(self._version_or_ivyxml) as fp:
        digest.update(fp.read())
    else:
      digest.update(self._version_or_ivyxml)
    classpath = os.path.join(ivy_cache, '%s.classpath' % digest.hexdigest())

    if not os.path.exists(classpath):
      ivy = self._bootstrap_ivy(os.path.join(ivy_cache, 'bootstrap.jar'))
      args = ['-confs', 'default', '-cachepath', classpath]
      if os.path.isfile(self._version_or_ivyxml):
        args.extend(['-ivy', self._version_or_ivyxml])
      else:
        args.extend(['-dependency', 'org.apache.ivy', 'ivy', self._version_or_ivyxml])

      try:
        ivy.execute(args)
      except ivy.Error as e:
        safe_delete(classpath)
        raise self.Error('Failed to bootstrap an ivy classpath! %s' % e)

    with open(classpath) as fp:
      cp = fp.read().strip().split(os.pathsep)
      if not all(map(os.path.exists, cp)):
        safe_delete(classpath)
        if retry:
          return self._bootstrap_ivy_classpath(retry=False)
        raise self.Error('Ivy bootstrapping failed - invalid classpath: %s' % ':'.join(cp))
      return cp

  def _bootstrap_ivy(self, bootstrap_jar_cache_path):
    if not os.path.exists(bootstrap_jar_cache_path):
      with temporary_file() as bootstrap_jar:
        fetcher = Fetcher()
        checksummer = fetcher.ChecksumListener(digest=hashlib.sha1())
        try:
          print('Downloading %s' % self._bootstrap_jar_url)
          fetcher.download(self._bootstrap_jar_url,
                           listener=fetcher.ProgressListener().wrap(checksummer),
                           path_or_fd=bootstrap_jar,
                           timeout=self._timeout)
          print('sha1: %s' % checksummer.checksum)
          bootstrap_jar.close()
          touch(bootstrap_jar_cache_path)
          shutil.move(bootstrap_jar.name, bootstrap_jar_cache_path)
        except fetcher.Error as e:
          raise self.Error('Problem fetching the ivy bootstrap jar! %s' % e)

    return Ivy(bootstrap_jar_cache_path,
               ivy_settings=self.ivy_settings,
               ivy_cache_dir=self.ivy_cache_dir)


class Ivy(object):
  """Encapsulates the ivy cli taking care of the basic invocation letting you just worry about the
  args to pass to the cli itself.
  """

  class Error(Exception):
    """Indicates an error executing an ivy command."""

  def __init__(self, classpath, java_executor=None, ivy_settings=None, ivy_cache_dir=None):
    """Configures an ivy wrapper for the ivy distribution at the given classpath."""

    self._classpath = maybe_list(classpath)

    self._java = java_executor or SubprocessExecutor()
    if not isinstance(self._java, Executor):
      raise ValueError('java_executor must be an Executor instance, given %s of type %s'
                       % (self._java, type(self._java)))

    self._ivy_settings = ivy_settings
    if self._ivy_settings and not isinstance(self._ivy_settings, Compatibility.string):
      raise ValueError('ivy_settings must be a string, given %s of type %s'
                       % (self._ivy_settings, type(self._ivy_settings)))

    self._ivy_cache_dir = ivy_cache_dir
    if self._ivy_cache_dir and not isinstance(self._ivy_cache_dir, Compatibility.string):
      raise ValueError('ivy_cache_dir must be a string, given %s of type %s'
                       % (self._ivy_cache_dir, type(self._ivy_cache_dir)))

  @property
  def ivy_settings(self):
    """Returns the ivysettings.xml path used by this `Ivy` instance."""
    return self._ivy_settings

  @property
  def ivy_cache_dir(self):
    """Returns the ivy cache dir used by this `Ivy` instance."""
    return self._ivy_cache_dir

  def execute(self, jvm_options=None, args=None, stdout=None, stderr=None, executor=None):
    """Executes the ivy commandline client with the given args.

    Raises Ivy.Error if the command fails for any reason.
    """
    runner = self.runner(jvm_options=jvm_options, args=args, executor=executor)
    try:
      result = runner.run(stdout=stdout, stderr=stderr)
      if result != 0:
        raise self.Error('Ivy command failed with exit code %d%s'
                         % (result, ': ' + ' '.join(args) if args else ''))
    except self._java.Error as e:
      raise self.Error('Problem executing ivy: %s' % e)

  def runner(self, jvm_options=None, args=None, executor=None):
    """Creates an ivy commandline client runner for the given args."""
    executor = executor or self._java
    if not isinstance(executor, Executor):
      raise ValueError('The executor argument must be an Executor instance, given %s of type %s'
                       % (executor, type(executor)))

    if self._ivy_cache_dir and '-cache' not in args:
      # TODO(John Sirois): Currently this is a magic property to support hand-crafted <caches/> in
      # ivysettings.xml.  Ideally we'd support either simple -caches or these hand-crafted cases
      # instead of just hand-crafted.  Clean this up by taking over ivysettings.xml and generating
      # it from BUILD constructs.
      jvm_options = ['-Divy.cache.dir=%s' % self._ivy_cache_dir] + (jvm_options or [])

    if self._ivy_settings and '-settings' not in args:
      args = ['-settings', self._ivy_settings] + args

    return executor.runner(self._classpath, 'org.apache.ivy.Main',
                           jvm_options=jvm_options, args=args)
