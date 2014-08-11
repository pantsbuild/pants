# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os

from pants.backend.jvm.tasks.jvm_compile.analysis_tools import AnalysisTools
from pants.backend.jvm.tasks.jvm_compile.jvm_compile import JvmCompile
from pants.backend.jvm.tasks.jvm_compile.scala.zinc_analysis import ZincAnalysis
from pants.backend.jvm.tasks.jvm_compile.scala.zinc_analysis_parser import ZincAnalysisParser
from pants.backend.jvm.tasks.jvm_compile.scala.zinc_utils import ZincUtils


# Overridden by parameter scala-compile -> args
_SCALA_COMPILE_ARGS_DEFAULT = [
  '-S-encoding', '-SUTF-8','-S-g:vars',
]

# Overridden by parameter scala-compile -> warning_args
_SCALA_COMPILE_WARNING_ARGS_DEFAULT = [
  '-S-deprecation', '-S-unchecked',
]

# Overridden by parameter scala-compile -> no_warning_args
_SCALA_COMPILE_NO_WARNING_ARGS_DEFAULT = [
  '-S-nowarn',
]

class ScalaCompile(JvmCompile):
  _language = 'scala'
  _file_suffix = '.scala'
  _config_section = 'scala-compile'

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    super(ScalaCompile, cls).setup_parser(option_group, args, mkflag)

    option_group.add_option(mkflag('plugins'), dest='plugins', default=None,
                            action='append',
                            help='Use these scalac plugins. Default is set in pants.ini.')

  def __init__(self, *args, **kwargs):
    super(ScalaCompile, self).__init__(*args, **kwargs)

    # Set up the zinc utils.
    color = not self.context.options.no_color
    self._zinc_utils = ZincUtils(context=self.context,
                                 nailgun_task=self,
                                 jvm_options=self._jvm_options,
                                 color=color)

    self.configure_args(args_defaults=_SCALA_COMPILE_ARGS_DEFAULT,
                        warning_defaults=_SCALA_COMPILE_WARNING_ARGS_DEFAULT,
                        no_warning_defaults=_SCALA_COMPILE_WARNING_ARGS_DEFAULT)

  @property
  def config_section(self):
    return self._config_section

  def create_analysis_tools(self):
    return AnalysisTools(self.context, ZincAnalysisParser(self._classes_dir), ZincAnalysis)

  def extra_compile_time_classpath_elements(self):
    # Classpath entries necessary for our compiler plugins.
    return self._zinc_utils.plugin_jars()

  # Invalidate caches if the toolchain changes.
  def platform_version_info(self):
    zinc_invalidation_key = self._zinc_utils.platform_version_info()
    jvm_target_version = ''

    # Check scalac args for jvm target version.
    for arg in self._args:
      if arg.strip().startswith("-S-target:"):
        jvm_target_version = arg.strip()

    zinc_invalidation_key.append(jvm_target_version)
    return zinc_invalidation_key

  def extra_products(self, target):
    ret = []
    if target.is_scalac_plugin and target.classname:
      root, plugin_info_file = ZincUtils.write_plugin_info(self._resources_dir, target)
      ret.append((root, [plugin_info_file]))
    return ret

  def compile(self, args, classpath, sources, classes_output_dir, analysis_file):
    # We have to treat our output dir as an upstream element, so zinc can find valid
    # analysis for previous partitions. We use the global valid analysis for the upstream.
    upstream = ({classes_output_dir: self._analysis_file}
                if os.path.exists(self._analysis_file) else {})
    return self._zinc_utils.compile(args, classpath + [self._classes_dir], sources,
                                    classes_output_dir, analysis_file, upstream)
