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
  _CONFIG_SECTION = 'dx-tool'

  # @classmethod
  # def setup_parser(cls, option_group, args, mkflag):
  #   # VM options go here dx -J<options>
  #   pass

  @classmethod
  def is_dextarget(cls, target):
    """Return true if target has class files to be compiled into dex"""
    return isinstance(target, AndroidBinary)

  @classmethod
  def product_types(cls):
    return ['dex']

  def __init__(self, context, workdir):
    super(DxCompile, self).__init__(context, workdir)
    self._android_dist = self.android_sdk
    config_section = self.config_section
    self.setup_artifact_cache_from_config(config_section=config_section)

  def prepare(self, round_manager):
    round_manager.require_data('classes_by_target')

  @property
  def config_section(self):
    return self._CONFIG_SECTION


  def _compile_dex(self, args, build_tools_version):
    classpath = [self.dx_jar_tool(build_tools_version)]
    java_main = 'com.android.dx.command.Main'
    return self.runjava(classpath=classpath, main=java_main, args=args, workunit_name='dx')


  def execute(self):
    #safe_mkdir(self.workdir)
    with self.context.new_workunit(name='dx-compile', labels=[WorkUnit.MULTITOOL]):
      for target in self.context.targets(predicate=self.is_dextarget):
        out_dir = os.path.join(self.workdir, target.id)
        safe_mkdir(out_dir)
        classes_by_target = self.context.products.get_data('classes_by_target')
        dex_classes = []

        def add_to_dex(tgt):
          target_classes = classes_by_target.get(tgt)
          if target_classes:

            def add_classes(target_products):
              for root, products in target_products.abs_paths():
                for prod in products:
                  dex_classes.append(prod)

            add_classes(target_classes)
        target.walk(add_to_dex)

        #args = self.render_args(args)
        args = []
        dex_file = 'classes.dex'
        jar_path = os.path.join(out_dir, dex_file)
        args.extend(['--dex', '--no-strict', '--output=' + jar_path])
        args.extend(dex_classes)
        self._compile_dex(args, target.build_tools_version)
        self.context.products.get('dex').add(target, out_dir).append(dex_file)


    #TODO check for empty class files there is no valid empty dex file.

  def dx_jar_tool(self, build_tools_version):
    """Return the appropriate dx.jar.

    :param string build_tools_version: The Android build-tools version number (e.g. '19.1.0').
    """
    dx_jar = os.path.join('build-tools', build_tools_version, 'lib', 'dx.jar')
    return self._android_dist.register_android_tool(dx_jar)

