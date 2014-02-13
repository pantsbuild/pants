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

import os.path

from twitter.pants.base.build_environment import get_buildroot
from twitter.pants.base.target import Target
from twitter.pants.targets.sources import SourceRoot
from twitter.pants.tasks.targets_help import TargetsHelp

from . import ConsoleTaskTest


class TargetsHelpTest(ConsoleTaskTest):

  @classmethod
  def task_type(cls):
    return TargetsHelp

  @classmethod
  def setUpClass(cls):
    super(TargetsHelpTest, cls).setUpClass()
    SourceRoot.register(os.path.join(get_buildroot(), 'fakeroot'), TargetsHelpTest.MyTarget)

  def test_list_installed_targets(self):
    self.assert_console_output(
      TargetsHelp.INSTALLED_TARGETS_HEADER,
      '  %s: %s' % ('my_target'.rjust(TargetsHelp.MAX_ALIAS_LEN),
                    TargetsHelpTest.MyTarget.__doc__.split('\n')[0]))

  def test_get_details(self):
    self.assert_console_output(
      TargetsHelp.DETAILS_HEADER.substitute(
        name='my_target', desc=TargetsHelpTest.MyTarget.__doc__),
      '  name: The name of this target.',
      '   foo: Another argument.  (default: None)',
      args=['--test-details=my_target'])

  class MyTarget(Target):
    """One-line description of the target."""
    def __init__(self, name, foo=None):
      """
      :param name: The name of this target.
      :param string foo: Another argument.
      """
      Target.__init__(self, name)
