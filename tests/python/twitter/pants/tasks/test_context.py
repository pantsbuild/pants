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

__author__ = 'jsirois'

import unittest

from twitter.pants.base import Config
from twitter.pants.goal import Context
from twitter.pants.testutils import MockTarget

class ContextTest(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
    cls.config = Config.load()

  @classmethod
  def create_context(cls, **kwargs):
    return Context(cls.config, run_tracker=None, **kwargs)

  def test_dependents_empty(self):
    context = self.create_context(options={}, target_roots=[])
    dependees = context.dependents()
    self.assertEquals(0, len(dependees))

  def test_dependents_direct(self):
    a = MockTarget('a')
    b = MockTarget('b', [a])
    c = MockTarget('c', [b])
    d = MockTarget('d', [c, a])
    e = MockTarget('e', [d])
    context = self.create_context(options={}, target_roots=[a, b, c, d, e])
    dependees = context.dependents(lambda t: t in set([e, c]))
    self.assertEquals(set([c]), dependees.pop(d))
    self.assertEquals(0, len(dependees))
