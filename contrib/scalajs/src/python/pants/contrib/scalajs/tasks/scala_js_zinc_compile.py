# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.jvm.tasks.jvm_compile.zinc.zinc_compile import BaseZincCompile
from pants.util.memo import memoized_method

from pants.contrib.scalajs.targets.scala_js_target import ScalaJSTarget


class ScalaJSZincCompile(BaseZincCompile):
  """Compile scala source code to an scala.js representation, ready to be linked."""

  _name = 'scala-js'
  _file_suffix = '.scala'
  compiler_name = 'zinc'

  scalac_plugins = ['scalajs']

  @classmethod
  def register_options(cls, register):
    super().register_options(register)
    # TODO: revisit after https://rbcommons.com/s/twitter/r/3225/
    cls.register_jvm_tool(register, 'scala-js-compiler')

  @classmethod
  def product_types(cls):
    return ['scala_js_ir']

  @memoized_method
  def scalac_plugin_classpath_elements(self):
    return self.tool_classpath('scala-js-compiler')

  def select(self, target):
    if not isinstance(target, ScalaJSTarget):
      return False
    return target.has_sources(self._file_suffix)

  def select_source(self, source_file_path):
    return source_file_path.endswith(self._file_suffix)
