# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from itertools import izip_longest
import os
import re
import subprocess
import unittest

import pytest

from pants.scm import Scm
from pants.scm.git import Git
from pants.util.contextutil import environment_as, pushd, temporary_dir
from pants.util.dirutil import safe_mkdtemp, safe_open, safe_rmtree, touch


class Version(object):
  def __init__(self, text):
    self._components = map(int, text.split('.'))

  def __cmp__(self, other):
    for ours, theirs in izip_longest(self._components, other._components, fillvalue=0):
      difference = cmp(ours, theirs)
      if difference != 0:
        return difference
    return 0


class VersionTest(unittest.TestCase):
  def test_equal(self):
    self.assertEqual(Version('1'), Version('1.0.0.0'))
    self.assertEqual(Version('1.0'), Version('1.0.0.0'))
    self.assertEqual(Version('1.0.0'), Version('1.0.0.0'))
    self.assertEqual(Version('1.0.0.0'), Version('1.0.0.0'))

  def test_less(self):
    self.assertTrue(Version('1.6') < Version('2'))
    self.assertTrue(Version('1.6') < Version('1.6.1'))
    self.assertTrue(Version('1.6') < Version('1.10'))

  def test_greater(self):
    self.assertTrue(Version('1.6.22') > Version('1'))
    self.assertTrue(Version('1.6.22') > Version('1.6'))
    self.assertTrue(Version('1.6.22') > Version('1.6.2'))
    self.assertTrue(Version('1.6.22') > Version('1.6.21'))
    self.assertTrue(Version('1.6.22') > Version('1.6.21.3'))


def git_version():
  '''Get a Version() based on installed command-line git's version'''
  process = subprocess.Popen(['git', '--version'], stdout=subprocess.PIPE)
  (stdout, stderr) = process.communicate()
  assert process.returncode == 0, "Failed to determine git version."
  # stdout is like 'git version 1.9.1.598.g9119e8b\n'  We want '1.9.1.598'
  matches = re.search(r'\s(\d+(?:\.\d+)*)[\s\.]', stdout)
  return Version(matches.group(1))


@pytest.mark.skipif("git_version() < Version('1.7.10')")
class GitTest(unittest.TestCase):
  @staticmethod
  def init_repo(remote_name, remote):
    subprocess.check_call(['git', 'init'])
    subprocess.check_call(['git', 'config', 'user.email', 'you@example.com'])
    subprocess.check_call(['git', 'config', 'user.name', 'Your Name'])
    subprocess.check_call(['git', 'remote', 'add', remote_name, remote])

  @classmethod
  def setUpClass(cls):
    cls.origin = safe_mkdtemp()
    with pushd(cls.origin):
      subprocess.check_call(['git', 'init', '--bare'])

    cls.gitdir = safe_mkdtemp()
    cls.worktree = safe_mkdtemp()

    cls.readme_file = os.path.join(cls.worktree, 'README')

    with environment_as(GIT_DIR=cls.gitdir, GIT_WORK_TREE=cls.worktree):
      cls.init_repo('depot', cls.origin)

      touch(cls.readme_file)
      subprocess.check_call(['git', 'add', 'README'])
      subprocess.check_call(['git', 'commit', '-am', 'initial commit with decode -> \x81b'])
      subprocess.check_call(['git', 'tag', 'first'])
      subprocess.check_call(['git', 'push', '--tags', 'depot', 'master'])
      subprocess.check_call(['git', 'branch', '--set-upstream', 'master', 'depot/master'])

      with safe_open(cls.readme_file, 'w') as readme:
        readme.write('Hello World.')
      subprocess.check_call(['git', 'commit', '-am', 'Update README.'])

    cls.clone2 = safe_mkdtemp()
    with pushd(cls.clone2):
      cls.init_repo('origin', cls.origin)
      subprocess.check_call(['git', 'pull', '--tags', 'origin', 'master:master'])

      with safe_open(os.path.realpath('README'), 'a') as readme:
        readme.write('--')
      subprocess.check_call(['git', 'commit', '-am', 'Update README 2.'])
      subprocess.check_call(['git', 'push', '--tags', 'origin', 'master'])

    cls.git = Git(gitdir=cls.gitdir, worktree=cls.worktree)

  @classmethod
  def tearDownClass(cls):
    safe_rmtree(cls.origin)
    safe_rmtree(cls.gitdir)
    safe_rmtree(cls.worktree)
    safe_rmtree(cls.clone2)

  def test(self):
    self.assertEqual(set(), self.git.changed_files())
    self.assertEqual(set(['README']), self.git.changed_files(from_commit='HEAD^'))

    tip_sha = self.git.commit_id
    self.assertTrue(tip_sha)

    self.assertTrue(tip_sha in self.git.changelog())

    self.assertTrue(self.git.tag_name.startswith('first-'), msg='un-annotated tags should be found')
    self.assertEqual('master', self.git.branch_name)

    def edit_readme():
      with open(self.readme_file, 'a') as readme:
        readme.write('More data.')

    edit_readme()
    with open(os.path.join(self.worktree, 'INSTALL'), 'w') as untracked:
      untracked.write('make install')
    self.assertEqual(set(['README']), self.git.changed_files())
    self.assertEqual(set(['README', 'INSTALL']), self.git.changed_files(include_untracked=True))

    try:
      # These changes should be rejected because our branch point from origin is 1 commit behind
      # the changes pushed there in clone 2.
      self.git.commit('API Changes.')
    except Scm.RemoteException:
      with environment_as(GIT_DIR=self.gitdir, GIT_WORK_TREE=self.worktree):
        subprocess.check_call(['git', 'reset', '--hard', 'depot/master'])
      self.git.refresh()
      edit_readme()

    self.git.commit('''API '"' " Changes.''')
    self.git.tag('second', message='''Tagged ' " Changes''')

    with temporary_dir() as clone:
      with pushd(clone):
        self.init_repo('origin', self.origin)
        subprocess.check_call(['git', 'pull', '--tags', 'origin', 'master:master'])

        with open(os.path.realpath('README')) as readme:
          self.assertEqual('--More data.', readme.read())

        git = Git()

        # Check that we can pick up committed and uncommitted changes.
        with safe_open(os.path.realpath('CHANGES'), 'w') as changes:
          changes.write('none')
        subprocess.check_call(['git', 'add', 'CHANGES'])
        self.assertEqual(set(['README', 'CHANGES']), git.changed_files(from_commit='first'))

        self.assertEqual('master', git.branch_name)
        self.assertEqual('second', git.tag_name, msg='annotated tags should be found')
