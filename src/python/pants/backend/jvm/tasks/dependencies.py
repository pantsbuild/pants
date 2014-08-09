# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.backend.core.tasks.console_task import ConsoleTask
from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.base.exceptions import TaskError


# XXX(pl): JVM/Python hairball violator
class Dependencies(ConsoleTask):
  """Generates a textual list (using the target format) for the dependency set of a target."""

  @staticmethod
  def _is_jvm(target):
    return target.is_jvm or target.is_jvm_app

  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    super(Dependencies, cls).setup_parser(option_group, args, mkflag)

    cls.internal_only_flag = mkflag("internal-only")
    cls.external_only_flag = mkflag("external-only")

    option_group.add_option(cls.internal_only_flag,
                            action="store_true",
                            dest="dependencies_is_internal_only",
                            default=False,
                            help='Specifies that only internal dependencies should'
                                 ' be included in the graph output (no external jars).')
    option_group.add_option(cls.external_only_flag,
                            action="store_true",
                            dest="dependencies_is_external_only",
                            default=False,
                            help='Specifies that only external dependencies should'
                                 ' be included in the graph output (only external jars).')

  def __init__(self, *args, **kwargs):
    super(Dependencies, self).__init__(*args, **kwargs)

    if (self.context.options.dependencies_is_internal_only and
        self.context.options.dependencies_is_external_only):

      error_str = "At most one of %s or %s can be selected." % (self.internal_only_flag,
                                                                self.external_only_flag)
      raise TaskError(error_str)

    self.is_internal_only = self.context.options.dependencies_is_internal_only
    self.is_external_only = self.context.options.dependencies_is_external_only

  def console_output(self, unused_method_argument):
    for target in self.context.target_roots:
      if self._is_jvm(target):
        for line in self._jvm_dependencies_list(target):
          yield line

      elif target.is_python:
        if self.is_internal_only:
          raise TaskError('Unsupported option for Python target: is_internal_only: %s' %
                          self.is_internal_only)
        if self.is_external_only:
          raise TaskError('Unsupported option for Python target: is_external_only: %s' %
                          self.is_external_only)
        for line in self._python_dependencies_list(target):
          yield line

  def _dep_id(self, dep):
    if isinstance(dep, JarDependency):
      jar = dep
      if jar.rev:
        return False, '%s:%s:%s' % (jar.org, jar.name, jar.rev)
      else:
        return True, '%s:%s' % (jar.org, jar.name)
    else:
      return True, dep.address.spec

  def _python_dependencies_list(self, target):
    if isinstance(target, PythonRequirementLibrary):
      for req in target.payload.requirements:
        yield str(req._requirement)

    yield target.address.spec

    for dep in target.dependencies:
      for d in self._python_dependencies_list(dep):
        yield d

  def _jvm_dependencies_list(self, target):
    def print_deps(visited, dep):
      internal, address = self._dep_id(dep)

      if not dep in visited:
        if internal and (not self.is_external_only or self.is_internal_only):
          yield address

        visited.add(dep)

        if self._is_jvm(dep):
          for dep in dep.dependencies:
            for line in print_deps(visited, dep):
              yield line

        if not self.is_internal_only:
          if isinstance(dep, JarLibrary):
            for jar_dep in dep.jar_dependencies:
              internal, address  = self._dep_id(jar_dep)
              if not internal:
                if jar_dep not in visited:
                  if self.is_external_only or not self.is_internal_only:
                    yield address
                  visited.add(jar_dep)

    visited = set()
    for dep in print_deps(visited, target):
      yield dep
