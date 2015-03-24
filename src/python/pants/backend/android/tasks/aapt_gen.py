# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
import subprocess

from twitter.common.collections import OrderedSet

from pants.backend.android.targets.android_binary import AndroidBinary
from pants.backend.android.targets.android_resources import AndroidResources
from pants.backend.android.tasks.aapt_task import AaptTask
from pants.backend.codegen.tasks.code_gen import CodeGen
from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.base.address import SyntheticAddress
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnit
from pants.util.dirutil import safe_mkdir


logger = logging.getLogger(__name__)


class AaptGen(AaptTask, CodeGen):
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
  def _calculate_genfile(cls, package):
    return os.path.join(cls.package_path(package), 'R.java')

  def __init__(self, *args, **kwargs):
    super(AaptGen, self).__init__(*args, **kwargs)
    self._jar_library_by_sdk = {}

  def is_gentarget(self, target):
    return isinstance(target, AndroidBinary)

  def genlangs(self):
    return dict(java=lambda t: t.is_jvm)

  def is_forced(self, lang):
    return lang == 'java'

  def prepare_gen(self, targets):
    # prepare exactly N android jar targets where N is the number of SDKs in-play
    sdks = set(ar.target_sdk for ar in targets)
    for sdk in sdks:
      jar_url = 'file://{0}'.format(self.android_jar_tool(sdk))
      jar = JarDependency(org='com.google', name='android', rev=sdk, url=jar_url)
      address = SyntheticAddress(self.workdir, '{0}-jars'.format(sdk))
      self._jar_library_by_sdk[sdk] = self.context.add_new_target(address, JarLibrary, jars=[jar])

  def _render_args(self, target, resource_dirs, output_dir):
    """Compute the args that will be passed to the aapt tool."""
    args = []

    # Glossary of used aapt flags. Aapt handles a ton of action, this will continue to expand.
    #   : 'package' is the main aapt operation (see class docstring for more info).
    #   : '-m' is to "make" a package directory under location '-J'.
    #   : '-J' Points to the output directory.
    #   : '-M' is the AndroidManifest.xml of the project.
    #   : '-S' points to each dir in resource_dirs, aapt 'scans' them in order while
    #            collecting resources (resource priority is left -> right).
    #   : '-I' packages to add to base "include" set, here it is the android.jar of the target-sdk.
    args.extend([self.aapt_tool(target.build_tools_version)])
    args.extend(['package', '-m', '-J', output_dir])
    args.extend(['-M', target.manifest.path])
    args.append('--auto-add-overlay')
    while resource_dirs:
      # Priority for resources is left to right, so reverse the collection order of DFS preorder.
      args.extend(['-S', resource_dirs.pop()])
    args.extend(['-I', self.android_jar_tool(target.target_sdk)])
    args.extend(['--ignore-assets', self.ignored_assets])
    logger.debug('Executing: {0}'.format(' '.join(args)))
    return args

  def genlang(self, lang, targets):
    safe_mkdir(self.workdir)
    for target in targets:
      if lang != 'java':
        raise TaskError('Unrecognized android gen lang: {0}'.format(lang))
      resource_dirs = []
      def collect_resource_dirs(tgt):
        """Gather the 'resource_dir's of the target's AndroidResources dependencies."""
        if isinstance(tgt, AndroidResources):
          resource_dirs.append(os.path.join(get_buildroot(), tgt.resource_dir))

      if self.is_gentarget(target):
        target.walk(collect_resource_dirs)

      args = self._render_args(target, resource_dirs, self.workdir)
      with self.context.new_workunit(name='aapt_gen', labels=[WorkUnit.MULTITOOL]) as workunit:
        returncode = subprocess.call(args, stdout=workunit.output('stdout'),
                                     stderr=workunit.output('stderr'))
        if returncode:
          raise TaskError('The AaptGen process exited non-zero: {0}'.format(returncode))

  def createtarget(self, lang, gentarget, dependees):
    spec_path = os.path.join(os.path.relpath(self.workdir, get_buildroot()))
    address = SyntheticAddress(spec_path=spec_path, target_name=gentarget.id)
    aapt_gen_file = self._calculate_genfile(gentarget.manifest.package_name)
    deps = OrderedSet([self._jar_library_by_sdk[gentarget.target_sdk]])
    tgt = self.context.add_new_target(address,
                                      JavaLibrary,
                                      derived_from=gentarget,
                                      sources=[aapt_gen_file],
                                      dependencies=deps)
    for dependee in dependees:
      dependee.inject_dependency(tgt.address)
    return tgt
