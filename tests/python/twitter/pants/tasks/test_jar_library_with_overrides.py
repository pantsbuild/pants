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

from twitter.pants.base import ParseContext
from twitter.pants.targets.exclude import Exclude
from twitter.pants.targets.jar_library import JarLibrary
from twitter.pants.targets.jar_dependency import JarDependency
from twitter.pants.targets.pants_target import Pants


class JarLibraryWithOverrides(unittest.TestCase):

  def test_jar_dependency(self):
    with ParseContext.temp():
      org, name = "org", "name"
      # thing to override
      nay = JarDependency(org, name, "0.0.1")
      yea = JarDependency(org, name, "0.0.8")
      # define targets depend on different 'org:c's
      JarLibrary("c", [nay])
      JarLibrary("b", [yea])
      # then depend on those targets transitively, and override to the correct version
      l = JarLibrary(
        "a",
        dependencies=[Pants(":c")],
        overrides=[":b"])

      # confirm that resolving includes the correct version
      resolved = set(l.resolve())
      self.assertTrue(yea in resolved)
      # and attaches an exclude directly to the JarDependency
      self.assertTrue(Exclude(org, name) in nay.excludes)
