# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import hashlib
import logging
import os
import shutil

from pants.base.build_environment import get_buildroot
from pants.java.distribution.distribution import DistributionLocator
from pants.net.http.fetcher import Fetcher
from pants.subsystem.subsystem import Subsystem
from pants.util.contextutil import temporary_file
from pants.util.dirutil import touch


logger = logging.getLogger(__name__)


class CoursierSubsystem(Subsystem):
  """Common configuration items for ivy tasks.

  :API: public
  """
  options_scope = 'coursier'

  class Error(Exception):
    """Indicates an error bootstrapping coursier."""

  @classmethod
  def register_options(cls, register):
    super(CoursierSubsystem, cls).register_options(register)
    register('--fetch-options', type=list, fingerprint=True,
             help='Additional options to pass to coursier fetch. See `coursier fetch --help`')
    register('--bootstrap-jar-url', fingerprint=True,
             default='https://dl.dropboxusercontent.com/s/7tfwf1jj0e9mis6/coursier-cli.0.0.0.a3eccfacf2f4b1e4df0b48a4aa7cbe30b467a116.jar?dl=0',
             help='Location to download a bootstrap version of Coursier.')
    register('--version', type=str, fingerprint=True,
             default='0.0.0.a3eccfacf2f4b1e4df0b48a4aa7cbe30b467a116',
             help='Version paired with --bootstrap-jar-url, in order to invalidate and fetch the new version.')

  @classmethod
  def subsystem_dependencies(cls):
    return super(CoursierSubsystem, cls).subsystem_dependencies() + (DistributionLocator,)

  def bootstrap_coursier(self):

    bootstrap_url = self.get_options().bootstrap_jar_url

    coursier_bootstrap_dir = os.path.join(self.get_options().pants_bootstrapdir,
                                          'tools', 'jvm', 'coursier',
                                          self.get_options().version)

    bootstrap_jar_path = os.path.join(coursier_bootstrap_dir, 'coursier.jar')

    if not os.path.exists(bootstrap_jar_path):
      with temporary_file() as bootstrap_jar:
        fetcher = Fetcher(get_buildroot())
        checksummer = fetcher.ChecksumListener(digest=hashlib.sha1())
        try:
          logger.info('\nDownloading {}'.format(bootstrap_url))
          # TODO: Capture the stdout of the fetcher, instead of letting it output
          # to the console directly.
          fetcher.download(bootstrap_url,
                           listener=fetcher.ProgressListener().wrap(checksummer),
                           path_or_fd=bootstrap_jar,
                           timeout_secs=2)
          logger.info('sha1: {}'.format(checksummer.checksum))
          bootstrap_jar.close()
          touch(bootstrap_jar_path)
          shutil.move(bootstrap_jar.name, bootstrap_jar_path)
        except fetcher.Error as e:
          raise self.Error('Problem fetching the coursier bootstrap jar! {}'.format(e))

    return bootstrap_jar_path
