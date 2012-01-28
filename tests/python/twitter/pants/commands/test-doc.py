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

__author__ = 'Mark McBride'

from twitter.pants import get_buildroot
from twitter.pants.commands.doc import Doc
from twitter.common.contextutil import temporary_dir

import optparse
import os
import shutil
import unittest
import tempfile

class DocTargetTest(unittest.TestCase):
  def testLoads(self):
    build_root = get_buildroot()
    with temporary_dir() as target_path:
      target_base = os.path.join(target_path, "tests.python.twitter.pants.commands.pants_doc.pants_doc")
      collections_sub = os.path.join(target_base, "src.java.com.twitter.common.collections.collections")

      # run doc on our test target
      doc = Doc(build_root, optparse.OptionParser(), ["tests/python/twitter/pants/commands/pants_doc"], target_path = target_path)
      res = doc.execute()

      # make sure it works
      self.assertEqual(res, 0)

      # make sure it generates (some) expected files
      self.assertTrue(os.path.exists(target_base))
      self.assertTrue(os.path.exists(os.path.join(target_base, "index.html")))
      self.assertTrue(os.path.exists(collections_sub))
