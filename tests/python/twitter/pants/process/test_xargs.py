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

import errno
import os

import mox
import pytest

from twitter.pants.process.xargs import Xargs


class XargsTest(mox.MoxTestBase):
  def setUp(self):
    super(XargsTest, self).setUp()
    self.call = self.mox.CreateMockAnything()
    self.xargs = Xargs(self.call)

  def test_execute_nosplit_success(self):
    self.call(['one', 'two', 'three', 'four']).AndReturn(0)
    self.mox.ReplayAll()

    self.assertEqual(0, self.xargs.execute(['one', 'two', 'three', 'four']))

  def test_execute_nosplit_raise(self):
    exception = Exception()

    self.call(['one', 'two', 'three', 'four']).AndRaise(exception)
    self.mox.ReplayAll()

    with pytest.raises(Exception) as raised:
      self.xargs.execute(['one', 'two', 'three', 'four'])
    self.assertTrue(exception is raised.value)

  def test_execute_nosplit_fail(self):
    self.call(['one', 'two', 'three', 'four']).AndReturn(42)
    self.mox.ReplayAll()

    self.assertEqual(42, self.xargs.execute(['one', 'two', 'three', 'four']))

  TOO_BIG = OSError(errno.E2BIG, os.strerror(errno.E2BIG))

  def test_execute_split(self):
    self.call(['one', 'two', 'three', 'four']).AndRaise(self.TOO_BIG)
    self.call(['one', 'two']).AndReturn(0)
    self.call(['three', 'four']).AndReturn(0)
    self.mox.ReplayAll()

    self.assertEqual(0, self.xargs.execute(['one', 'two', 'three', 'four']))

  def test_execute_uneven(self):
    self.call(['one', 'two', 'three']).AndRaise(self.TOO_BIG)
    # TODO(John Sirois): We really don't care if the 1st call gets 1 argument or 2, we just
    # care that all arguments get passed just once via exactly 2 rounds of call - consider making
    # this test less brittle to changes in the chunking logic.
    self.call(['one']).AndReturn(0)
    self.call(['two', 'three']).AndReturn(0)
    self.mox.ReplayAll()

    self.assertEqual(0, self.xargs.execute(['one', 'two', 'three']))

  def test_execute_split_multirecurse(self):
    self.call(['one', 'two', 'three', 'four']).AndRaise(self.TOO_BIG)
    self.call(['one', 'two']).AndRaise(self.TOO_BIG)
    self.call(['one']).AndReturn(0)
    self.call(['two']).AndReturn(0)
    self.call(['three', 'four']).AndReturn(0)
    self.mox.ReplayAll()

    self.assertEqual(0, self.xargs.execute(['one', 'two', 'three', 'four']))

  def test_execute_split_fail_fast(self):
    self.call(['one', 'two', 'three', 'four']).AndRaise(self.TOO_BIG)
    self.call(['one', 'two']).AndReturn(42)
    self.mox.ReplayAll()

    self.assertEqual(42, self.xargs.execute(['one', 'two', 'three', 'four']))

  def test_execute_split_fail_slow(self):
    self.call(['one', 'two', 'three', 'four']).AndRaise(self.TOO_BIG)
    self.call(['one', 'two']).AndReturn(0)
    self.call(['three', 'four']).AndReturn(42)
    self.mox.ReplayAll()

    self.assertEqual(42, self.xargs.execute(['one', 'two', 'three', 'four']))
