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

import unittest

from twitter.birds.duck.ttypes import Duck
from twitter.birds.goose.ttypes import Goose

class ThritNamespacePackagesTest(unittest.TestCase):
  def test_thrift_namespaces(self):
    """The 'test' here is the very fact that we can successfully import the generated thrift code
    with a shared package prefix (twitter.birds) from two different eggs.
    However there's no harm in also exercising the thrift objects, just to be sure we can."""
    myDuck = Duck()
    myDuck.quack = 'QUACKQUACKQUACK'
    myGoose = Goose()
    myGoose.laysGoldenEggs = True
