# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.tasks.nailgun_task import NailgunTaskBase
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.java.jar.jar_dependency import JarDependency
from pants.task.simple_codegen_task import SimpleCodegenTask
from twitter.common.collections import OrderedSet

from pants.contrib.thrifty.java_thrifty_library import JavaThriftyLibrary


class JavaThriftyGen(NailgunTaskBase, SimpleCodegenTask):

  gentarget_type = JavaThriftyLibrary

  sources_globs = ('**/*',)

  @classmethod
  def register_options(cls, register):
    super().register_options(register)

    def thrifty_jar(name):
      return JarDependency(org='com.microsoft.thrifty', name=name, rev='0.4.3')

    cls.register_jvm_tool(register,
                          'thrifty-runtime',
                          classpath=[thrifty_jar(name='thrifty-runtime')])
    cls.register_jvm_tool(register,
                          'thrifty-compiler',
                          classpath=[thrifty_jar(name='thrifty-compiler')])

  def synthetic_target_type(self, target):
    return JavaLibrary

  def synthetic_target_extra_dependencies(self, target, target_workdir):
    deps = OrderedSet(self.resolve_deps([self.get_options().thrifty_runtime]))
    deps.update(target.dependencies)
    return deps

  def synthetic_target_extra_exports(self, target, target_workdir):
    return self.resolve_deps([self.get_options().thrifty_runtime])

  def format_args_for_target(self, target, target_workdir):
    sources = OrderedSet(target.sources_relative_to_buildroot())
    args = ['--out={0}'.format(target_workdir)]
    for include_path in self._compute_include_paths(target):
      args.append('--path={0}'.format(include_path))
    args.extend(sources)
    return args

  def execute_codegen(self, target, target_workdir):
    args = self.format_args_for_target(target, target_workdir)
    if args:
      result = self.runjava(classpath=self.tool_classpath('thrifty-compiler'),
                            main='com.microsoft.thrifty.compiler.ThriftyCompiler',
                            args=args,
                            workunit_name='compile',
                            workunit_labels=[WorkUnitLabel.TOOL])
      if result != 0:
        raise TaskError('Thrifty compiler exited non-zero ({0})'.format(result))

  def _compute_include_paths(self, target):
    """Computes the set of paths that thrifty uses to lookup imports.

    The IDL files under these paths are not compiled, but they are required to compile
    downstream IDL files.

    :param target: the JavaThriftyLibrary target to compile.
    :return: an ordered set of directories to pass along to thrifty.
    """
    paths = OrderedSet()
    paths.add(os.path.join(get_buildroot(), target.target_base))

    def collect_paths(dep):
      if not dep.has_sources('.thrift'):
        return
      paths.add(os.path.join(get_buildroot(), dep.target_base))

    collect_paths(target)
    target.walk(collect_paths)
    return paths
