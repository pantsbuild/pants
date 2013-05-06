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

import mox

from twitter.common.contextutil import temporary_file

from twitter.pants.base.hash_utils import hash_all, hash_file


class TestHashUtils(mox.MoxTestBase):

  def setUp(self):
    super(TestHashUtils, self).setUp()
    self.digest = self.mox.CreateMockAnything()

  def test_hash_all(self):
    self.digest.update('jake')
    self.digest.update('jones')
    self.digest.hexdigest().AndReturn('42')
    self.mox.ReplayAll()

    self.assertEqual('42', hash_all(['jake', 'jones'], digest=self.digest))

  def test_hash_file(self):
    self.digest.update('jake jones')
    self.digest.hexdigest().AndReturn('1137')
    self.mox.ReplayAll()

    with temporary_file() as fd:
      fd.write('jake jones')
      fd.close()

      self.assertEqual('1137', hash_file(fd.name, digest=self.digest))

