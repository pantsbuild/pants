# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import hashlib
import os
import shutil

from twitter.common import log
from twitter.common.quantity import Amount, Time

from pants.base.config import Config
from pants.ivy.ivy import Ivy
from pants.net.http.fetcher import Fetcher
from pants.util.contextutil import temporary_file
from pants.util.dirutil import safe_delete, touch


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
  def default_ivy(cls, java_executor=None, bootstrap_workunit_factory=None):
    """Returns an Ivy instance using the default global bootstrapper.

    By default runs ivy via a subprocess java executor.

    :param java_executor: the optional java executor to use
    :param bootstrap_workunit_factory: the optional workunit to bootstrap under.
    :returns: an Ivy instance.
    :raises: Bootstrapper.Error if the default ivy instance could not be bootstrapped
    """
    return cls.instance().ivy(java_executor=java_executor,
                              bootstrap_workunit_factory=bootstrap_workunit_factory)

  def __init__(self):
    """Creates an ivy bootstrapper."""
    self._config = Config.load()
    self._bootstrap_jar_url = self._config.get('ivy', 'bootstrap_jar_url',
                                               default=self._DEFAULT_URL)
    self._timeout = Amount(self._config.getint('ivy', 'bootstrap_fetch_timeout_secs', default=1),
                           Time.SECONDS)
    self._version_or_ivyxml = self._config.get('ivy', 'ivy_profile', default=self._DEFAULT_VERSION)
    self._classpath = None

  def ivy(self, java_executor=None, bootstrap_workunit_factory=None):
    """Returns an ivy instance bootstrapped by this bootstrapper.

    :param java_executor: the optional java executor to use
    :param bootstrap_workunit_factory: the optional workunit to bootstrap under.
    :raises: Bootstrapper.Error if ivy could not be bootstrapped
    """
    return Ivy(self._get_classpath(java_executor, bootstrap_workunit_factory),
               java_executor=java_executor,
               ivy_settings=self._ivy_settings,
               ivy_cache_dir=self.ivy_cache_dir)

  def _get_classpath(self, executor, workunit_factory):
    """Returns the bootstrapped ivy classpath as a list of jar paths.

    :raises: Bootstrapper.Error if the classpath could not be bootstrapped
    """
    if not self._classpath:
      self._classpath = self._bootstrap_ivy_classpath(executor, workunit_factory)
    return self._classpath

  @property
  def _ivy_settings(self):
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

  def _bootstrap_ivy_classpath(self, executor, workunit_factory, retry=True):
    # TODO(John Sirois): Extract a ToolCache class to control the path structure:
    # https://jira.twitter.biz/browse/DPB-283
    ivy_bootstrap_dir = \
      os.path.join(self._config.getdefault('pants_bootstrapdir'), 'tools', 'jvm', 'ivy')
    ivy_bootstrap_dir = os.path.expanduser(ivy_bootstrap_dir) # Support ~ in pants_bootstrapdir.

    digest = hashlib.sha1()
    if os.path.isfile(self._version_or_ivyxml):
      with open(self._version_or_ivyxml) as fp:
        digest.update(fp.read())
    else:
      digest.update(self._version_or_ivyxml)
    classpath = os.path.join(ivy_bootstrap_dir, '%s.classpath' % digest.hexdigest())

    if not os.path.exists(classpath):
      ivy = self._bootstrap_ivy(os.path.join(ivy_bootstrap_dir, 'bootstrap.jar'))
      args = ['-confs', 'default', '-cachepath', classpath]
      if os.path.isfile(self._version_or_ivyxml):
        args.extend(['-ivy', self._version_or_ivyxml])
      else:
        args.extend(['-dependency', 'org.apache.ivy', 'ivy', self._version_or_ivyxml])

      try:
        ivy.execute(args=args, executor=executor,
                    workunit_factory=workunit_factory, workunit_name='ivy-bootstrap')
      except ivy.Error as e:
        safe_delete(classpath)
        raise self.Error('Failed to bootstrap an ivy classpath! %s' % e)

    with open(classpath) as fp:
      cp = fp.read().strip().split(os.pathsep)
      if not all(map(os.path.exists, cp)):
        safe_delete(classpath)
        if retry:
          return self._bootstrap_ivy_classpath(executor, workunit_factory, retry=False)
        raise self.Error('Ivy bootstrapping failed - invalid classpath: %s' % ':'.join(cp))
      return cp

  def _bootstrap_ivy(self, bootstrap_jar_path):
    if not os.path.exists(bootstrap_jar_path):
      with temporary_file() as bootstrap_jar:
        fetcher = Fetcher()
        checksummer = fetcher.ChecksumListener(digest=hashlib.sha1())
        try:
          log.info('\nDownloading %s' % self._bootstrap_jar_url)
          # TODO: Capture the stdout of the fetcher, instead of letting it output
          # to the console directly.
          fetcher.download(self._bootstrap_jar_url,
                           listener=fetcher.ProgressListener().wrap(checksummer),
                           path_or_fd=bootstrap_jar,
                           timeout=self._timeout)
          log.info('sha1: %s' % checksummer.checksum)
          bootstrap_jar.close()
          touch(bootstrap_jar_path)
          shutil.move(bootstrap_jar.name, bootstrap_jar_path)
        except fetcher.Error as e:
          raise self.Error('Problem fetching the ivy bootstrap jar! %s' % e)

    return Ivy(bootstrap_jar_path,
               ivy_settings=self._ivy_settings,
               ivy_cache_dir=self.ivy_cache_dir)
