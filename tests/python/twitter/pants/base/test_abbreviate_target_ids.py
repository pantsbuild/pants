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

import unittest

from twitter.pants.base.abbreviate_target_ids import abbreviate_target_ids

class AbbreviateTargetIdsTest(unittest.TestCase):
  def _test(self, expected, *actual):
    self.assertEqual(expected, abbreviate_target_ids(actual))

  def test_empty(self):
    self._test({})

  def test_single(self):
    self._test({'a': 'a'}, 'a')
    self._test({'a.b.c': 'c'}, 'a.b.c')

  def test_simple(self):
    self._test({'a': 'a',
                'b': 'b',
                'c': 'c'},
               'a', 'b', 'c')
    self._test({'x.a': 'a',
                'y.b': 'b',
                'z.c': 'c'},
               'x.a', 'y.b', 'z.c')

  def test_complex(self):
    self._test({'x.a': 'a',
                'x.b': 'b',
                'x.c': 'c'},
               'x.a', 'x.b', 'x.c')
    self._test({'x.a': 'x.a',
                'y.a': 'y.a',
                'z.b': 'b'},
               'x.a', 'y.a', 'z.b')
    self._test({'x.a': 'a',
                'x.y.a': 'y.a',
                'z.b': 'b'},
               'x.a', 'x.y.a', 'z.b')
