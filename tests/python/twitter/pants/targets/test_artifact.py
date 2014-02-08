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

from twitter.pants.base import ParseContext
from twitter.pants.targets.artifact import Artifact
from twitter.pants.targets.repository import Repository


class ArtifactTest(unittest.TestCase):

  def test_validation(self):
    with ParseContext.temp():
      repo = Repository(name="myRepo", url="myUrl", push_db="myPushDb")
      Artifact(org="testOrg", name="testName", repo=repo, description="Test")
      self.assertRaises(ValueError, Artifact,
                        org=1, name="testName", repo=repo, description="Test")
      self.assertRaises(ValueError, Artifact,
                        org="testOrg", name=1, repo=repo, description="Test")
      self.assertRaises(ValueError, Artifact,
                        org="testOrg", name="testName", repo=1, description="Test")
      self.assertRaises(ValueError, Artifact,
                        org="testOrg", name="testName", repo=repo, description=1)
