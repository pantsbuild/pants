# ==================================================================================================
# Copyright 2011 Twitter, Inc.
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

from collections import deque
from twitter.common.collections import OrderedSet
from copy import copy

from twitter.pants.targets import JavaLibrary

import bang

def extract_target(java_targets, is_transitive, name = None):
  meta_target = bang.extract_target(java_targets, name)

  internal_deps, jar_deps = _extract_target(meta_target, is_transitive)

  # TODO(John Sirois): make an empty source set work in ant/compile.xml
  sources = [ '__no_source__' ]

  all_deps = OrderedSet()
  all_deps.update(internal_deps)
  all_deps.update(jar_deps)

  return JavaLibrary('ide',
                     sources,
                     provides = None,
                     dependencies = all_deps,
                     excludes = meta_target.excludes,
                     resources = None,
                     binary_resources = None,
                     deployjar = False,
                     buildflags = None,
                     is_meta = True)

def _extract_target(meta_target, is_transitive):
  class RootNode(object):
    def __init__(self):
      self.internal_dependencies = OrderedSet()

  root_target = RootNode()

  codegen_graph = deque([])
  codegen_graph.appendleft(root_target)
  jar_deps = OrderedSet()

  visited = set()
  def sift_targets(target):
    if target not in visited:
      visited.add(target)

      if target.is_codegen:
        codegen_graph[0].internal_dependencies.add(target)
      else:
        for jar_dependency in target.jar_dependencies:
          if jar_dependency.rev:
            if is_transitive(target):
              jar_deps.add(jar_dependency)
            else:
              jar_deps.add(copy(jar_dependency).intransitive())

      if target.is_codegen:
          codegen_graph.appendleft(target)

      for internal_target in list(target.internal_dependencies):
        target.internal_dependencies.discard(internal_target)
        sift_targets(internal_target)

      if target.is_codegen:
        codegen_graph.popleft()

  sift_targets(meta_target)

  assert len(codegen_graph) == 1 and codegen_graph[0] == root_target,\
    "Unexpected walk: %s" % codegen_graph

  return codegen_graph.popleft().internal_dependencies, jar_deps
