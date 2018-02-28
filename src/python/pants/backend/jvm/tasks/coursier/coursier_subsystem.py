# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import hashlib
import logging
import os

from pants.base.build_environment import get_buildroot
from pants.base.workunit import WorkUnit, WorkUnitLabel
from pants.java.distribution.distribution import DistributionLocator
from pants.net.http.fetcher import Fetcher
from pants.subsystem.subsystem import Subsystem
from pants.util.dirutil import safe_concurrent_creation


logger = logging.getLogger(__name__)


class CoursierSubsystem(Subsystem):
  """Common configuration items for coursier tasks.

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
             default='https://dl.dropboxusercontent.com/s/a1xr4qxzj5aoait/coursier-cli-1.0.2.3e4a65d5ee66f043c2467972bd6e29f48b570715.jar?dl=0',
             help='Location to download a bootstrap version of Coursier.')
    # TODO(wisechengyi): currently using a custom url for fast iteration.
    # Once the coursier builds are stable, move the logic to binary_util. https://github.com/pantsbuild/pants/issues/5381
    # Ths sha in the version corresponds to the sha in the PR https://github.com/coursier/coursier/pull/774
    # The jar is built by following https://github.com/coursier/coursier/blob/master/DEVELOPMENT.md#build-with-pants
    register('--version', type=str, fingerprint=True,
             default='1.0.2.3e4a65d5ee66f043c2467972bd6e29f48b570715',
             help='Version paired with --bootstrap-jar-url, in order to invalidate and fetch the new version.')
    register('--bootstrap-fetch-timeout-secs', type=int, advanced=True, default=10,
             help='Timeout the fetch if the connection is idle for longer than this value.')

  @classmethod
  def subsystem_dependencies(cls):
    return super(CoursierSubsystem, cls).subsystem_dependencies() + (DistributionLocator,)

  def bootstrap_coursier(self, workunit_factory):

    opts = self.get_options()
    bootstrap_url = opts.bootstrap_jar_url

    coursier_bootstrap_dir = os.path.join(opts.pants_bootstrapdir,
                                          'tools', 'jvm', 'coursier',
                                          opts.version)

    bootstrap_jar_path = os.path.join(coursier_bootstrap_dir, 'coursier.jar')

    with workunit_factory(name='bootstrap-coursier', labels=[WorkUnitLabel.TOOL]) as workunit:

      if not os.path.exists(bootstrap_jar_path):
        with safe_concurrent_creation(bootstrap_jar_path) as temp_path:
          fetcher = Fetcher(get_buildroot())
          checksummer = fetcher.ChecksumListener(digest=hashlib.sha1())
          try:
            logger.info('\nDownloading {}'.format(bootstrap_url))
            # TODO: Capture the stdout of the fetcher, instead of letting it output
            # to the console directly.
            fetcher.download(bootstrap_url,
                             listener=fetcher.ProgressListener().wrap(checksummer),
                             path_or_fd=temp_path,
                             timeout_secs=opts.bootstrap_fetch_timeout_secs)
            logger.info('sha1: {}'.format(checksummer.checksum))
          except fetcher.Error as e:
            workunit.set_outcome(WorkUnit.FAILURE)
            raise self.Error('Problem fetching the coursier bootstrap jar! {}'.format(e))
          else:
            workunit.set_outcome(WorkUnit.SUCCESS)

      return bootstrap_jar_path
