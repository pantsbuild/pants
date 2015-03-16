# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.tasks.jvm_compile.analysis_tools import AnalysisTools
from pants.backend.jvm.tasks.jvm_compile.jvm_compile import JvmCompile
from pants.backend.jvm.tasks.jvm_compile.scala.zinc_analysis import ZincAnalysis
from pants.backend.jvm.tasks.jvm_compile.scala.zinc_analysis_parser import ZincAnalysisParser
from pants.backend.jvm.tasks.jvm_compile.scala.zinc_utils import ZincUtils


class ScalaCompile(JvmCompile):
  _language = 'scala'
  _file_suffix = '.scala'

  @classmethod
  def get_args_default(cls, bootstrap_option_values):
    return ('-S-encoding', '-SUTF-8','-S-g:vars')

  @classmethod
  def get_warning_args_default(cls):
    return ('-S-deprecation', '-S-unchecked')

  @classmethod
  def get_no_warning_args_default(cls):
    return ('-S-nowarn',)

  @classmethod
  def register_options(cls, register):
    super(ScalaCompile, cls).register_options(register)
    # Note: Used in ZincUtils.
    # TODO: Revisit this. It's unintuitive for ZincUtils to reach back into the task for options.
    register('--plugins', action='append', help='Use these scalac plugins.')
    register('--name-hashing', action='store_true', default=False, help='Use zinc name hashing.')
    ZincUtils.register_options(register, cls.register_jvm_tool)

  def __init__(self, *args, **kwargs):
    super(ScalaCompile, self).__init__(*args, **kwargs)

    # Set up the zinc utils.
    color = self.get_options().colors
    self._zinc_utils = ZincUtils(context=self.context,
                                 nailgun_task=self,
                                 jvm_options=self._jvm_options,
                                 color=color,
                                 log_level=self.get_options().level)

  def create_analysis_tools(self):
    return AnalysisTools(self.context.java_home, ZincAnalysisParser(), ZincAnalysis)

  def extra_compile_time_classpath_elements(self):
    # Classpath entries necessary for our compiler plugins.
    return self._zinc_utils.plugin_jars()

  # Invalidate caches if the toolchain changes.
  def platform_version_info(self):
    zinc_invalidation_key = self._zinc_utils.platform_version_info()

    # Check scalac args for jvm target version.
    jvm_target_version = ''
    for arg in self._args:
      if arg.strip().startswith("-S-target:"):
        jvm_target_version = arg.strip()
    zinc_invalidation_key.append(jvm_target_version)

    # Invalidate if use of name hashing changes.
    zinc_invalidation_key.append(
      'name-hashing-{0}'.format('on' if self.get_options().name_hashing else 'off'))

    return zinc_invalidation_key

  def extra_products(self, target):
    ret = []
    if target.is_scalac_plugin and target.classname:
      root, plugin_info_file = ZincUtils.write_plugin_info(self._resources_dir, target)
      ret.append((root, [plugin_info_file]))
    return ret

  def compile(self, args, classpath, sources, classes_output_dir, upstream_analysis, analysis_file):
    return self._zinc_utils.compile(args, classpath, sources,
                                    classes_output_dir, analysis_file, upstream_analysis)
