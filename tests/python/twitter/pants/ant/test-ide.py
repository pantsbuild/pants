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
               is_apt = False,
               is_codegen = False,
               internal_dependencies = None,
               jar_dependencies = None,
               rev = None):
    self.name = name
    self.is_apt = is_apt
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
    jar5 = MockTarget('jar5', rev = 1)
    jar6 = MockTarget('jar6', rev = 1)

    f = MockTarget('f', is_codegen = True)
    b = MockTarget('b', is_codegen = True, internal_dependencies = [f])
    d = MockTarget('d', internal_dependencies = [f], jar_dependencies = [jar1])

    g = MockTarget('g', is_apt = True)
    i = MockTarget('i', internal_dependencies = [g])
    h = MockTarget('h', is_apt = True, internal_dependencies = [i], jar_dependencies = [jar5])
    j = MockTarget('j', jar_dependencies = [jar1, jar6])

    e = MockTarget('e', internal_dependencies = [g, h], jar_dependencies = [jar2])


    c = MockTarget('c',
                   is_codegen = True,
                   internal_dependencies = [d, e],
                   jar_dependencies = [jar3])

    a = MockTarget('a', internal_dependencies = [c, b, e, j], jar_dependencies = [jar4])

    # We want to compile only:
    #   codegen <- ide classpath needs these
    #   apt + any internal deps <- ide compiler needs these
    #
    # a -> *c -> d --> *f
    #              --> jar1
    #         -> e
    #         -> jar3
    #   -> *b -> (*f)
    #   --> e -> #g
    #         -> #h -> i -> (#g)
    #               -> jar5
    #         -> jar2
    #   --> j -> jar1
    #         -> jar6
    #   --> jar4

    internal_deps, jar_deps = _extract_target(a, lambda target: True, lambda target: target.is_apt)

    self.assertEquals(OrderedSet([c, b]), internal_deps,
                      'Expected depth first walk to roll up e to 1st visited dependee (c)')

    self.assertEquals(OrderedSet([d, e]), c.internal_dependencies)
    self.assertEquals(OrderedSet([f]), d.internal_dependencies)
    self.assertEquals(OrderedSet([g, h]), e.internal_dependencies)
    self.assertEquals(OrderedSet([i]), h.internal_dependencies)
    self.assertEquals(OrderedSet(), b.internal_dependencies,
                      'Expected depth first walk to roll up f to 1st visited dependee (d)')

    self.assertEquals(set([jar1, jar4, jar6]), set(jar_deps),
                      'Only jar dependencies from rolled up targets should be collected since '
                      'those not rolled up will include their jar deps in their own ivy.xmls')
