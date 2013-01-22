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
    - single Pants() target is left alone
    - list of strings and Pants() targets gets its strings wrapped, returning a list of Pants() targets
  """

  if arg is None:
    return None

  if isinstance(arg, str):
    return clazz(arg)

  if isinstance(arg, clazz):
    return arg

  return [clazz(dependency) if isinstance(dependency, str) else dependency for dependency in arg]
