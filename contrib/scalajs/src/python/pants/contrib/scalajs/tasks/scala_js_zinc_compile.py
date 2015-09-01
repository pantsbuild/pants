# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.jvm.tasks.jvm_compile.scala.zinc_compile import BaseZincCompile

from pants.contrib.scalajs.targets.scala_js_binary import ScalaJSBinary
from pants.contrib.scalajs.subsystems.scala_js_platform import ScalaJSPlatform


class ScalaJSZincCompile(BaseZincCompile):
  _name = 'scala-js'
  _file_suffix = '.scala'

  @classmethod
  def register_options(cls, register):
    super(ScalaJSZincCompile, cls).register_options(register)
    cls.register_jvm_tool(register, 'scala-js-compiler')

  def __init__(self, *args, **kwargs):
    super(ScalaJSZincCompile, self).__init__(*args, **kwargs)

    # A directory independent of any other classpath which can contain per-target
    # plugin resource files.
    self._plugin_info_dir = os.path.join(self.workdir, 'scalac-plugin-info')

    # The set of target addresses that should be selected by this member.
    self._selected_target_addresses = None

  def plugin_jars(self):
    return self.tool_classpath('scala-js-compiler')

  def plugin_args(self):
    # filter the tool classpath to select only the compiler jar
    return ['-S-Xplugin:{}'.format(jar) for jar in self.plugin_jars() if 'scalajs-compiler_' in jar]

  def select(self, target):
    """Transitively selects scala targets that are depended on by ScalaJSBinary targets.

    TODO: This method implements a stateful, hacky workaround. The ability to select transitively
    should probably be baked into GroupTask.
    """
    if self._selected_target_addresses:
      return target.address in self._selected_target_addresses

    self._selected_target_addresses = set()
    for target in self.context.targets():
      if not isinstance(target, ScalaJSBinary):
        continue
      # Select ScalaJSBinary and its transitive scala dependencies.
      for dep in target.closure():
        if dep.has_sources('.scala'):
          self._selected_target_addresses.add(dep.address)

  def select_source(self, source_file_path):
    return source_file_path.endswith('.scala')
