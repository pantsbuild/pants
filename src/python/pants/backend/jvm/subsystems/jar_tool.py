# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.subsystems.jvm_tool_mixin import JvmToolMixin
from pants.base.workunit import WorkUnitLabel
from pants.java.jar.jar_dependency import JarDependency
from pants.subsystem.subsystem import Subsystem


class JarTool(JvmToolMixin, Subsystem):
  options_scope = 'jar-tool'

  @classmethod
  def register_options(cls, register):
    super(JarTool, cls).register_options(register)
    cls.register_jvm_tool(register,
                          'jar-tool',
                          classpath=[
                            JarDependency(org='org.pantsbuild', name='jar-tool', rev='0.0.10'),
                          ])

  def run(self, context, runjava, args):
    return runjava(self.tool_classpath_from_products(context.products, 'jar-tool',
                                                     scope=self.options_scope),
                   'org.pantsbuild.tools.jar.Main',
                   jvm_options=self.get_options().jvm_options,
                   args=args,
                   workunit_name='jar-tool',
                   workunit_labels=[WorkUnitLabel.TOOL, WorkUnitLabel.JVM,
                                    WorkUnitLabel.NAILGUN, WorkUnitLabel.SUPPRESS_LABEL])
