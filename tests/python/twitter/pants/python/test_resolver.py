# ==================================================================================================
# Copyright 2012 Twitter, Inc.
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

from twitter.common.contextutil import temporary_file
from twitter.common.python.platforms import Platform

from twitter.pants.base.config import Config
from twitter.pants.python.resolver import get_platforms


class ResolverTest(unittest.TestCase):
  def setUp(self):
    with temporary_file() as ini:
      ini.write(
'''
[python-setup]
platforms: [
  'current',
  'linux-x86_64']
''')
      ini.close()
      self.config = Config.load(configpath=ini.name)

  def test_get_current_platform(self):
    expected_platforms = [Platform.current(), 'linux-x86_64']
    self.assertEqual(expected_platforms,
                     list(get_platforms(self.config.getlist('python-setup', 'platforms'))))

