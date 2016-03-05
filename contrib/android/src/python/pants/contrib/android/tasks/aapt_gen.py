# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
import subprocess

from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.build_graph.address import Address
from pants.util.dirutil import safe_mkdir

from pants.contrib.android.targets.android_library import AndroidLibrary
from pants.contrib.android.targets.android_resources import AndroidResources
from pants.contrib.android.tasks.aapt_task import AaptTask


logger = logging.getLogger(__name__)


class AaptGen(AaptTask):
  """Process resources for Android targets with the Android Asset Packaging Tool (aapt).

  The aapt tool supports 6 major commands: [dump, list, add, remove, crunch, package]
  For right now, pants supports 'package'.

  Commands and flags for aapt can be seen here:
  https://android.googlesource.com/platform/frameworks/base/+/master/tools/aapt/Command.cpp

  The resources are processed against a set of APIs found in the android.jar that corresponds to
  the target's target_sdk. AndroidBinary files must declare a target_sdk in their manifest.
  AndroidLibrary targets are processed with the target_sdk of the dependee AndroidBinary.
  An AndroidLibrary will need to be processed once for every target_sdk that it supports.

  Each AndroidLibrary is processed individually. AndroidBinary targets are processed along with
  all of the AndroidLibrary targets in its transitive closure. The output of an AaptGen invocation
  is an R.java file that allows programmatic access to resources, one each for all AndroidBinary
  and AndroidLibrary targets.
  """

  @classmethod
  def _relative_genfile(cls, target):
    """Name of the file produced by aapt."""
    return os.path.join(cls.package_path(target.manifest.package_name), 'R.java')

  @classmethod
  def prepare(cls, options, round_manager):
    super(AaptGen, cls).prepare(options, round_manager)
    round_manager.require_data('unpacked_libraries')

  def __init__(self, *args, **kwargs):
    super(AaptGen, self).__init__(*args, **kwargs)
    self._jar_library_by_sdk = {}
    self._created_library_targets = {}

  def create_sdk_jar_deps(self, binaries):
    """Create a JarLibrary target for every sdk in play.

    :param list binaries: A list of AndroidBinary targets.
    """
    # Prepare exactly N android jar targets where N is the number of SDKs in-play.
    for binary in binaries:
      sdk = binary.target_sdk
      if sdk not in self._jar_library_by_sdk:
        jar_url = 'file://{0}'.format(self.android_jar(binary))
        jar = JarDependency(org='com.google', name='android', rev=sdk, url=jar_url)
        address = Address(self.workdir, 'android-{0}.jar'.format(sdk))
        self._jar_library_by_sdk[sdk] = self.context.add_new_target(address, JarLibrary, jars=[jar])
      binary.inject_dependency(self._jar_library_by_sdk[sdk].address)

  def _render_args(self, binary, manifest, resource_dirs):
    """Compute the args that will be passed to the aapt tool.

    :param AndroidBinary binary: The target that depends on the processed resources.
    :param AndroidManifest manifest: Manifest of the target that owns the resources.
    :param list resource_dirs: List of resource_dirs to include in this invocation of the aapt tool.
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
    args = [self.aapt_tool(binary)]
    args.extend(['package', '-m', '-J', self.aapt_out(binary)])
    args.extend(['-M', manifest.path])
    args.append('--auto-add-overlay')
    for resource_dir in resource_dirs:
      args.extend(['-S', resource_dir])
    args.extend(['-I', self.android_jar(binary)])
    args.extend(['--ignore-assets', self.ignored_assets])
    logger.debug('Executing: {0}'.format(' '.join(args)))
    return args

  def execute(self):
    # The number of R.java files produced from each library is == |sdks in play for its dependees|.
    # The number of R.java files produced for each android_binary == |android_library deps| + 1
    binaries = self.context.targets(self.is_android_binary)
    self.create_sdk_jar_deps(binaries)
    for binary in binaries:
      # TODO(mateo) add invalidation framework. Adding it here doesn't work right now because the
      # framework can't differentiate between one library that has to be compiled by multiple sdks.

      gentargets = [binary]

      def gather_gentargets(tgt):
        """Gather all AndroidLibrary targets that have a manifest."""
        if isinstance(tgt, AndroidLibrary) and tgt.manifest:
          gentargets.append(tgt)
      binary.walk(gather_gentargets)
      for gen in gentargets:
        aapt_output = self._relative_genfile(gen)
        aapt_file = os.path.join(self.aapt_out(binary), aapt_output)

        resource_deps = self.context.build_graph.transitive_subgraph_of_addresses([gen.address])
        resource_dirs = [t.resource_dir for t in resource_deps if isinstance(t, AndroidResources)]
        if resource_dirs:
          if aapt_file not in self._created_library_targets:

            # Priority for resources is left->right, so dependency order matters (see TODO in aapt_builder).
            args = self._render_args(binary, gen.manifest, resource_dirs)
            with self.context.new_workunit(name='aaptgen', labels=[WorkUnitLabel.MULTITOOL]) as workunit:
              returncode = subprocess.call(args,
                                           stdout=workunit.output('stdout'),
                                           stderr=workunit.output('stderr'))
              if returncode:
                raise TaskError('The AaptGen process exited non-zero: {}'.format(returncode))
            new_target = self.create_target(binary, gen)
            self._created_library_targets[aapt_file] = new_target
          gen.inject_dependency(self._created_library_targets[aapt_file].address)

  def create_target(self, binary, gentarget):
    """Create a JavaLibrary target for the R.java files created by the aapt tool.

    :param AndroidBinary binary: AndroidBinary target whose target_sdk is used.
    :param AndroidTarget gentarget: AndroidBinary or Library that owns the processed resources.

    :returns new_target: Synthetic target for the R.java output of the aapt tool.
    :rtype::class:`pants.backend.jvm.targets.java_library.JavaLibrary`
    """
    spec_path = os.path.join(os.path.relpath(self.aapt_out(binary), get_buildroot()))
    address = Address(spec_path=spec_path, target_name=gentarget.id)
    new_target = self.context.add_new_target(address,
                                             JavaLibrary,
                                             derived_from=gentarget,
                                             sources=[self._relative_genfile(gentarget)],
                                             dependencies=[])
    return new_target

  def aapt_out(self, binary):
    """Location for the output of an aapt invocation.

    :param AndroidBinary binary: AndroidBinary target that depends upon the aapt output.
    :returns outdir: full path of output directory
    :rtype string
    """
    outdir = os.path.join(self.workdir, binary.target_sdk)
    safe_mkdir(outdir)
    return outdir
