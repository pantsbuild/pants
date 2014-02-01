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

from twitter.pants.base.context_utils import create_context
from twitter.pants.tasks.binary_create import BinaryCreate


sample_ini_test_1 = """
[DEFAULT]
pants_distdir = /tmp/dist
"""


class BinaryCreateTest(unittest.TestCase):

  def test_binary_create_init(self):
    options = {'jvm_binary_create_outdir': None,
               'binary_create_compressed': None,
               'binary_create_zip64': None,
               'jvm_binary_create_deployjar': None}
    binary_create = BinaryCreate(create_context(config=sample_ini_test_1, options=options))
    self.assertEquals(binary_create.outdir, '/tmp/dist')

