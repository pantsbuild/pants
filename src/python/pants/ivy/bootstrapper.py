# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import hashlib
import logging
import os
import shutil

from pants.ivy.ivy import Ivy
from pants.ivy.ivy_subsystem import IvySubsystem
from pants.net.http.fetcher import Fetcher
from pants.util.contextutil import temporary_file
from pants.util.dirutil import safe_delete, touch


logger = logging.getLogger(__name__)


class Bootstrapper(object):
  """Bootstraps a working ivy resolver.

  By default a working resolver will be bootstrapped from maven central and it will use standard
  public jar repositories and a standard ivy local cache directory to execute resolve operations.

  By default ivy will be bootstrapped from a stable ivy jar version found in maven central, but
  this can be over-ridden with the ``--ivy-bootstrap-jar-url`` option.  Additionally the
  bootstrapping will use a connect/read timeout of 1 second by default, but this can be raised by
  specifying a ``--ivy-bootstrap-fetch-timeout-secs`` option.

  After bootstrapping, ivy will re-resolve itself.  By default it does this via maven central, but
  a custom ivy tool classpath can be specified by using the ``--ivy-ivy-profile`` option to point to
  a custom ivy profile ivy.xml.  This can be useful to upgrade ivy to a version released after pants
  or else mix in auxiliary jars that provide ivy plugins.

  Finally, by default the ivysettings.xml embedded in the ivy jar will be used in conjunction with
  the default ivy local cache directory of ~/.ivy2/cache.  To specify custom values for these you
  can either provide ``--ivy-ivy-settings`` and ``--ivy-cache-dir`` options.
  """

  class Error(Exception):
    """Indicates an error bootstrapping an ivy classpath."""

  _INSTANCE = None

  @classmethod
  def default_ivy(cls, bootstrap_workunit_factory=None):
    """Returns an Ivy instance using the default global bootstrapper.

    By default runs ivy via a subprocess java executor.  Callers of execute() on the returned
    Ivy instance can provide their own executor.

    :param bootstrap_workunit_factory: the optional workunit to bootstrap under.
    :returns: an Ivy instance.
    :raises: Bootstrapper.Error if the default ivy instance could not be bootstrapped
    """
    return cls.instance().ivy(bootstrap_workunit_factory=bootstrap_workunit_factory)

  def __init__(self, ivy_subsystem=None):
    """Creates an ivy bootstrapper."""
    self._ivy_subsystem = ivy_subsystem or IvySubsystem.global_instance()
    self._version_or_ivyxml = self._ivy_subsystem.get_options().ivy_profile
    self._classpath = None

  @classmethod
  def instance(cls):
    """:returns: the default global ivy bootstrapper.
    :rtype: Bootstrapper
    """
    if cls._INSTANCE is None:
      cls._INSTANCE = Bootstrapper()
    return cls._INSTANCE

  @classmethod
  def reset_instance(cls):
    cls._INSTANCE = None

  def ivy(self, bootstrap_workunit_factory=None):
    """Returns an ivy instance bootstrapped by this bootstrapper.

    :param bootstrap_workunit_factory: the optional workunit to bootstrap under.
    :raises: Bootstrapper.Error if ivy could not be bootstrapped
    """
    return Ivy(self._get_classpath(bootstrap_workunit_factory),
               ivy_settings=self._ivy_subsystem.get_options().ivy_settings,
               ivy_cache_dir=self._ivy_subsystem.get_options().cache_dir,
               extra_jvm_options=self._ivy_subsystem.extra_jvm_options())

  def _get_classpath(self, workunit_factory):
    """Returns the bootstrapped ivy classpath as a list of jar paths.

    :raises: Bootstrapper.Error if the classpath could not be bootstrapped
    """
    if not self._classpath:
      self._classpath = self._bootstrap_ivy_classpath(workunit_factory)
    return self._classpath

  def _bootstrap_ivy_classpath(self, workunit_factory, retry=True):
    # TODO(John Sirois): Extract a ToolCache class to control the path structure:
    # https://jira.twitter.biz/browse/DPB-283

    ivy_bootstrap_dir = os.path.join(self._ivy_subsystem.get_options().pants_bootstrapdir,
                                     'tools', 'jvm', 'ivy')
    digest = hashlib.sha1()
    if os.path.isfile(self._version_or_ivyxml):
      with open(self._version_or_ivyxml) as fp:
        digest.update(fp.read())
    else:
      digest.update(self._version_or_ivyxml)
    classpath = os.path.join(ivy_bootstrap_dir, '{}.classpath'.format(digest.hexdigest()))

    if not os.path.exists(classpath):
      ivy = self._bootstrap_ivy(os.path.join(ivy_bootstrap_dir, 'bootstrap.jar'))
      args = ['-confs', 'default', '-cachepath', classpath]
      if os.path.isfile(self._version_or_ivyxml):
        args.extend(['-ivy', self._version_or_ivyxml])
      else:
        args.extend(['-dependency', 'org.apache.ivy', 'ivy', self._version_or_ivyxml])

      try:
        ivy.execute(args=args, workunit_factory=workunit_factory, workunit_name='ivy-bootstrap')
      except ivy.Error as e:
        safe_delete(classpath)
        raise self.Error('Failed to bootstrap an ivy classpath! {}'.format(e))

    with open(classpath) as fp:
      cp = fp.read().strip().split(os.pathsep)
      if not all(map(os.path.exists, cp)):
        safe_delete(classpath)
        if retry:
          return self._bootstrap_ivy_classpath(workunit_factory, retry=False)
        raise self.Error('Ivy bootstrapping failed - invalid classpath: {}'.format(':'.join(cp)))
      return cp

  def _bootstrap_ivy(self, bootstrap_jar_path):
    if not os.path.exists(bootstrap_jar_path):
      with temporary_file() as bootstrap_jar:
        fetcher = Fetcher()
        checksummer = fetcher.ChecksumListener(digest=hashlib.sha1())
        try:
          logger.info('\nDownloading {}'.format(self._ivy_subsystem.get_options().bootstrap_jar_url))
          # TODO: Capture the stdout of the fetcher, instead of letting it output
          # to the console directly.
          fetcher.download(self._ivy_subsystem.get_options().bootstrap_jar_url,
                           listener=fetcher.ProgressListener().wrap(checksummer),
                           path_or_fd=bootstrap_jar,
                           timeout_secs=self._ivy_subsystem.get_options().bootstrap_fetch_timeout_secs)
          logger.info('sha1: {}'.format(checksummer.checksum))
          bootstrap_jar.close()
          touch(bootstrap_jar_path)
          shutil.move(bootstrap_jar.name, bootstrap_jar_path)
        except fetcher.Error as e:
          raise self.Error('Problem fetching the ivy bootstrap jar! {}'.format(e))

    return Ivy(bootstrap_jar_path,
               ivy_settings=self._ivy_subsystem.get_options().ivy_settings,
               ivy_cache_dir=self._ivy_subsystem.get_options().cache_dir)
