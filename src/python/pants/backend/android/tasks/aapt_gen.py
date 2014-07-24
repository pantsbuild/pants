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
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError


# These are hardcoded into aapt but we added 'BUILD*'. Changes clobber, so we need entire string
IGNORED_ASSETS = ('!.svn:!.git:!.ds_store:!*.scc:.*:<dir>_*:!CVS:'
                  '!thumbs.db:!picasa.ini:!*~:BUILD*')


class AaptGen(AndroidTask, CodeGen):
  """
  Handle the processing of resources for Android targets with the
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

    option_group.add_option(mkflag("ignored-assets"), dest="ignored_assets", default=IGNORED_ASSETS,
                            help="[%default] Specifies regex patterns the aapt tools should "
                                 "ignore as it spiders down the resource_dir.")

  @classmethod
  def _calculate_genfile(cls, package):
    return os.path.join('bin', cls.package_path(package), 'R.java')

  def __init__(self, context, workdir):
    super(AaptGen, self).__init__(context, workdir)
    self._android_dist = self.android_sdk
    self._forced_build_tools_version = context.options.build_tools_version
    self._forced_ignored_assets = context.options.ignored_assets
    self._forced_target_sdk = context.options.target_sdk

  def is_gentarget(self, target):
    return isinstance(target, AndroidResources)

  def genlangs(self):
    return dict(java=lambda t: t.is_jvm)

  def is_forced(self, lang):
    return lang == 'java'

  def render_args(self, target, output_dir):
    args = []

    if self._forced_build_tools_version:
      args.append(self.aapt_tool(self._forced_build_tools_version))
    else:
      args.append(self.aapt_tool(target.build_tools_version))

    # Glossary of used aapt flags. Aapt handles a ton of action, this will continue to expand.
    #   : 'package' is the main aapt operation (see class docstring for more info).
    #   : '-m' is to "make" a package directory under location '-J'.
    #   : '-J' Points to the output directory.
    #   : '-M' is the AndroidManifest.xml of the project.
    #   : '-S' points to the resource_dir to "spider" down while collecting resources.
    #   : '-I' packages to add to base "include" set, here it is the android.jar of the target-sdk.

    args.extend(['package', '-m', '-J', output_dir, '-M', target.manifest,
                 '-S', target.resource_dir, '-I'])

    if self._forced_target_sdk:
      args.append(self.android_jar_tool(self._forced_target_sdk))
    else:
      args.append(self.android_jar_tool(target.target_sdk))

    if self._forced_ignored_assets:
      args.extend(['--ignore-assets', self._forced_ignored_assets])
    else:
      args.extend(['--ignore-assets', IGNORED_ASSETS])

    log.debug('Executing: {0}'.format(args))
    return args

  def genlang(self, lang, targets):
    aapt_out = os.path.join(self.workdir, 'bin')
    safe_mkdir(aapt_out)
    for target in targets:
      if lang != 'java':
        raise TaskError('Unrecognized android gen lang: {0!r}'.format(lang))
      process = subprocess.Popen(self.render_args(target, aapt_out))
      result = process.wait()
      if result != 0:
        raise TaskError('Android aapt tool exited non-zero ({code})'.format(code=result))

  def createtarget(self, lang, gentarget, dependees):
    aapt_gen_file = self._calculate_genfile(gentarget.package)
    spec_path = os.path.join(os.path.relpath(self.workdir, get_buildroot()), 'bin')
    address = SyntheticAddress(spec_path=spec_path, target_name=gentarget.id)
    tgt = self.context.add_new_target(address,
                                      JavaLibrary,
                                      derived_from=gentarget,
                                      sources=aapt_gen_file,
                                      dependencies=[])

    for dependee in dependees:
      dependee.inject_dependency(tgt.address)
    return tgt


  def _aapt_out(self):
    # TODO (mateor) Does this have potential for collision (chances of same package name?)
    return os.path.join(self.workdir, 'bin')

  def aapt_tool(self, build_tools_version):
    """Return the appropriate aapt tool.

    :param string build_tools_version: The Android build-tools version number (e.g. '19.1.0').
    """
    aapt = os.path.join('build-tools', build_tools_version, 'aapt')
    return self._android_dist.register_android_tool(aapt)

  def android_jar_tool(self, target_sdk):
    """Return the appropriate android.jar.

    :param string target_sdk: The Android SDK version number of the target (e.g. '18').
    """
    android_jar = os.path.join('platforms', 'android-' + target_sdk, 'android.jar')
    return self._android_dist.register_android_tool(android_jar)
