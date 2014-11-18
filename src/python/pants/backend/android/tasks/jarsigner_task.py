# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import subprocess

from pants.backend.android.targets.android_binary import AndroidBinary
from pants.backend.android.targets.keystore import Keystore
from pants.backend.core.tasks.task import Task
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnit
from pants.java.distribution.distribution import Distribution
from pants.util.dirutil import safe_mkdir


class JarsignerTask(Task):
  """Sign Android packages with keystore."""

  @classmethod
  def register_options(cls, register):
    super(JarsignerTask, cls).register_options(register)
    register('--build-type', choices=['debug', 'release'],
             help = 'Specifies the build type and keystore used to sign the package.')

  @classmethod
  def is_signtarget(cls, target):
    return isinstance(target, AndroidBinary)

  def __init__(self, *args, **kwargs):
    super(JarsignerTask, self).__init__(*args, **kwargs)
    self._distdir = self.context.config.getdefault('pants_distdir')
    self._build_type = self.get_options().build_type
    # No Java 8 for Android. I am considering max=1.7.0_50. See comment in render_args().
    self._dist = Distribution.cached(maximum_version="1.7.0_99")

  @property
  def distribution(self):
    return self._dist

  def prepare(self, round_manager):
    round_manager.require_data('apk')

  def render_args(self, target, unsigned_apk, key):
    """Create arg list for the jarsigner process.

    :param AndroidBinary target: Target to be signed
    :param string unsigned_apk: Location of the apk product from the AaptBuilder task.
    :param list key: List containing the Keystore object intended to sign the target.
    """
    # After JDK 1.7.0_51, jars without timestamps print a warning. This causes jars to stop working
    # past their validity date. But Android purposefully passes 30 years validity. More research
    # is needed before passing a -tsa flag indiscriminately.
    # http://bugs.java.com/view_bug.do?bug_id=8023338
    args = []
    args.extend([self.distribution.binary('jarsigner')])

    # first two are required flags for JDK 7+
    args.extend(['-sigalg', 'SHA1withRSA'])
    args.extend(['-digestalg', 'SHA1'])

    args.extend(['-keystore', key.location])
    args.extend(['-storepass', key.keystore_password])
    args.extend(['-keypass', key.key_password])
    args.extend(['-signedjar', (os.path.join(self.jarsigner_out(target), target.app_name
                                             + '-' + key.build_type + '-signed.apk'))])
    args.append(unsigned_apk)
    args.append(key.keystore_alias)
    return args

  def execute(self):
    with self.context.new_workunit(name='jarsigner', labels=[WorkUnit.MULTITOOL]):
      targets = self.context.targets(self.is_signtarget)
      with self.invalidated(targets) as invalidation_check:
        invalid_targets = []
        for vt in invalidation_check.invalid_vts:
          invalid_targets.extend(vt.targets)
        for target in invalid_targets:
          safe_mkdir(self.jarsigner_out(target))
          if self._build_type:
            build_type = self._build_type
          else:
            build_type = target.build_type
          keys = []

          def get_apk(target):
            """Return the unsigned.apk product from AaptBuilder."""
            unsigned_apks = self.context.products.get('apk')
            for tgts, prods in unsigned_apks.get(target).items():
              unsigned_path = os.path.join(tgts)
              for prod in prods:
                return os.path.join(unsigned_path, prod)

          def get_key(key):
            """Return Keystore objects that match the target's build_type."""
            if isinstance(key, Keystore):
              if key.build_type == build_type:
                keys.append(key)

          unsigned_apk = get_apk(target)
          target.walk(get_key)

          # Ensure there is only one key that matches the requested config.
          # Perhaps we will soon allow depending on multiple keys per type and match by name.
          if keys:
            if len(keys) > 1:
              raise TaskError(self, "This target: {0} depends on more than one key of the same "
                                    "build type [{1}]. Please pick just one key of each build type "
                                    "['debug', 'release']".format(target, target.build_type))
            # TODO(mateor?)create Nailgun pipeline for other java tools, handling stderr/out, etc.
            for key in keys:
              process = subprocess.Popen(self.render_args(target, unsigned_apk, key))
              result = process.wait()
              if result != 0:
                raise TaskError('Jarsigner tool exited non-zero ({code})'.format(code=result))
          else:
            raise TaskError(self, "No key matched the {0} target's build type "
                                  "[release, debug]".format(target))

  def jarsigner_out(self, target):
    return os.path.join(self._distdir, target.app_name)
