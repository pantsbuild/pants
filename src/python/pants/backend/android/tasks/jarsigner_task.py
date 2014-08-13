# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import sys, io
import os
from stat import *

from pants.backend.android.targets.android_binary import AndroidBinary
from pants.backend.android.targets.keystore import Keystore
from pants.backend.android.tasks.android_task import AndroidTask
from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.build_environment import get_buildroot
from pants.base.workunit import WorkUnit
from pants.util.dirutil import safe_mkdir


  # need an err "We could not find a key at DEFAULT you need to xxxxxxxx

class JarsignerTask(NailgunTask):
  """Sign Android packages with keystore"""

  # For debug releases, we are using the debug key created with an install
  # of the Android SDK. This uses a keystore and key with a known passphrase.

  GITIGNORE = '.gitignore'
  _CONFIG_SECTION = 'jarsigner-tool'

  def __init__(self, *args, **kwargs):
    super(JarsignerTask, self).__init__(*args, **kwargs)
    #self.release = self.context.options.release_build or False
    #config_section = self.config_section
    #print ("release is %s" % self.release)

  def prepare(self, round_manager):
    round_manager.require_data('apk')

  @property
  def config_section(self):
    return self._CONFIG_SECTION

  @classmethod
  def is_signtarget(self, target):
    return isinstance(target, AndroidBinary)

  @classmethod
  def is_keytarget(self, target):
    return isinstance(target, Keystore)

  def render_args(self, apk, key):
    print("APK: {0}, KEY: {1}".format(apk,key))

  def check_permissions(self, file):
    """Ensure that the file permissions of the config are 640, rw-r----"""
    file = os.path.join('/Users/mateor/fred')
    with open(file) as f:
      content = f.readlines()
    print (content)
    permissions = (oct(os.stat(file)[ST_MODE]))
    if permissions is not '0100640':
      KeyError

  def _execute_jarsigner(self, args):

    classpath = ['jarsigner']
    java_main = 'sun.security.tools.jarsigner.Main'
    return self.runjava(classpath=classpath, main=java_main,
                        args=args, workunit_name='dx')

  #TODO IF we walk the target graph, how to pick the exact key in the dep? I think walk does this auto, though.

  def execute(self):
    safe_mkdir(self.workdir)
    with self.context.new_workunit(name='jarsigner', labels=[WorkUnit.MULTITOOL]):
      targets = self.context.targets(self.is_signtarget)
      for target in targets:
        build_type=target.build_type

        # get the unsigned apk
        unsigned_apks = self.context.products.get('apk')
        apk = unsigned_apks.get(target)
        if apk:
          target_apk = apk
        print(target_apk)

        build_type = target.build_type
        print ("POPEYE the build_type is %s" % build_type)
        key = []

        # match the keystore in the target graph to the type of build ordered.
        # gradle produces both release and debug every run. My gut is against it, as of now.
        def get_key(tgt):
          print(tgt)
          if isinstance(tgt, Keystore):
            print ("OLIVE OYL the tgt.type is %s" % tgt.type)
            if tgt.type == build_type:
              print ("SWEA'PEA we FOUND a match!")
              key.append(tgt)


        target.walk(get_key, predicate=isinstance(target,Keystore))
        if key:
          self.render_args(target_apk, key)

    #if debug
    #  if no config
    #    default to using the Android SDK's
    #    instantiate a Keystore object with default config in authentication.
    #  else:
    #     use keystore object from BUILD
    #else (is release):
    #   use release config (prop file permissions checked, name checked, and maybe location outside pants.


    # securing local passphrases

    # Storing in plaintext is not ideal. git, Maven and Gradle use cleartext config files as well.
    # As this is local only, we should at least not be worse than those existing implementations.
    # The protections I am using are
    #     * keystore_configs are separate from the BUILD file and the keystore_config.release is in .gitignore
    #     * mandating that the release_keystore matches RELEASE_KEYSTORE name and that RELEASE_KEYSTORE is present in gitconfig
    #     * mandate that the release_keystore.config is located outside of pants buildroot (can I?)
    #     * check for permissions of release_keystore, similar to ssh.
    #     * is there a good way to reliably handle the keys in kernel memory? Use keyring on supported machines?
