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

__author__ = 'John Sirios'

from twitter.common.collections import OrderedSet
from twitter.pants.ant.ide import _extract_target

import unittest

class MockTarget(object):
  def __init__(self,
               name,
               is_codegen = False,
               internal_dependencies = None,
               jar_dependencies = None,
               rev = None):
    self.name = name
    self.is_codegen = is_codegen
    self.internal_dependencies = OrderedSet(internal_dependencies)
    self.jar_dependencies = OrderedSet(jar_dependencies)
    self.excludes = []
    self.rev = rev

  def __repr__(self):
    return self.name


class IdeTest(unittest.TestCase):
  def test_extract_target(self):
    jar1 = MockTarget('jar1', rev = 1)
    jar2 = MockTarget('jar2', rev = 1)
    jar3 = MockTarget('jar3', rev = 1)
    jar4 = MockTarget('jar4', rev = 1)

    f = MockTarget('f', is_codegen = True)
    b = MockTarget('b', is_codegen = True, internal_dependencies = [f])
    d = MockTarget('d', internal_dependencies = [f], jar_dependencies = [jar1])
    e = MockTarget('e', jar_dependencies = [jar2])

    # This codegen target has a jar dependency, but it should not be rolled up since the codegen
    # target itself is grafted into the dep tree
    c = MockTarget('c',
                   is_codegen = True,
                   internal_dependencies = [d, e],
                   jar_dependencies = [jar3])

    a = MockTarget('a', internal_dependencies = [c, b, e], jar_dependencies = [jar4])

    internal_deps, jar_deps = _extract_target(a, lambda target: True)

    self.assertEquals(OrderedSet([c, b]), internal_deps)
    self.assertEquals(OrderedSet([f]), c.internal_dependencies,
                      'Expected depth first walk to roll up f to 1st visited dependee')
    self.assertEquals(OrderedSet(), b.internal_dependencies,
                      'Expected depth first walk to roll up f to 1st visited dependee')

    self.assertEquals(set([jar1, jar2, jar4]), set(jar_deps))
