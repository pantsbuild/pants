# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.android.targets.android_binary import AndroidBinary
from pants.backend.android.tasks.android_task import AndroidTask
from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnit
from pants.util.dirutil import safe_mkdir


class DxCompile(AndroidTask, NailgunTask):
  """
  Compile java classes into dex files, Dalvik executables.
  """

  # Name of output file. "Output name must end with one of: .dex .jar .zip .apk or be a directory."
  DEX_NAME = 'classes.dex'

  @staticmethod
  def is_dextarget(target):
    """Return True if target has class files to be compiled into dex."""
    return isinstance(target, AndroidBinary)

  @classmethod
  def register_options(cls, register):
    super(DxCompile, cls).register_options(register)
    register('--build-tools-version',
             help='Create the dex file using this version of the Android build tools.')
    register('--jvm-options', action='append', metavar='<option>...',
             help='Run dx with these JVM options.')

  @classmethod
  def product_types(cls):
    return ['dex']

  @classmethod
  def prepare(cls, options, round_manager):
    super(DxCompile, cls).prepare(options, round_manager)
    round_manager.require_data('classes_by_target')
    round_manager.require_data('unpacked_archives')

  def __init__(self, *args, **kwargs):
    super(DxCompile, self).__init__(*args, **kwargs)
    self._forced_build_tools_version = self.get_options().build_tools_version
    self._forced_jvm_options = self.get_options().jvm_options

    self.setup_artifact_cache()

  def _render_args(self, outdir, classes):
    dex_file = os.path.join(outdir, self.DEX_NAME)
    args = []
    # Glossary of dx.jar flags.
    #   : '--dex' to create a Dalvik executable.
    #   : '--no-strict' allows the dx.jar to skip verifying the package path. This allows us to
    #            pass a list of classes as opposed to a top-level dir.
    #   : '--output' tells the dx.jar where to put and what to name the created file.
    #            See comment on self.classes_dex for restrictions.
    args.extend(['--dex', '--no-strict', '--output={0}'.format(dex_file)])

    # classes is a list of class files to be included in the created dex file.
    args.extend(classes)
    return args

  def _compile_dex(self, args, build_tools_version):
    if self._forced_build_tools_version:
      classpath = [self.dx_jar_tool(self._forced_build_tools_version)]
    else:
      classpath = [self.dx_jar_tool(build_tools_version)]

    jvm_options = self._forced_jvm_options if self._forced_jvm_options else None
    java_main = 'com.android.dx.command.Main'
    return self.runjava(classpath=classpath, jvm_options=jvm_options, main=java_main,
                        args=args, workunit_name='dx')

  def execute(self):
    with self.context.new_workunit(name='dx-compile', labels=[WorkUnit.MULTITOOL]):
      targets = self.context.targets(self.is_dextarget)

      with self.invalidated(targets) as invalidation_check:
        invalid_targets = []
        for vt in invalidation_check.invalid_vts:
          invalid_targets.extend(vt.targets)
        for target in invalid_targets:

          outdir = self.dx_out(target)
          safe_mkdir(outdir)
          classes_by_target = self.context.products.get_data('classes_by_target')
          unpacked_archives = self.context.products.get_data('unpacked_archives')
          classes = []

          def gather_classes(tgt):
            def add_classes(target_products):
              for _, products in target_products.abs_paths():
                for prod in products:
                  classes.append(prod)

            target_classes = classes_by_target.get(tgt)

            if target_classes:
              add_classes(target_classes)

            if unpacked_archives:
              unpacked = unpacked_archives.get(tgt)
              if unpacked:
                # The unpacked_archives are passed as a list of [found_files, rel_unpack_dir].
                # For Android's purposes, just passing the containing dir is fine.
                classes.append(unpacked[1])

          target.walk(gather_classes)
          if not classes:
            raise TaskError("No classes were found for {0!r}.".format(target))
          args = self._render_args(outdir, classes)
          # TODO (mateor) wrap this in a workunit and properly handle stdout/err.
          self._compile_dex(args, target.build_tools_version)
      for target in targets:
        self.context.products.get('dex').add(target, self.dx_out(target)).append(self.DEX_NAME)

  def dx_jar_tool(self, build_tools_version):
    """Return the appropriate dx.jar.

    :param string build_tools_version: The Android build-tools version number (e.g. '19.1.0').
    """
    dx_jar = os.path.join('build-tools', build_tools_version, 'lib', 'dx.jar')
    return self.android_sdk.register_android_tool(dx_jar)

  def dx_out(self, target):
    """Return the outdir for the DxCompile task."""
    return os.path.join(self.workdir, target.id)
