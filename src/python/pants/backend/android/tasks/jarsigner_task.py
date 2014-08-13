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

  def render_args(self, target, apk, key):
    # required flags for JDK 7+
    args = []
    args.extend(['-sigalg', 'SHA1withRSA'])
    args.extend(['-digestalg', ' SHA1'])
    args.extend(['-keystore', key.location])
    args.extend(['-storepass', key.keystore_password])
    args.extend(['-keypass', key.key_alias_password])
    args.extend(['-signedjar', (os.path.join(self.jarsigner_out(target), target.app_name + '-signed.apk'))])
    args.append(apk)
    args.append(key.keystore_alias)
    return args

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
                        args=args, workunit_name='jarsigner')

  #TODO IF we walk the target graph, how to pick the exact key in the dep? I think walk does this auto, though.

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
            for prod in prods:
              apk = prod
        else:
          raise ValueError(self, "There was no apk built that can be signed")

        # match the keystore in the target graph to the type of build ordered.
        # gradle produces both release and debug every run. My gut is against it, as of now.
        def get_key(tgt):
          if isinstance(tgt, Keystore):
            if tgt.type == build_type:
              keys.append(tgt)
          #TODO (mateor) raise an exception if no type match here!

        target.walk(get_key, predicate=isinstance(target,Keystore))
        if keys:
          for key in keys:
            args = self.render_args(target, apk, key)
            self._execute_jarsigner(args)

  def jarsigner_out(self, target):
    return os.path.join(self.workdir, target.app_name)

        # TODO (mateor) verify sig (jarsigner -verify -verbose -certs my_application.apk
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
