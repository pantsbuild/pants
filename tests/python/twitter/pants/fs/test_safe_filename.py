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

import os
import pytest
import unittest

from twitter.pants.fs.fs import safe_filename


class SafeFilenameTest(unittest.TestCase):
  class FixedDigest(object):
    def __init__(self, size):
      self._size = size

    def update(self, value):
      pass

    def hexdigest(self):
      return self._size * '*'

  def test_bad_name(self):
    with pytest.raises(ValueError):
      safe_filename(os.path.join('more', 'than', 'a', 'name.game'))

  def test_noop(self):
    self.assertEqual('jack.jill', safe_filename('jack', '.jill', max_length=9))
    self.assertEqual('jack.jill', safe_filename('jack', '.jill', max_length=100))

  def test_shorten(self):
    self.assertEqual('**.jill',
                     safe_filename('jack', '.jill', digest=self.FixedDigest(2), max_length=8))

  def test_shorten_fail(self):
    with pytest.raises(ValueError):
      safe_filename('jack', '.beanstalk', digest=self.FixedDigest(3), max_length=12)
