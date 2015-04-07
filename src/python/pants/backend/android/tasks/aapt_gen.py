# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
import subprocess

from pants.backend.android.targets.android_binary import AndroidBinary
from pants.backend.android.targets.android_library import AndroidLibrary
from pants.backend.android.targets.android_resources import AndroidResources
from pants.backend.android.tasks.aapt_task import AaptTask
from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.base.address import SyntheticAddress
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnit
from pants.util.dirutil import safe_mkdir


logger = logging.getLogger(__name__)

class AaptGen(AaptTask):
  """
  Handle the processing of resources for Android targets with the
  Android Asset Packaging Tool (aapt).

  The aapt tool supports 6 major commands: [dump, list, add, remove, crunch, package]
  For right now, pants supports 'package'.

  Commands and flags for aapt can be seen here:
  https://android.googlesource.com/platform/frameworks/base/+/master/tools/aapt/Command.cpp
  """

  @classmethod
  def _calculate_genfile(cls, package):
    """Name of the file produced by aapt."""
    # The aapt tool determines this information by parsing the manifest of the target.
    return os.path.join(cls.package_path(package), 'R.java')

  @staticmethod
  def is_aapt_target(target):
    """Return True for AndroidBinary targets."""
    return isinstance(target, AndroidBinary)

  def __init__(self, *args, **kwargs):
    super(AaptGen, self).__init__(*args, **kwargs)
    self._jar_library_by_sdk = {}

  def create_sdk_jar_deps(self, targets):
    """Create a JarLibrary target for every sdk in play.

    :param list targets: A list of AndroidBinary targets.
    """
    # Prepare exactly N android jar targets where N is the number of SDKs in-play.
    sdks = set(ar.target_sdk for ar in targets)
    for sdk in sdks:
      jar_url = 'file://{0}'.format(self.android_jar_tool(sdk))
      jar = JarDependency(org='com.google', name='android', rev=sdk, url=jar_url)
      address = SyntheticAddress(self.workdir, 'android-{0}.jar'.format(sdk))
      self._jar_library_by_sdk[sdk] = self.context.add_new_target(address, JarLibrary, jars=[jar])

  def _render_args(self, target, sdk, resource_dirs, output_dir):
    """Compute the args that will be passed to the aapt tool.

    :param AndroidResources target: Target resources to be processed.
    :param string sdk: The SDK version of the android.jar included with the processing.
    :param list resource_dirs: List of resource_dirs to include in this invocation of the aapt tool.
    :param string output_dir: Output location for the directories and R.java created by aapt.
    """

    # Glossary of used aapt flags.
    #   : 'package' is the main aapt operation (see class docstring for more info).
    #   : '-m' is to "make" a package directory under location '-J'.
    #   : '-J' Points to the output directory.
    #   : '-M' is the AndroidManifest.xml of the project.
    #   : '--auto-add-overlay' automatically add resources that are only in overlays.
    #   : '-S' points to each dir in resource_dirs, aapt 'scans' them in order while
    #            collecting resources (resource priority is left -> right).
    #   : '-I' packages to add to base 'include' set, here it is the android.jar of the target sdk.
    #   : '--ignore-assets' the aapt tool will disregard any files matching that pattern.
    args = [self.aapt_tool(target.build_tools_version)]
    args.extend(['package', '-m', '-J', output_dir])
    args.extend(['-M', target.manifest.path])
    args.append('--auto-add-overlay')
    while resource_dirs:
      # Priority for resources is left->right, so reverse the order it was collected (DFS preorder).
      args.extend(['-S', resource_dirs.pop()])
    args.extend(['-I', self.android_jar_tool(sdk)])
    args.extend(['--ignore-assets', self.ignored_assets])
    logger.debug('Executing: {0}'.format(' '.join(args)))
    return args

  def execute(self):
    # Every android_binary and each android_library dependency must have its resources processed
    # into separate R.java files.
    # The number of R.java files produced from each library is <= |sdks in play|.
    targets = self.context.targets(self.is_aapt_target)
    self.create_sdk_jar_deps(targets)
    for target in targets:
      sdk = target.target_sdk
      outdir = self.aapt_out(sdk)

      gentargets = [target]
      def gather_gentargets(tgt):
        """Gather targets that have an AndroidResources dependency."""
        if isinstance(tgt, AndroidLibrary):
          gentargets.append(tgt)
      target.walk(gather_gentargets)

      # TODO(mateo) add invalidation framework. Adding it here doesn't work right now because the
      # framework can't differentiate between one library that has to be compiled by multiple sdks.
      # We can try some things with the BUILD file rework that'd be up next in a perfect world.
      for targ in gentargets:

        # If a library does not specify a target_sdk, use the sdk of its dependee binary.
        used_sdk = targ.manifest.target_sdk if targ.manifest.target_sdk else sdk

        resource_dirs = []
        for dep in targ.closure():
          # A target's resources, as well as the resources of its transitive deps, are needed.
          if isinstance(dep, AndroidResources):
            resource_dirs.append(dep.resource_dir)

        args = self._render_args(targ, used_sdk, resource_dirs, outdir)
        with self.context.new_workunit(name='aapt_gen', labels=[WorkUnit.MULTITOOL]) as workunit:
          returncode = subprocess.call(args, stdout=workunit.output('stdout'),
                                       stderr=workunit.output('stderr'))
          if returncode:
            raise TaskError('The AaptGen process exited non-zero: {}'.format(returncode))

        new_target = self.create_target(targ, sdk)
        targ.inject_dependency(new_target.address)

  def create_target(self, gentarget, sdk):
    """Create a JavaLibrary target for the R.java files created by the aapt tool.

    :param AndroidTarget gentarget: An android_binary or android_library that owns resources.
    :param string sdk: The Android SDK version of the android.jar that the created target will
      depend on.
    """
    spec_path = os.path.join(os.path.relpath(self.aapt_out(sdk), get_buildroot()))
    address = SyntheticAddress(spec_path=spec_path, target_name=gentarget.id)
    aapt_gen_file = self._calculate_genfile(gentarget.manifest.package_name)
    deps = [self._jar_library_by_sdk[sdk]]
    tgt = self.context.add_new_target(address,
                                      JavaLibrary,
                                      derived_from=gentarget,
                                      sources=[aapt_gen_file],
                                      dependencies=deps)
    return tgt

  def aapt_out(self, sdk):
    """Location for the output of the aapt invocation.

    :param string sdk: The Android SDK version to be used when processing the resources.
    """
    outdir = os.path.join(self.workdir, sdk)
    safe_mkdir(outdir)
    return outdir
