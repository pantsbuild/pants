# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
import subprocess

from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.java.distribution.distribution import DistributionLocator
from pants.task.task import Task
from pants.util.dirutil import safe_mkdir

from pants.contrib.android.android_config_util import AndroidConfigUtil
from pants.contrib.android.keystore.keystore_resolver import KeystoreResolver
from pants.contrib.android.targets.android_binary import AndroidBinary


logger = logging.getLogger(__name__)


class SignApkTask(Task):
  """Sign Android packages with keystores using the jarsigner tool."""

  _DEFAULT_KEYSTORE_CONFIG = 'android/keystore/default_config.ini'

  @classmethod
  def register_options(cls, register):
    super(SignApkTask, cls).register_options(register)
    register('--keystore-config-location',
             help='Location of the .ini file containing keystore definitions.')

  @classmethod
  def prepare(cls, options, round_manager):
    super(SignApkTask, cls).prepare(options, round_manager)
    round_manager.require_data('apk')

  @classmethod
  def is_signtarget(cls, target):
    return isinstance(target, AndroidBinary)

  @classmethod
  def product_types(cls):
    return ['release_apk']

  @classmethod
  def setup_default_config(cls, path):
    """Create the default keystore config file for Android targets.

    :param string path: Full path for the created default config file.
    """
    # TODO(mateor): Hook into pants global setup instead of relying on building an Android target.
    try:
      AndroidConfigUtil.setup_keystore_config(path)
    except AndroidConfigUtil.AndroidConfigError as e:
      raise TaskError('Failed to setup default keystore config: {0}'.format(e))

  @classmethod
  def signed_package_name(cls, target, build_type):
    """Get package name with 'build_type', a string KeyResolver mandates is in (debug, release)."""
    return '{0}.{1}.signed.apk'.format(target.manifest.package_name, build_type)

  def __init__(self, *args, **kwargs):
    super(SignApkTask, self).__init__(*args, **kwargs)
    self._config_file = self.get_options().keystore_config_location
    self._distdir = self.get_options().pants_distdir
    self._configdir = self.get_options().pants_configdir
    self._dist = None

  @property
  def config_file(self):
    if not self._config_file:
      raise TaskError('The --keystore_config_location option must be set.')
    return os.path.expanduser(self._config_file)

  @property
  def default_config_location(self):
    """Return the path where pants creates the default keystore config file.

    This location will hold the well-known definition of the debug keystore installed with the SDK.
    """
    return os.path.join(self._configdir, self._DEFAULT_KEYSTORE_CONFIG)

  @property
  def distribution(self):
    if self._dist is None:
      # Currently no Java 8 for Android. I considered max=1.7.0_50. See comment in _render_args().
      self._dist = DistributionLocator.cached(minimum_version='1.6.0_00',
                                              maximum_version='1.7.0_99',
                                              jdk=True)
    return self._dist

  def _render_args(self, target, key, unsigned_apk, outdir):
    """Create arg list for the jarsigner process.

    :param AndroidBinary target: Target to be signed.
    :param string unsigned_apk: Location of the apk product from the AaptBuilder task.
    :param Keystore key: Keystore instance with which to sign the android target.
    :param string outdir: output directory for the signed apk.
    """
    # After JDK 1.7.0_51, jars without timestamps print a warning. This causes jars to stop working
    # past their validity date. But Android purposefully passes 30 years validity. More research
    # is needed before passing a -tsa flag indiscriminately.
    # http://bugs.java.com/view_bug.do?bug_id=8023338

    args = [self.distribution.binary('jarsigner')]
    # These first two params are required flags for JDK 7+
    args.extend(['-sigalg', 'SHA1withRSA'])
    args.extend(['-digestalg', 'SHA1'])

    args.extend(['-keystore', key.keystore_location])
    args.extend(['-storepass', key.keystore_password])
    args.extend(['-keypass', key.key_password])
    args.extend(['-signedjar',
                 os.path.join(outdir, self.signed_package_name(target, key.build_type))])
    args.append(unsigned_apk)
    args.append(key.keystore_alias)
    logger.debug('Executing: {0}'.format(' '.join(args)))
    return args

  def execute(self):
    # One time setup of the default keystore config file.
    if not os.path.isfile(self.default_config_location):
      self.setup_default_config(self.default_config_location)

    targets = self.context.targets(self.is_signtarget)
    with self.invalidated(targets) as invalidation_check:
      invalid_targets = []
      for vt in invalidation_check.invalid_vts:
        invalid_targets.extend(vt.targets)
      for target in invalid_targets:

        def get_products_path(target):
          """Get path of target's unsigned apks as created by AaptBuilder."""
          unsigned_apks = self.context.products.get('apk')
          packages = unsigned_apks.get(target)
          if packages:
            for tgts, products in packages.items():
              for prod in products:
                yield os.path.join(tgts, prod)

        packages = list(get_products_path(target))
        for unsigned_apk in packages:
          keystores = KeystoreResolver.resolve(self.config_file)

          for key in keystores:
            outdir = self.sign_apk_out(target, keystores[key].build_type)
            safe_mkdir(outdir)
            args = self._render_args(target, keystores[key], unsigned_apk, outdir)
            with self.context.new_workunit(name='sign_apk',
                                           labels=[WorkUnitLabel.MULTITOOL]) as workunit:
              returncode = subprocess.call(args, stdout=workunit.output('stdout'),
                                           stderr=workunit.output('stderr'))
              if returncode:
                raise TaskError('The SignApk jarsigner process exited non-zero: {0}'
                                .format(returncode))

    for target in targets:
      release_path = self.sign_apk_out(target, 'release')
      release_apk = self.signed_package_name(target, 'release')

      if os.path.isfile(os.path.join(release_path, release_apk)):
        self.context.products.get('release_apk').add(target, release_path).append(release_apk)

  def sign_apk_out(self, target, build_type):
    """Compute the outdir for a target."""
    if build_type == 'release':
      # If it is a release build, it goes to the workdir for zipalign to operate upon.
      return os.path.join(self.workdir, target.name, build_type)
    elif build_type == 'debug':
      # Debug builds have completed all needed tasks so they can go straight to dist.
      return os.path.join(self._distdir, target.name)
