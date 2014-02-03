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

from textwrap import dedent

from twitter.pants.tasks.check_published_deps import CheckPublishedDeps

from . import ConsoleTaskTest


class CheckPublishedDepsTest(ConsoleTaskTest):

  @classmethod
  def task_type(cls):
    return CheckPublishedDeps

  @classmethod
  def setUpClass(cls):
    super(CheckPublishedDepsTest, cls).setUpClass()

    cls.create_file('repo/pushdb/publish.properties', dedent('''
        revision.major.org.name%lib1=2
        revision.minor.org.name%lib1=0
        revision.patch.org.name%lib1=0
        revision.sha.org.name%lib1=12345
        revision.major.org.name%lib2=2
        revision.minor.org.name%lib2=0
        revision.patch.org.name%lib2=0
        revision.sha.org.name%lib2=12345
        '''))
    cls.create_target('repo/BUILD', dedent('''
        import os
        repo(name='repo',
             url='http://www.www.com',
             push_db=os.path.join(os.path.dirname(__file__), 'pushdb', 'publish.properties'))
        '''))

    cls.create_target('provider/BUILD', dedent('''
        java_library(name='lib1',
          provides=artifact(
            org='org.name',
            name='lib1',
            repo=pants('repo')),
          sources=[])
        java_library(name='lib2',
          provides=artifact(
            org='org.name',
            name='lib2',
            repo=pants('repo')),
          sources=[])
        '''))
    cls.create_target('outdated/BUILD', dedent('''
        jar_library(name='outdated',
          dependencies=[jar(org='org.name', name='lib1', rev='1.0.0')]
        )
        '''))
    cls.create_target('uptodate/BUILD', dedent('''
        jar_library(name='uptodate',
          dependencies=[jar(org='org.name', name='lib2', rev='2.0.0')]
        )
        '''))
    cls.create_target('both/BUILD', dedent('''
        dependencies(name='both',
          dependencies=[
            pants('outdated'),
            pants('uptodate'),
          ]
        )
        '''))

  def test_all_up_to_date(self):
    self.assert_console_output(
      targets=[self.target('uptodate')]
    )

  def test_print_up_to_date_and_outdated(self):
    self.assert_console_output(
      'outdated org.name#lib1 1.0.0 latest 2.0.0',
      'up-to-date org.name#lib2 2.0.0',
      targets=[self.target('both')],
      args=['--test-print-uptodate']
    )

  def test_outdated(self):
    self.assert_console_output(
      'outdated org.name#lib1 1.0.0 latest 2.0.0',
      targets=[self.target('outdated')]
    )
