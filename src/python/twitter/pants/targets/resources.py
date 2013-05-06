# ==================================================================================================
# Copyright 2012 Twitter, Inc.
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

import os

from collections import Sequence

from twitter.pants import is_concrete
from twitter.pants.base import ParseContext, Target
from twitter.pants.targets.with_sources import TargetWithSources


class Resources(TargetWithSources):
  """Describes a set of resource files to be embedded in a library or binary."""


class WithLegacyResources(TargetWithSources):
  """Collects resources whether they are specified using globs against an assumed parallel
  'resources' directory or they are Resources targets
  """
  def __init__(self, name, sources=None, resources=None):
    TargetWithSources.__init__(self, name, sources=sources)

    if resources is not None:
      def is_resources(item):
        return (isinstance(item, Target)
                and all(map(lambda tgt: isinstance(tgt, Resources),
                            filter(lambda tgt: is_concrete(tgt), item.resolve()))))

      if is_resources(resources):
        self.resources = list(self.resolve_all(resources, Resources))
      elif isinstance(resources, Sequence) and all(map(is_resources, resources)):
        self.resources = list(self.resolve_all(resources, Resources))
      else:
        # Handle parallel resource dir globs.
        # For example, for a java_library target base of src/main/java:
        #   src/main/java/com/twitter/base/BUILD
        # We get:
        #   sibling_resources_base = src/main/resources
        #   base_relpath = com/twitter/base
        #   resources_dir = src/main/resources/com/twitter/base
        #
        # TODO(John Sirois): migrate projects to Resources and remove support for old style assumed
        # parallel resources dirs
        sibling_resources_base = os.path.join(os.path.dirname(self.target_base), 'resources')
        base_relpath = os.path.relpath(self.address.buildfile.relpath, self.target_base)
        resources_dir = os.path.join(sibling_resources_base, base_relpath)
        with ParseContext.temp(basedir=resources_dir):
          self.resources = [Resources(name, resources)]
