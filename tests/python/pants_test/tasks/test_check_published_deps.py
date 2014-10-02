# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
from textwrap import dedent

from pants.backend.core.targets.dependencies import Dependencies
from pants.backend.jvm.artifact import Artifact
from pants.backend.jvm.repository import Repository
from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.tasks.check_published_deps import CheckPublishedDeps
from pants.base.build_file_aliases import BuildFileAliases
from pants_test.tasks.test_base import ConsoleTaskTest


class CheckPublishedDepsTest(ConsoleTaskTest):
  @property
  def alias_groups(self):
    return BuildFileAliases.create(
      targets={
        'target': Dependencies,
        'jar_library': JarLibrary,
        'java_library': JavaLibrary,
      },
      objects={
        'artifact': Artifact,
        'jar': JarDependency,
        'repo': Repository(name='repo',
                           url='http://www.www.com',
                           push_db_basedir=os.path.join(self.build_root, 'repo')),
      }
    )

  @classmethod
  def task_type(cls):
    return CheckPublishedDeps

  def setUp(self):
    super(CheckPublishedDepsTest, self).setUp()

    self.create_file('repo/org.name/lib1/publish.properties', dedent('''
        revision.major.org.name%lib1=2
        revision.minor.org.name%lib1=0
        revision.patch.org.name%lib1=0
        revision.sha.org.name%lib1=12345
        '''))
    self.create_file('repo/org.name/lib2/publish.properties', dedent('''
        revision.major.org.name%lib2=2
        revision.minor.org.name%lib2=0
        revision.patch.org.name%lib2=0
        revision.sha.org.name%lib2=12345
        '''))

    self.add_to_build_file('provider/BUILD', dedent('''
        java_library(name='lib1',
          provides=artifact(
            org='org.name',
            name='lib1',
            repo=repo),
          sources=[])
        java_library(name='lib2',
          provides=artifact(
            org='org.name',
            name='lib2',
            repo=repo),
          sources=[])
        '''))
    self.add_to_build_file('outdated/BUILD', dedent('''
        jar_library(name='outdated',
          jars=[jar(org='org.name', name='lib1', rev='1.0.0')]
        )
        '''))
    self.add_to_build_file('uptodate/BUILD', dedent('''
        jar_library(name='uptodate',
          jars=[jar(org='org.name', name='lib2', rev='2.0.0')]
        )
        '''))
    self.add_to_build_file('both/BUILD', dedent('''
        target(name='both',
          dependencies=[
            'outdated',
            'uptodate',
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
