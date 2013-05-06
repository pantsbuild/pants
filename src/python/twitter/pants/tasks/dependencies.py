# ==================================================================================================
# Copyright 2013 Twitter, Inc.
# --------------------------------------------------------------------------------------------------
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this work except in compliance with the License.
# You may obtain a copy of the License in the LICENSE file, or at:
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==================================================================================================

from __future__ import print_function

from twitter.pants import is_concrete, is_jvm, is_jvm_app, is_python, PythonRequirement
from twitter.pants.targets.jar_dependency import JarDependency

from . import TaskError
from .console_task import ConsoleTask


class Dependencies(ConsoleTask):
  """Generates a textual list (using the target format) for the dependency set of a target."""

  @staticmethod
  def _is_jvm(target):
    return is_jvm(target) or is_jvm_app(target)

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

  def __init__(self, context, **kwargs):
    super(Dependencies, self).__init__(context, **kwargs)

    if (self.context.options.dependencies_is_internal_only and
        self.context.options.dependencies_is_external_only):

      error_str = "At most one of %s or %s can be selected." % (self.internal_only_flag,
                                                                self.external_only_flag)
      raise TaskError(error_str)

    self.is_internal_only = self.context.options.dependencies_is_internal_only
    self.is_external_only = self.context.options.dependencies_is_external_only

  def console_output(self, unused_method_argument):
    for target in self.context.target_roots:
      if all(self._is_jvm(t) for t in target.resolve() if is_concrete(t)):
        for line in self._dependencies_list(target):
          yield line

      elif is_python(target):
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
      if dep.rev:
        return False, '%s:%s:%s' % (dep.org, dep.name, dep.rev)
      else:
        return True, '%s:%s' % (dep.org, dep.name)
    else:
      return True, str(dep.address)

  def _python_dependencies_list(self, target):
    if isinstance(target, PythonRequirement):
      yield str(target._requirement)
    else:
      yield str(target.address)

    if hasattr(target, 'dependencies'):
      for dep in target.dependencies:
        for d in dep.resolve():
          for dep in self._python_dependencies_list(d):
            yield dep

  def _dependencies_list(self, target):
    def print_deps(visited, dep):
      internal, address = self._dep_id(dep)

      if not dep in visited:
        if internal and (not self.is_external_only or self.is_internal_only):
          yield address

        visited.add(dep)

        if self._is_jvm(dep):
          for internal_dependency in dep.internal_dependencies:
            for line in print_deps(visited, internal_dependency):
              yield line

        if not self.is_internal_only:
          if self._is_jvm(dep):
            for jar_dep in dep.jar_dependencies:
              internal, address  = self._dep_id(jar_dep)
              if not internal:
                if jar_dep not in visited:
                  if self.is_external_only or not self.is_internal_only:
                    yield address
                  visited.add(jar_dep)

    visited = set()
    for t in target.resolve():
      for dep in print_deps(visited, t):
        yield dep
