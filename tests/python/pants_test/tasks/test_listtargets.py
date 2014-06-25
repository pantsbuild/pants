# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
from textwrap import dedent

from pants.backend.core.targets.dependencies import Dependencies
from pants.backend.core.tasks.listtargets import ListTargets
from pants.backend.jvm.targets.artifact import Artifact
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.targets.repository import Repository
from pants_test.tasks.test_base import ConsoleTaskTest


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
  @property
  def alias_groups(self):
    return {
      'target_aliases': {
        'dependencies': Dependencies,
        'java_library': JavaLibrary,
        'repo': Repository,
      },
      'exposed_objects': {
        'pants': lambda x: x,
        'artifact': Artifact,
      },
    }

  def setUp(self):
    super(ListTargetsTest, self).setUp()

    # Setup a BUILD tree for various list tests

    repo_target = dedent('''
        repo(
          name='public',
          url='http://maven.twttr.com',
          push_db='/tmp/publish.properties'
        )
        ''').strip()
    self.add_to_build_file('repos', repo_target)

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
      libs = libs or [Lib(os.path.basename(os.path.dirname(self.build_path(path))))]
      for lib in libs:
        target = "java_library(name='%s', provides=%s, sources=[])\n" % (lib.name, lib.provides)
        self.add_to_build_file(path, target)

    create_library('a')
    create_library('a/b', Lib('b', provides=True))
    create_library('a/b/c', Lib('c'), Lib('c2', provides=True), Lib('c3'))
    create_library('a/b/d')
    create_library('a/b/e', Lib('e1'))
    self.add_to_build_file('f', dedent('''
        dependencies(
          name='alias',
          dependencies=[
            pants('a/b/c:c3'),
            pants('a/b/d:d')
          ]
        ).with_description("""
        Exercises alias resolution.
        Further description.
        """)
        '''))

  def test_list_path(self):
    self.assert_console_output('a/b:b', targets=[self.target('a/b')])

  def test_list_siblings(self):
    self.assert_console_output('a/b:b', targets=self.targets('a/b:'))
    self.assert_console_output('a/b/c:c', 'a/b/c:c2', 'a/b/c:c3',
                               targets=self.targets('a/b/c/:'))

  def test_list_descendants(self):
    self.assert_console_output('a/b/c:c', 'a/b/c:c2', 'a/b/c:c3',
                               targets=self.targets('a/b/c/::'))

    self.assert_console_output(
        'a/b:b',
        'a/b/c:c',
        'a/b/c:c2',
        'a/b/c:c3',
        'a/b/d:d',
        'a/b/e:e1',
        targets=self.targets('a/b::'))

  def test_list_all(self):
    self.assert_entries('\n',
        'repos:public',
        'a:a',
        'a/b:b',
        'a/b/c:c',
        'a/b/c:c2',
        'a/b/c:c3',
        'a/b/d:d',
        'a/b/e:e1',
        'f:alias')

    self.assert_entries(', ',
        'repos:public',
        'a:a',
        'a/b:b',
        'a/b/c:c',
        'a/b/c:c2',
        'a/b/c:c3',
        'a/b/d:d',
        'a/b/e:e1',
        'f:alias',
        args=['--test-sep=, '])

    self.assert_console_output(
        'repos:public',
        'a:a',
        'a/b:b',
        'a/b/c:c',
        'a/b/c:c2',
        'a/b/c:c3',
        'a/b/d:d',
        'a/b/e:e1',
        'f:alias')

  def test_list_provides(self):
    self.assert_console_output(
        'a/b:b com.twitter#b',
        'a/b/c:c2 com.twitter#c2',
        args=['--test-provides'])

  def test_list_provides_customcols(self):
    self.assert_console_output(
        '/tmp/publish.properties a/b:b http://maven.twttr.com public com.twitter#b',
        '/tmp/publish.properties a/b/c:c2 http://maven.twttr.com public com.twitter#c2',
        args=[
            '--test-provides',
            '--test-provides-columns=repo_db,address,repo_url,repo_name,artifact_id'
        ])

  def test_list_dedups(self):
    targets = []
    targets.extend(self.targets('a/b/d/::'))
    targets.extend(self.target('f:alias').dependencies)
    self.assertEquals(3, len(targets), "Expected a duplicate of a/b/d:d")
    self.assert_console_output(
      'a/b/c:c3',
      'a/b/d:d',
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
      f:alias
        Exercises alias resolution.
        Further description.
      ''').strip(),
      args=['--test-documented']
    )
