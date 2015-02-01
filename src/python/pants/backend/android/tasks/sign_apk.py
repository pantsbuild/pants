# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

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

from twitter.common import log


class SignApkTask(Task):
  """Sign Android packages with keystores using the jarsigner tool."""

  _DEFAULT_KEYSTORE_CONFIG = 'android/keystore/default_config.ini'
  _CONFIG_SECTION = 'android-keystore-location'

  @classmethod
  def register_options(cls, register):
    super(SignApkTask, cls).register_options(register)
    register('--keystore-config-location',
             help='Location of the .ini file containing keystore definitions.')

  @classmethod
  def prepare(self, options, round_manager):
    round_manager.require_data('apk')

  @classmethod
  def is_signtarget(cls, target):
    return isinstance(target, AndroidBinary)

  @classmethod
  def product_types(cls):
    return ['signed_apk']

  def __init__(self, *args, **kwargs):
    super(SignApkTask, self).__init__(*args, **kwargs)
    self._distdir = self.context.config.getdefault('pants_distdir')
    self._config_file = self.get_options().keystore_config_location
    self._dist = None

  @property
  def config_file(self):
    """Path of .ini file containing definitions for backend.android.keystore_resolver.Keystore."""
    if self._config_file in (None, ""):
      try:
        self._config_file = self.context.config.get_required(self._CONFIG_SECTION,
                                                             'keystore_config_location')
      except Config.ConfigError:
       raise TaskError(self, "To sign .apks an '{0}' option must declare the location of an "
                             ".ini file holding keystore definitions.".format(self._CONFIG_SECTION))
    return self._config_file

  @property
  def distribution(self):
    if self._dist is None:
      # Currently no Java 8 for Android. I considered max=1.7.0_50. See comment in render_args().
      self._dist = Distribution.cached(minimum_version='1.6.0_00',
                                       maximum_version="1.7.0_99",
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
    args.extend([self.distribution.binary('jarsigner')])

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
    log.debug('Executing: {0}'.format(args))
    return args

  def execute(self):
    targets = self.context.targets(self.is_signtarget)
    # Check for Android keystore config file (where the default keystore definition is kept).
    config_dir = os.path.join(self.context.config.getdefault('pants_bootstrapdir'),
                              self._DEFAULT_KEYSTORE_CONFIG)
    if not os.path.isfile(config_dir):
      try:
        AndroidConfigUtil.setup_keystore_config(config_dir)
      except OSError as e:
        raise TaskError(self, e)

    with self.invalidated(targets) as invalidation_check:
      invalid_targets = []
      for vt in invalidation_check.invalid_vts:
        invalid_targets.extend(vt.targets)
      for target in invalid_targets:

          def get_apk(target):
            """Get a handle for the unsigned.apk product created by AaptBuilder."""
            unsigned_apks = self.context.products.get('apk')
            for tgts, products in unsigned_apks.get(target).items():
              unsigned_path = os.path.join(tgts)
              for prod in products:
                return os.path.join(unsigned_path, prod)

          unsigned_apk = get_apk(target)
          keystores = KeystoreResolver.resolve(self.config_file)
          for key in keystores:
            outdir = (self.sign_apk_out(target, key.keystore_name))
            safe_mkdir(outdir)
            with self.context.new_workunit(name='sign_apk',
                                           labels=[WorkUnit.MULTITOOL]) as workunit:
              args = self.render_args(target, key, unsigned_apk, outdir)
              process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
              stdout, stderr = process.communicate()

              if workunit:
                workunit.output('stdout').write(stdout)
                workunit.output('stderr').write(stderr)
              workunit.set_outcome(WorkUnit.FAILURE if process.returncode else WorkUnit.SUCCESS)
              if process.returncode:
                raise TaskError('This SignApk jarsigner command exited non-zero: {0}'
                                .format(stdout))
              # I will handle the output products with the next CR for the final step in the build.

  def sign_apk_out(self, target, key_name):
    """Compute the outdir for a target, one outdir per keystore."""
    return os.path.join(self._distdir, target.app_name, key_name)
