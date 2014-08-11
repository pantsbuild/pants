# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)


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

  # name of output file. "Output name must end with one of: .dex .jar .zip .apk or be a directory."
  DEX_NAME = 'classes.dex'
  _CONFIG_SECTION = 'dx-tool'

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    super(DxCompile, cls).setup_parser(option_group, args, mkflag)

    option_group.add_option(mkflag("build-tools-version"), dest="build_tools_version",
                            help="[%default] Specifies the Android build-tools version used "
                                 "to create the dex file.")

    option_group.add_option(mkflag("VM-options"), dest="vm_options",
                            help="[%default] Pass VM-specific options to the virtual machine "
                                 "that runs dx (e.g. Xmx1024m).")

  @classmethod
  def is_dextarget(cls, target):
    """Return true if target has class files to be compiled into dex"""
    return isinstance(target, AndroidBinary)

  @classmethod
  def product_types(cls):
    return ['dex']

  def __init__(self, *args, **kwargs):
    super(DxCompile, self).__init__(*args, **kwargs)
    self._android_dist = self.android_sdk
    self._forced_build_tools_version = self.context.options.build_tools_version
    self._forced_vm_options = self.context.options.vm_options

    config_section = self.config_section
    self.setup_artifact_cache_from_config(config_section=config_section)

  def prepare(self, round_manager):
    round_manager.require_data('classes_by_target')

  @property
  def config_section(self):
    return self._CONFIG_SECTION

  def _render_args(self, out, classes):
    dex_file = os.path.join(out, self.DEX_NAME)
    args = []
    # Glossary of dx.jar flags.
    #   : '--dex' to create a Dalvik executable.
    #   : '--no-strict' allows the dx.jar to skip verifying the package path. This allows us to
    #            pass a list of classes as opposed to a top-level dir.
    #   : '--output' tells the dx.jar where to put and what to name the created file.
    #            See comment on self.classes_dex for restrictions.
    args.extend(['--dex', '--no-strict', '--output=' + dex_file])

    # classes is a list of class files to be included in the created dex file.
    args.extend(classes)
    return args

  def _compile_dex(self, args, build_tools_version):
    if self._forced_build_tools_version:
      classpath = [self.dx_jar_tool(self._forced_build_tools_version)]
    else:
      classpath = [self.dx_jar_tool(build_tools_version)]

    jvm_options = self._forced_vm_options if self._forced_vm_options else None
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
          out_dir = self.dx_out(target)
          safe_mkdir(out_dir)
          classes_by_target = self.context.products.get_data('classes_by_target')
          classes = []

          def add_to_dex(tgt):
            target_classes = classes_by_target.get(tgt)
            if target_classes:

              def add_classes(target_products):
                for root, products in target_products.abs_paths():
                  for prod in products:
                    classes.append(prod)

              add_classes(target_classes)

          target.walk(add_to_dex)
          if not classes:
            raise TaskError("No classes were found for {0!r}.".format(target))
          args = self._render_args(out_dir, classes)
          self._compile_dex(args, target.build_tools_version)
      for target in targets:
        self.context.products.get('dex').add(target, self.dx_out(target)).append(self.DEX_NAME)

  def dx_jar_tool(self, build_tools_version):
    """Return the appropriate dx.jar.

    :param string build_tools_version: The Android build-tools version number (e.g. '19.1.0').
    """
    dx_jar = os.path.join('build-tools', build_tools_version, 'lib', 'dx.jar')
    return self._android_dist.register_android_tool(dx_jar)

  def dx_out(self, target):
    return os.path.join(self.workdir, target.id)