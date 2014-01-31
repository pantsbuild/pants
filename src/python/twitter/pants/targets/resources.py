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

from twitter.common.dirutil.fileset import Fileset
from twitter.common.lang import Compatibility

from twitter.pants.base import ParseContext, Target

from .internal import InternalTarget
from .with_sources import TargetWithSources


class Resources(InternalTarget, TargetWithSources):
  """Describes a set of resource files to be embedded in a library or binary.

  If your target compiles to the JVM (e.g., ``java_library``,
  ``scala_library``, ``junit_tests``), you might have files
  that you need to access as resources. Each of these targets has an optional
  argument called ``resources`` that expects a list of target addresses that
  resolve to targets whose type is resource.

  In the ``jar`` goal, the resource files are placed in the resulting `.jar`.
  """

  def __init__(self, name, sources, exclusives=None):
    """
    :param string name: The name of this target, which combined with this
      build file defines the target :class:`twitter.pants.base.address.Address`.
    :param sources: A list of filenames representing the resources
      this library provides.
    """
    # TODO(John Sirois): XXX Review why this is an InternalTarget
    InternalTarget.__init__(self, name, dependencies=None, exclusives=exclusives)
    TargetWithSources.__init__(self, name, sources=sources)

  def has_sources(self, extension=None):
    """``Resources`` never own sources of any particular native type, like for example
    ``JavaLibrary``.
    """
    # TODO(John Sirois): track down the reason for this hack and kill or explain better.
    return extension is None


class WithLegacyResources(TargetWithSources):
  """Collects resources whether they are specified using globs against an assumed parallel
  'resources' directory or they are Resources targets.

  Resource handling is currently in transition, and two forms are available.

  New style:

  ::

    # `resources' is a first-class target type.
    resources(name='mybird',
      sources=['list', 'of', 'resources']
    )

    # Dependees depend on one or more `resources' targets.
    resources=[pants('src/resources/com/twitter/mybird')]

  Old style:

  ::

    # Resources can be a fileset.
    resources=globs('*.txt')

    # Resources can be a list of filenames.
    resources=['list', 'of', 'files']

  Please note mixing old/new styles is not supported.

  """

  def __init__(self, name, sources=None, resources=None, exclusives=None):
    """
    :param string name: The name of this target, which combined with this
      build file defines the target :class:`twitter.pants.base.address.Address`.
    :param sources: A list of filenames representing the source code
      this library is compiled from.
    :param resources: One or more :class:`twitter.pants.targets.resources.Resources`
      xor a list of filenames representing the resources this library provides.
    """
    TargetWithSources.__init__(self, name, sources=sources, exclusives=exclusives)

    if resources is not None:
      def is_resources(item):
        if not isinstance(item, Target):
          return False
        concrete_targets = [t for t in item.resolve() if t.is_concrete]
        return all(isinstance(t, Resources) for t in concrete_targets)

      resources_seq = resources if isinstance(resources, Sequence) else [resources]
      if all(map(is_resources, resources_seq)):
        self.resources = list(self.resolve_all(resources_seq, Resources))
      elif (all(map(lambda resource: isinstance(resource, (Fileset, Compatibility.string)),
                    resources_seq))):
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
      else:
        raise ValueError('Target %s resources are invalid: %s' % (self.address, resources))

      # Add the resources to dependencies.
      if isinstance(self, InternalTarget):
        self.update_dependencies(self.resources)
