# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.jvm.tasks.jvm_compile.analysis_tools import AnalysisTools
from pants.backend.jvm.tasks.jvm_compile.jvm_compile import JvmCompile
from pants.backend.jvm.tasks.jvm_compile.scala.zinc_analysis import ZincAnalysis
from pants.backend.jvm.tasks.jvm_compile.scala.zinc_analysis_parser import ZincAnalysisParser
from pants.backend.jvm.tasks.jvm_compile.scala.zinc_utils import ZincUtils
from pants.option.options import Options


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
    register('--plugin-args', advanced=True, type=Options.dict, default={},
             help='Map from plugin name to list of arguments for that plugin.')
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

    # A directory independent of any other classpath which can contain per-target
    # plugin resource files.
    self._plugin_info_dir = os.path.join(self.workdir, 'scalac-plugin-info')

  def create_analysis_tools(self):
    return AnalysisTools(self.context.java_home, ZincAnalysisParser(), ZincAnalysis)

  def extra_compile_time_classpath_elements(self):
    # Classpath entries necessary for our compiler plugins.
    return self._zinc_utils.plugin_jars()

  # Invalidate caches if the toolchain changes.
  def platform_version_info(self):
    zinc_invalidation_key = self._zinc_utils.platform_version_info()

    # Invalidate if any compiler args change.
    # Note that while some args are obviously important for invalidation (e.g., the jvm target
    # version), some might not be. However we must invalidated on all the args, because Zinc
    # ignores analysis files if the compiler args they were created with are different from the
    # current ones, and does a full recompile. So if we allow cached artifacts with those analysis
    # files to be used, Zinc will do unnecessary full recompiles on subsequent edits.
    zinc_invalidation_key.extend(self._args)

    # Invalidate if use of name hashing changes.
    zinc_invalidation_key.append(
      'name-hashing-{0}'.format('on' if self.get_options().name_hashing else 'off'))

    return zinc_invalidation_key

  def extra_products(self, target):
    """Override extra_products to produce a plugin information file."""
    ret = []
    if target.is_scalac_plugin and target.classname:
      # NB: We don't yet support explicit in-line compilation of scala compiler plugins from
      # the workspace to be used in subsequent compile rounds like we do for annotation processors
      # with javac. This would require another GroupTask similar to AptCompile, but for scala.
      root, plugin_info_file = ZincUtils.write_plugin_info(self._plugin_info_dir, target)
      ret.append((root, [plugin_info_file]))
    return ret

  def compile(self, args, classpath, sources, classes_output_dir, upstream_analysis, analysis_file):
    return self._zinc_utils.compile(args, classpath, sources,
                                    classes_output_dir, analysis_file, upstream_analysis)
