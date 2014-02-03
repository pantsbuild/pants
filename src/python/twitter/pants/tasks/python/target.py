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

from twitter.common.collections import OrderedSet

from twitter.pants.base import ParseContext, Target
from twitter.pants.base.target import TargetDefinitionException
from twitter.pants.targets import PythonRequirement


def is_python_root(target):
  return isinstance(target, PythonRoot)


class PythonRoot(Target):
  """
    Internal target for managing python chroot state.
  """
  @classmethod
  def synthetic_name(cls, targets):
    return list(targets)[0].name if len(targets) > 0 else 'empty'

  @classmethod
  def union(cls, targets, name=None):
    name = name or (cls.synthetic_name(targets) + '-union')
    with ParseContext.temp():
      return cls(name, dependencies=targets)

  @classmethod
  def of(cls, target):
    with ParseContext.temp():
      return cls(target.name, dependencies=[target])

  def __init__(self, name, dependencies=None):
    self.dependencies = OrderedSet(dependencies) if dependencies else OrderedSet()
    self.internal_dependencies = OrderedSet()
    self.interpreters = []
    self.distributions = {} # interpreter => distributions
    self.chroots = {}       # interpreter => chroots
    super(PythonRoot, self).__init__(name)

  def closure(self):
    os = OrderedSet()
    for target in self.dependencies | self.internal_dependencies:
      os.update(target.closure())
    return os

  def select(self, target_class):
    return OrderedSet(target for target in self.closure() if isinstance(target, target_class))

  @property
  def requirements(self):
    return self.select(PythonRequirement)
