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

from twitter.pants.commands.ide import Ide

class IdeTest(unittest.TestCase):

  def testInterpolation(self):
    testFileContents = '''
base.dir=${root.dir}/base
sub.dir.1=${base.dir}/a
sub.dir.2=${base.dir}/b

checkstyle.suppression.files=\
${sub.dir.1}/checkstyle_suppressions.xml,\
${sub.dir.2}/checkstyle_suppressions.xml
    '''
    result = Ide._find_checkstyle_suppressions(testFileContents, '/root')
    self.assertEquals(['/root/base/a/checkstyle_suppressions.xml',
                       '/root/base/b/checkstyle_suppressions.xml' ], result)
