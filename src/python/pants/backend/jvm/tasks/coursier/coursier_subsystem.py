# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import hashlib
import logging
import os

from pants.base.build_environment import get_buildroot, get_pants_cachedir
from pants.base.workunit import WorkUnit, WorkUnitLabel
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
    super().register_options(register)
    register('--cache-dir', type=str, fingerprint=True,
             default=os.path.join(get_pants_cachedir(), 'coursier'),
             help='Version paired with --bootstrap-jar-url, in order to invalidate and fetch the new version.')
    register('--repos', type=list, fingerprint=True,
             help='Maven style repos', default=['https://repo1.maven.org/maven2'])
    register('--fetch-options', type=list, fingerprint=True,
             default=[
               # Quiet mode, so coursier does not show resolve progress,
               # but still prints results if --report is specified.
               '-q',
               # Do not use default public maven repo.
               '--no-default',
               # Concurrent workers
               '-n', '8',
             ],
             help='Additional options to pass to coursier fetch. See `coursier fetch --help`')
    register('--artifact-types', type=list, fingerprint=True,
             default=['jar', 'bundle', 'test-jar', 'maven-plugin', 'src', 'doc'],
             help='Specify the type of artifacts to fetch. See `packaging` at https://maven.apache.org/pom.html#Maven_Coordinates, '
                  'except `src` and `doc` being coursier specific terms for sources and javadoc.')
    # TODO(yic): Use a published version of Coursier. https://github.com/pantsbuild/pants/issues/6852
    register('--bootstrap-jar-url', fingerprint=True,
             default='https://github.com/coursier/coursier/releases/download/pants_release_1.5.x/coursier-cli-1.1.0.cf365ea27a710d5f09db1f0a6feee129aa1fc417.jar',
             help='Location to download a bootstrap version of Coursier.')
    register('--version', type=str, fingerprint=True,
             default='1.1.0.cf365ea27a710d5f09db1f0a6feee129aa1fc417',
             help='Version paired with --bootstrap-jar-url, in order to invalidate and fetch the new version.')
    register('--bootstrap-fetch-timeout-secs', type=int, advanced=True, default=10,
             help='Timeout the fetch if the connection is idle for longer than this value.')

  def bootstrap_coursier(self, workunit_factory):

    opts = self.get_options()
    bootstrap_url = opts.bootstrap_jar_url

    coursier_bootstrap_dir = os.path.join(opts.pants_bootstrapdir,
                                          'tools', 'jvm', 'coursier',
                                          opts.version)

    bootstrap_jar_path = os.path.join(coursier_bootstrap_dir, 'coursier.jar')

    if not os.path.exists(bootstrap_jar_path):
      with workunit_factory(name='bootstrap-coursier', labels=[WorkUnitLabel.TOOL]) as workunit:
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
