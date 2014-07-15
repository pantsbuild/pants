# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
import subprocess

from twitter.common import log
from twitter.common.dirutil import safe_mkdir

from pants.backend.android.targets.android_resources import AndroidResources
from pants.backend.android.tasks.android_task import AndroidTask
from pants.backend.codegen.tasks.code_gen import CodeGen
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.base.address import SyntheticAddress
from pants.base.exceptions import TaskError


class AaptGen(AndroidTask, CodeGen):
  """
  Handles the processing of resources for Android targets with the
  Android Asset Packaging Tool (aapt).

  The aapt tool supports 6 major commands: [dump, list, add, remove, crunch, package]
  For right now, pants is only supporting 'package'. More to come as we support Release builds
  (crunch, at minimum).

  Commands and flags for aapt can be seen here:
  https://android.googlesource.com/platform/frameworks/base/+/master/tools/aapt/Command.cpp
  """
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    super(AaptGen, cls).setup_parser(option_group, args, mkflag)

    option_group.add_option(mkflag("target-sdk"), dest="target_sdk",
                            help="[%default] Specifies the target Android SDK used to compile "
                                 "resources. Overrides AndroidManifest.xml.")

    option_group.add_option(mkflag("build-tools-version"), dest="build_tools_version",
                            help="[%default] Specifies the Android build-tools version used "
                                 "to compile resources.")

  def __init__(self, context, workdir):
    super(AaptGen, self).__init__(context, workdir)
    lang = 'java'
    self.gen_langs=set()
    self.gen_langs.add(lang)
    # self._dist is an AndroidDistribution inherited from AndroidTask
    self.dist = self._dist
    self.forced_target_sdk = context.options.target_sdk
    self.forced_build_tools_version = context.options.build_tools_version

  def is_gentarget(self, target):
    return isinstance(target, AndroidResources)

  def genlangs(self):
    return dict(java=lambda t: t.is_jvm)

  def is_forced(self, lang):
    return lang in self.gen_langs

  def render_args(self, target):
    output_dir = self._aapt_out(target)
    safe_mkdir(output_dir)
    args = []

    if self.forced_build_tools_version:
      args.append(self.aapt_tool(self.forced_build_tools_version))
    else:
      args.append(self.aapt_tool(target.build_tools_version))
    args.extend(['package', '-m', '-J', output_dir, '-M', target.manifest,
                 '-S', target.resource_dir, '-I'])
    if self.forced_target_sdk:
      args.append(self.android_jar_tool(self.forced_target_sdk))
    else:
      args.append(self.android_jar_tool(target.target_sdk))

    # BUILD files in the resource folder chokes aapt. This is a defensive measure.
    ignored_assets='!.svn:!.git:!.ds_store:!*.scc:.*:<dir>_*:!CVS:' \
                   '!thumbs.db:!picasa.ini:!*~:BUILD*'
    args.extend(['--ignore-assets', ignored_assets])
    log.debug('Executing: {0}'.format(args))
    return args


  def genlang(self, lang, targets):
    for target in targets:
      if lang != 'java':
        raise TaskError('Unrecognized android gen lang: {0!r}'.format(lang))
      process = subprocess.Popen(self.render_args(target))
      result = process.wait()
      if result != 0:
        raise TaskError('Android aapt exited non-zero ({code})'.format(code=result))

  def createtarget(self, lang, gentarget, dependees):
    aapt_gen_file = self._calculate_genfile(self._aapt_out(gentarget),gentarget.package)
    address = SyntheticAddress(spec_path=aapt_gen_file, target_name = gentarget.id)
    tgt = self.context.add_new_target(address,
                                      JavaLibrary,
                                      derived_from=gentarget,
                                      sources=['R.java'],
                                      dependencies=[])

    for dependee in dependees:
      dependee.inject_dependency(tgt.address)
    return tgt

  @classmethod
  def package_path(self, package):
    return package.replace('.', os.sep)

  @classmethod
  def _calculate_genfile(self, path, package):
    return os.path.join(path, self.package_path(package))

  def _aapt_out(self, target):
    # This mimics the Eclipse layout. We may switch to gradle style sometime in the future.
    return os.path.join(self.workdir, 'bin')

  def aapt_tool(self, build_tools_version):
    """Return the appropriate aapt tool.

    :param string build_tools_version: The version number of the Android build-tools.
    """
    aapt = os.path.join('build-tools', build_tools_version, 'aapt')
    return self.dist.registered_android_tool(aapt)

  def android_jar_tool(self, target_sdk):
    """Return the appropriate android.jar.

    :param string target_sdk: The version number of the Android SDK.
    """
    android_jar = os.path.join('platforms', 'android-' + target_sdk, 'android.jar')
    return self.dist.registered_android_tool(android_jar)
