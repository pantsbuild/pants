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

  #TODO (mateor) if we are going to keep a debug key in repo, it should go in 3rdparty/android

  @classmethod
  def is_signtarget(self, target):
    return isinstance(target, AndroidBinary)

  @classmethod
  def is_keytarget(self, target):
    return isinstance(target, Keystore)

  def debug_fields(self):
    pass

  def check_permissions(self, file):
    """Ensure that the file permissions of the config are 640, rw-r----"""
    file = os.path.join('/Users/mateor/fred')
    with open(file) as f:
      content = f.readlines()
    print (content)
    permissions = (oct(os.stat(file)[ST_MODE]))
    if permissions is not '0100640':
      KeyError

  def jarsigner_tool(self):
    pass

  #TODO IF we walk the target graph, how to pick the exact key in the dep? I think walk does this auto, though.

  def execute(self):
    with self.context.new_workunit(name='jarsigner', labels=[WorkUnit.MULTITOOL]):
      targets = self.context.targets(self.is_signtarget)
      print("I am taking a metro to see the giraffe show")
      for target in targets:
        build_type=target.build_type
        print(target)
        safe_mkdir(self.workdir)
        unsigned_apks = self.context.products.get('apk')
        print(unsigned_apks)
        apk = unsigned_apks.get(target)
        if apk:
          target_apk = apk
        print(target_apk)
        build_type = target.build_type
        print ("POPEYE the build_type is %s" % build_type)
        key = []
        #
        # #for key in keys_by_target:
        #  # print("Dems da keys: ")
        #  # print(key)
        #
        def get_key(tgt):
          print(tgt)
          if isinstance(tgt, Keystore):
            print ("OLIVE OYL the tgt.type is %s" % tgt.type)
            if tgt.type == build_type:
              print ("Swee'pea we FOUND a match!")
              key.append(tgt)
              return tgt

          # if target_apk:
          #   # This does comes back None, you need the protection here.
          #   print("WE shhould see th sea from thee")
          #   return target_apk
        #     # def add_classes(target_products):
        #     #   for root, products in target_products.abs_paths():
        #     #     for prod in products:
        #     #       classes.append(prod)
        #     #
        #     # add_classes(target_classes)

      keystore = target.walk(get_key, predicate=isinstance(target,Keystore))
      print ("Here we are again on the keystore")
      print(keystore)
      print(key)

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
