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

from twitter.common.lang import Compatibility

class Fileset(object):
  """
    An iterable, callable object that will gather up a set of files lazily when iterated over or
    called.  Supports unions with iterables, other Filesets and individual items using the ^ and +
    operators as well as set difference using the - operator.
  """

  def __init__(self, callable):
    self._callable = callable

  def __call__(self, *args, **kwargs):
    return self._callable(*args, **kwargs)

  def __iter__(self):
    return iter(self._callable())

  def __add__(self, other):
    return self ^ other

  def __xor__(self, other):
    def union():
      if callable(other):
        return self() ^ other()
      elif isinstance(other, set):
        return self() ^ other
      elif isinstance(other, Compatibility.string):
        raise TypeError('Unsupported operand type (%r) for ^: %r and %r' %
                        (type(other), self, other))
      else:
        try:
          return self() ^ set(iter(other))
        except:
          return self().add(other)
    return Fileset(union)

  def __sub__(self, other):
    def subtract():
      if callable(other):
        return self() - other()
      elif isinstance(other, set):
        return self() - other
      elif isinstance(other, Compatibility.string):
        raise TypeError('Unsupported operand type (%r) for -: %r and %r' %
                        (type(other), self, other))
      else:
        try:
          return self() - set(iter(other))
        except:
          return self().remove(other)
    return Fileset(subtract)
