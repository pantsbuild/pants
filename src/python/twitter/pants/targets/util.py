# ==================================================================================================
# Copyright 2013 Foursquare Labs, Inc.
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

__author__ = 'Ryan Williams'

from twitter.pants.targets.pants_target import Pants

def resolve(arg, clazz=Pants):
  """Wraps strings in Pants() targets, for BUILD file convenience.

    - single string literal gets wrapped in Pants() target
    - single object is left alone
    - list of strings and other miscellaneous objects gets its strings wrapped in Pants() targets
  """

  if isinstance(arg, basestring):
    # Strings get wrapped in a given class (default Pants).
    return clazz(arg)

  # NOTE(ryan): if arg is a non-iterable object, just return it. Ideally we'd check isinstance(arg, Target) here, but
  # some things that Targets depend on are not themselves subclasses of Target, notably JarDependencies.
  try:
    [ e for e in arg ]
  except TypeError:
    return arg

  # If arg is in fact iterable, recurse on its elements.
  return [resolve(dependency, clazz=clazz) for dependency in arg]
