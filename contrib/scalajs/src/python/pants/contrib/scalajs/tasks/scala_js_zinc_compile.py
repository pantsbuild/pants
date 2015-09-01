# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.tasks.jvm_compile.scala.zinc_compile import BaseZincCompile

from pants.contrib.scalajs.targets.scala_js_library import ScalaJSLibrary


class ScalaJSZincCompile(BaseZincCompile):
  _language = 'scala-js'
  _file_suffix = '.scala'

  @classmethod
  def register_options(cls, register):
    super(ScalaJSZincCompile, cls).register_options(register)
    cls.register_jvm_tool(register, 'scala-js-compiler')

  def plugin_jars(self):
    return self.tool_classpath('scala-js-compiler')

  def plugin_args(self):
    # filter the tool classpath to select only the compiler jar
    return ['-S-Xplugin:{}'.format(jar) for jar in self.plugin_jars() if 'scalajs-compiler_' in jar]

  def select(self, target):
    return isinstance(target, ScalaJSLibrary)

  def select_source(self, source_file_path):
    return source_file_path.endswith('.scala')
