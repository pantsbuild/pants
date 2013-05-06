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

import os

from textwrap import dedent

from twitter.pants.base.target import Target
from twitter.pants.tasks.listtargets import ListTargets

from . import ConsoleTaskTest


class BaseListTargetsTest(ConsoleTaskTest):
  @classmethod
  def task_type(cls):
    return ListTargets


class ListTargetsTestEmpty(BaseListTargetsTest):
  def test_list_all_empty(self):
    self.assertEqual('', self.execute_task())
    self.assertEqual('', self.execute_task(args=['--test-sep=###']))
    self.assertEqual([], self.execute_console_task())


class ListTargetsTest(BaseListTargetsTest):
  @classmethod
  def setUpClass(cls):
    super(ListTargetsTest, cls).setUpClass()

    # Setup a BUILD tree for various list tests

    repo_target = dedent('''
        repo(
          name='public',
          url='http://maven.twttr.com',
          push_db='/tmp/publish.properties'
        )
        ''').strip()
    cls.create_target('repos', repo_target)

    class Lib(object):
      def __init__(self, name, provides=False):
        self.name = name
        self.provides = dedent('''
            artifact(
              org='com.twitter',
              name='%s',
              repo=pants('repos:public')
            )
            ''' % name).strip() if provides else 'None'

    def create_library(path, *libs):
      libs = libs or [Lib(os.path.basename(os.path.dirname(cls.build_path(path))))]
      for lib in libs:
        target = "java_library(name='%s', provides=%s, sources=[])\n" % (lib.name, lib.provides)
        cls.create_target(path, target)

    create_library('a')
    create_library('a/b', Lib('b', provides=True))
    create_library('a/b/c', Lib('c'), Lib('c2', provides=True), Lib('c3'))
    create_library('a/b/d')
    create_library('a/b/e', Lib('e1'))
    cls.create_target('f', dedent('''
        dependencies(
          name='alias',
          dependencies=[
            pants('a/b/c/BUILD:c3'),
            pants('a/b/d/BUILD:d')
          ]
        ).with_description("""
        Exercises alias resolution.
        Further description.
        """)
        '''))

  def test_list_path(self):
    self.assert_console_output('a/b/BUILD:b', targets=[self.target('a/b')])

  def test_list_siblings(self):
    self.assert_console_output('a/b/BUILD:b', targets=self.targets('a/b:'))
    self.assert_console_output('a/b/c/BUILD:c', 'a/b/c/BUILD:c2', 'a/b/c/BUILD:c3',
                               targets=self.targets('a/b/c/:'))

  def test_list_descendants(self):
    self.assert_console_output('a/b/c/BUILD:c', 'a/b/c/BUILD:c2', 'a/b/c/BUILD:c3',
                               targets=self.targets('a/b/c/::'))

    self.assert_console_output(
        'a/b/BUILD:b',
        'a/b/c/BUILD:c',
        'a/b/c/BUILD:c2',
        'a/b/c/BUILD:c3',
        'a/b/d/BUILD:d',
        'a/b/e/BUILD:e1',
        targets=self.targets('a/b::'))

  def test_list_all(self):
    self.assert_entries('\n',
        'repos/BUILD:public',
        'a/BUILD:a',
        'a/b/BUILD:b',
        'a/b/c/BUILD:c',
        'a/b/c/BUILD:c2',
        'a/b/c/BUILD:c3',
        'a/b/d/BUILD:d',
        'a/b/e/BUILD:e1',
        'f/BUILD:alias')

    self.assert_entries(', ',
        'repos/BUILD:public',
        'a/BUILD:a',
        'a/b/BUILD:b',
        'a/b/c/BUILD:c',
        'a/b/c/BUILD:c2',
        'a/b/c/BUILD:c3',
        'a/b/d/BUILD:d',
        'a/b/e/BUILD:e1',
        'f/BUILD:alias',
        args=['--test-sep=, '])

    self.assert_console_output(
        'repos/BUILD:public',
        'a/BUILD:a',
        'a/b/BUILD:b',
        'a/b/c/BUILD:c',
        'a/b/c/BUILD:c2',
        'a/b/c/BUILD:c3',
        'a/b/d/BUILD:d',
        'a/b/e/BUILD:e1',
        'f/BUILD:alias')

  def test_list_provides(self):
    self.assert_console_output(
        'a/b/BUILD:b com.twitter#b',
        'a/b/c/BUILD:c2 com.twitter#c2',
        args=['--test-provides'])

  def test_list_provides_customcols(self):
    self.assert_console_output(
        '/tmp/publish.properties a/b/BUILD:b http://maven.twttr.com public com.twitter#b',
        '/tmp/publish.properties a/b/c/BUILD:c2 http://maven.twttr.com public com.twitter#c2',
        args=[
            '--test-provides',
            '--test-provides-columns=repo_db,address,repo_url,repo_name,artifact_id'
        ])

  def test_list_dedups(self):
    def expand(spec):
      for target in self.targets(spec):
        for tgt in target.resolve():
          if isinstance(tgt, Target) and tgt.is_concrete:
            yield tgt

    targets = []
    targets.extend(expand('a/b/d/::'))
    targets.extend(expand('f::'))

    self.assertEquals(3, len(targets), "Expected a duplicate of a/b/d/BUILD:d")
    self.assert_console_output(
      'a/b/c/BUILD:c3',
      'a/b/d/BUILD:d',
      targets=targets
    )

  def test_list_documented(self):
    self.assert_console_output(
      # Confirm empty listing
      args=['--test-documented'],
      targets=[self.target('a/b')]
    )

    self.assert_console_output(
      dedent('''
      f/BUILD:alias
        Exercises alias resolution.
        Further description.
      ''').strip(),
      args=['--test-documented']
    )

