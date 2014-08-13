# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import sys, io
import os
import subprocess
from stat import *

from pants.backend.android.targets.android_binary import AndroidBinary
from pants.backend.android.targets.keystore import Keystore
from pants.backend.android.tasks.android_task import AndroidTask
from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnit
from pants.util.dirutil import safe_mkdir


class JarsignerTask(NailgunTask):
  """Sign Android packages with keystore"""

  GITIGNORE = '.gitignore'
  _CONFIG_SECTION = 'jarsigner-tool'

  @classmethod
  def is_signtarget(self, target):
    return isinstance(target, AndroidBinary)

  def __init__(self, *args, **kwargs):
    super(JarsignerTask, self).__init__(*args, **kwargs)
    self._java_dist = self._dist

  def prepare(self, round_manager):
    round_manager.require_data('apk')

  @property
  def config_section(self):
    return self._CONFIG_SECTION

  def render_args(self, target, unsigned_apk, key):
    # With JDK 1.7.0_51, jars without timestamps print a warning. This causes jars to stop working
    # pas their validity date. But Android purposefully passes 30 years validity. More research
    # is needed before passing a -tsa flag indiscriminately.
    # http://bugs.java.com/view_bug.do?bug_id=8023338
    args = []
    args.extend([self._java_dist.binary('jarsigner')])
    # first two are required flags for JDK 7+
    args.extend(['-sigalg', 'SHA1withRSA'])
    args.extend(['-digestalg', 'SHA1'])
    args.extend(['-keystore', key.location])
    args.extend(['-storepass', key.keystore_password])
    args.extend(['-keypass', key.key_password])
    args.extend(['-signedjar', (os.path.join(self.jarsigner_out(target), target.app_name
                                             + '-' + key.type + '-signed.apk')) ])
    args.append(unsigned_apk)
    args.append(key.keystore_alias)
    return args

  def execute(self):
    with self.context.new_workunit(name='jarsigner', labels=[WorkUnit.MULTITOOL]):
      targets = self.context.targets(self.is_signtarget)
      for target in targets:
        safe_mkdir(self.jarsigner_out(target))
        build_type = target.build_type
        keys = []
        # get the unsigned apk
        unsigned_apks = self.context.products.get('apk')
        target_apk = unsigned_apks.get(target)
        if target_apk:
          for tgts, prods in target_apk.iteritems():
            unsigned_path = os.path.join(tgts)
            for prod in prods:
              unsigned_apk = os.path.join(unsigned_path, prod)
        else:
          raise ValueError(self, "This target {0} did not have an apk built that can be "
                                 "signed".format(target))
        # match the keystore in the target graph to the type of build ordered.
        def get_key(tgt):
          if isinstance(tgt, Keystore):
            if tgt.type == build_type:
              keys.append(tgt)

        target.walk(get_key, predicate=isinstance(target,Keystore))
        if keys:
          # Perhaps we will soon allow depending pn multiple keys per type and match by name.
          if len(keys) > 1:
            raise TaskError(self, "This target {0} depends on more than one key of the same"
                                  "build type {1}. Please pick the key you wish to "
                                  "sign with".format(target, target.build_type))
            # TODO(mateor?)create Nailgun pipeline for other java tools, handling stderr/out, etc.
          process = subprocess.Popen(self.render_args(target, unsigned_apk, keys[0]))
          result = process.wait()
          if result != 0:
            raise TaskError('Android aapt tool exited non-zero ({code})'.format(code=result))
        else:
          raise TaskError(self, "No key matched the {0} target's build type "
                                "[release, debug]".format(target))

  def jarsigner_out(self, target):
    return os.path.join(self.workdir, target.app_name)

  # TODO (mateor) verify sig (jarsigner -verify -verbose -certs my_application.apk)
