# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import logging
import os
import subprocess

from pants.backend.android.android_config_util import AndroidConfigUtil
from pants.backend.android.keystore.keystore_resolver import KeystoreResolver
from pants.backend.android.targets.android_binary import AndroidBinary
from pants.backend.core.tasks.task import Task
from pants.base.config import Config
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnit
from pants.java.distribution.distribution import Distribution
from pants.util.dirutil import safe_mkdir


logger = logging.getLogger(__name__)


class SignApkTask(Task):
  """Sign Android packages with keystores using the jarsigner tool."""

  _DEFAULT_KEYSTORE_CONFIG = 'android/keystore/default_config.ini'
  _CONFIG_SECTION = 'android-keystore-location'
  _CONFIG_OPTION = 'keystore_config_location'

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
    return ['signed_apk']

  def __init__(self, *args, **kwargs):
    super(SignApkTask, self).__init__(*args, **kwargs)
    self._distdir = self.get_options().pants_distdir
    self._config_file = self.get_options().keystore_config_location
    self._dist = None

  @property
  def config_file(self):
    """Path of .ini file containing definitions for backend.android.keystore_resolver.Keystore."""
    if self._config_file in (None, ""):
      try:
        self._config_file = self.context.config.get_required(self._CONFIG_SECTION,
                                                             self._CONFIG_OPTION )
      except Config.ConfigError:
       raise TaskError('The "[{0}]: {1}" option must declare the location of an .ini file '
                             'holding keystore definitions.'.format(self._CONFIG_SECTION,
                                                                    self._CONFIG_OPTION))
    return self._config_file

  @property
  def distribution(self):
    if self._dist is None:
      # Currently no Java 8 for Android. I considered max=1.7.0_50. See comment in render_args().
      self._dist = Distribution.cached(minimum_version='1.6.0_00',
                                       maximum_version='1.7.0_99',
                                       jdk=True)
    return self._dist

  def render_args(self, target, key, unsigned_apk, outdir):
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

    args = []
    args.append(self.distribution.binary('jarsigner'))

    # These first two params are required flags for JDK 7+
    args.extend(['-sigalg', 'SHA1withRSA'])
    args.extend(['-digestalg', 'SHA1'])

    args.extend(['-keystore', key.keystore_location])
    args.extend(['-storepass', key.keystore_password])
    args.extend(['-keypass', key.key_password])
    args.extend(['-signedjar', (os.path.join(outdir, target.app_name + '.' +
                                             key.build_type + '.signed.apk'))])
    args.append(unsigned_apk)
    args.append(key.keystore_alias)
    logger.debug('Executing: {0}'.format(' '.join(args)))
    return args

  def execute(self):
    targets = self.context.targets(self.is_signtarget)
    # Check for Android keystore config file (where the default keystore definition is kept).
    config_file = os.path.join(self.context.config.getdefault('pants_bootstrapdir'),
                               self._DEFAULT_KEYSTORE_CONFIG)
    if not os.path.isfile(config_file):
      try:
        AndroidConfigUtil.setup_keystore_config(config_file)
      except OSError as e:
        raise TaskError('Failed to setup keystore config: {0}'.format(e))

    with self.invalidated(targets) as invalidation_check:
      invalid_targets = []
      for vt in invalidation_check.invalid_vts:
        invalid_targets.extend(vt.targets)
      for target in invalid_targets:

        def get_products_path(target):
          """Get path of target's unsigned apks as created by AaptBuilder."""
          unsigned_apks = self.context.products.get('apk')
          if unsigned_apks.get(target):
            # This allows for multiple apks but we expect only one per target.
            for tgts, products in unsigned_apks.get(target).items():
              for prod in products:
                yield os.path.join(tgts, prod)

        packages = list(get_products_path(target))
        for unsigned_apk in packages:
          keystores = KeystoreResolver.resolve(self.config_file)
          for key in keystores:
            outdir = (self.sign_apk_out(target, key.keystore_name))
            safe_mkdir(outdir)
            args = self.render_args(target, key, unsigned_apk, outdir)
            with self.context.new_workunit(name='sign_apk',
                                           labels=[WorkUnit.MULTITOOL]) as workunit:
              returncode = subprocess.call(args, stdout=workunit.output('stdout'),
                                           stderr=workunit.output('stderr'))
              if returncode:
                raise TaskError('The SignApk jarsigner process exited non-zero: {0}'
                                .format(returncode))
              # I will handle the output products with the next CR for the final build step.

  def sign_apk_out(self, target, key_name):
    """Compute the outdir for a target, one outdir per keystore."""
    return os.path.join(self._distdir, target.app_name, key_name)
