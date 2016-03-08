# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
import subprocess

from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.util.dirutil import safe_mkdir

from pants.contrib.android.targets.android_resources import AndroidResources
from pants.contrib.android.tasks.aapt_task import AaptTask


logger = logging.getLogger(__name__)


class AaptBuilder(AaptTask):
  """Build an android bundle with compiled code and assets.

  This class gathers compiled classes (an Android dex archive) and packages it with the
  target's resource files. The output is an unsigned .apk, an Android application package file.
  """

  @classmethod
  def product_types(cls):
    return ['apk']

  @classmethod
  def package_name(cls, binary):
    return '{0}.unsigned.apk'.format(binary.manifest.package_name)

  @classmethod
  def prepare(cls, options, round_manager):
    super(AaptBuilder, cls).prepare(options, round_manager)
    round_manager.require_data('dex')

  def _render_args(self, binary, resource_dirs, dex_files):
    # Glossary of used aapt flags.
    #   : 'package' is the main aapt operation (see class docstring for more info).
    #   : '-f' to 'force' overwrites if the package already exists.
    #   : '-M' is the AndroidManifest.xml of the project.
    #   : '--auto-add-overlay' automatically add resources that are only in overlays.
    #   : '-S' points to each dir in resource_dirs, aapt 'scans' them in order while
    #            collecting resources (resource priority is left -> right).
    #   : '-I' packages to add to base "include" set, here the android.jar of the target-sdk.
    #   : '--ignored-assets' patterns for the aapt to skip. This is the default w/ 'BUILD*' added.
    #   : '-F' The name and location of the .apk file to output.
    #   : additional positional arguments are treated as input directories to gather files from.
    args = []
    args.extend([self.aapt_tool(binary)])
    args.extend(['package', '-f'])
    args.extend(['-M', binary.manifest.path])
    args.append('--auto-add-overlay')
    for resource_dir in resource_dirs:
      args.extend(['-S', resource_dir])
    args.extend(['-I', self.android_jar(binary)])
    args.extend(['--ignore-assets', self.ignored_assets])
    args.extend(['-F', os.path.join(self.workdir, self.package_name(binary))])
    args.extend(dex_files)
    logger.debug('Executing: {0}'.format(' '.join(args)))
    return args

  def execute(self):
    safe_mkdir(self.workdir)
    binaries = self.context.targets(self.is_android_binary)
    with self.invalidated(binaries) as invalidation_check:
      invalid_targets = []
      for vt in invalidation_check.invalid_vts:
        invalid_targets.extend(vt.targets)
      for binary in invalid_targets:

        dex_files = []
        mapping = self.context.products.get('dex')
        for dex in mapping.get(binary):
          dex_files.append(dex)

        resource_deps = self.context.build_graph.transitive_subgraph_of_addresses([binary.address])
        resource_dirs = [t.resource_dir for t in resource_deps if isinstance(t, AndroidResources)]

        # Priority for resources is left to right so dependency order matters.
        # TODO(mateo): Make resources a first class AndroidBinary attribute to limit the order-dependent parts of the
        # BUILD files.
        args = self._render_args(binary, resource_dirs, dex_files)
        with self.context.new_workunit(name='apk-bundle',
                                       labels=[WorkUnitLabel.MULTITOOL]) as workunit:
          returncode = subprocess.call(args, stdout=workunit.output('stdout'),
                                       stderr=workunit.output('stderr'))
          if returncode:
            raise TaskError('Android aapt tool exited non-zero: {0}'.format(returncode))
    for binary in binaries:
      apk_name = self.package_name(binary)
      self.context.products.get('apk').add(binary, self.workdir).append(apk_name)
