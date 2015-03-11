# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from contextlib import contextmanager
from itertools import izip_longest
import os
import re
import subprocess
import unittest2 as unittest

import pytest

from pants.scm.scm import Scm
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
  def setUp(self):
    self.origin = safe_mkdtemp()
    with pushd(self.origin):
      subprocess.check_call(['git', 'init', '--bare'])

    self.gitdir = safe_mkdtemp()
    self.worktree = safe_mkdtemp()

    self.readme_file = os.path.join(self.worktree, 'README')

    with environment_as(GIT_DIR=self.gitdir, GIT_WORK_TREE=self.worktree):
      self.init_repo('depot', self.origin)

      touch(self.readme_file)
      subprocess.check_call(['git', 'add', 'README'])
      subprocess.check_call(['git', 'commit', '-am', 'initial commit with decode -> \x81b'])
      subprocess.check_call(['git', 'tag', 'first'])
      subprocess.check_call(['git', 'push', '--tags', 'depot', 'master'])
      subprocess.check_call(['git', 'branch', '--set-upstream', 'master', 'depot/master'])

      with safe_open(self.readme_file, 'w') as readme:
        readme.write('Hello World.')
      subprocess.check_call(['git', 'commit', '-am', 'Update README.'])

    self.clone2 = safe_mkdtemp()
    with pushd(self.clone2):
      self.init_repo('origin', self.origin)
      subprocess.check_call(['git', 'pull', '--tags', 'origin', 'master:master'])

      with safe_open(os.path.realpath('README'), 'a') as readme:
        readme.write('--')
      subprocess.check_call(['git', 'commit', '-am', 'Update README 2.'])
      subprocess.check_call(['git', 'push', '--tags', 'origin', 'master'])

    self.git = Git(gitdir=self.gitdir, worktree=self.worktree)

  @staticmethod
  @contextmanager
  def mkremote(remote_name):
    with temporary_dir() as remote_uri:
      subprocess.check_call(['git', 'remote', 'add', remote_name, remote_uri])
      try:
        yield remote_uri
      finally:
        subprocess.check_call(['git', 'remote', 'remove', remote_name])

  @classmethod
  def tearDown(self):
    safe_rmtree(self.origin)
    safe_rmtree(self.gitdir)
    safe_rmtree(self.worktree)
    safe_rmtree(self.clone2)

  def test_integration(self):
    self.assertEqual(set(), self.git.changed_files())
    self.assertEqual(set(['README']), self.git.changed_files(from_commit='HEAD^'))

    tip_sha = self.git.commit_id
    self.assertTrue(tip_sha)

    self.assertTrue(tip_sha in self.git.changelog())

    merge_base = self.git.merge_base()
    self.assertTrue(merge_base)

    self.assertTrue(merge_base in self.git.changelog())

    with pytest.raises(Scm.LocalException):
      self.git.server_url

    with environment_as(GIT_DIR=self.gitdir, GIT_WORK_TREE=self.worktree):
      with self.mkremote('origin') as origin_uri:
        origin_url = self.git.server_url
        self.assertEqual(origin_url, origin_uri)

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

    # confirm that files outside of a given relative_to path are ignored
    self.assertEqual(set(), self.git.changed_files(relative_to='non-existent'))

    self.git.commit('API Changes.')
    try:
      # These changes should be rejected because our branch point from origin is 1 commit behind
      # the changes pushed there in clone 2.
      self.git.push()
    except Scm.RemoteException:
      with environment_as(GIT_DIR=self.gitdir, GIT_WORK_TREE=self.worktree):
        subprocess.check_call(['git', 'reset', '--hard', 'depot/master'])
      self.git.refresh()
      edit_readme()

    self.git.commit('''API '"' " Changes.''')
    self.git.push()
    # HEAD is merged into master
    self.assertEqual(self.git.commit_date(self.git.merge_base()), self.git.commit_date('HEAD'))
    self.assertEqual(self.git.commit_date('HEAD'), self.git.commit_date('HEAD'))
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

  def test_detect_worktree(self):
    with temporary_dir() as _clone:
      with pushd(_clone):
        clone = os.path.realpath(_clone)

        self.init_repo('origin', self.origin)
        subprocess.check_call(['git', 'pull', '--tags', 'origin', 'master:master'])

        def worktree_relative_to(cwd, expected):
          """Given a cwd relative to the worktree, tests that the worktree is detected as 'expected'."""
          orig_cwd = os.getcwd()
          try:
            abs_cwd = os.path.join(clone, cwd)
            if not os.path.isdir(abs_cwd):
              os.mkdir(abs_cwd)
            os.chdir(abs_cwd)
            actual = Git.detect_worktree()
            self.assertEqual(expected, actual)
          finally:
            os.chdir(orig_cwd)

        worktree_relative_to('..', None)
        worktree_relative_to('.', clone)
        worktree_relative_to('is', clone)
        worktree_relative_to('is/a', clone)
        worktree_relative_to('is/a/dir', clone)

  def test_refresh_with_conflict(self):
    with environment_as(GIT_DIR=self.gitdir, GIT_WORK_TREE=self.worktree):
      self.assertEqual(set(), self.git.changed_files())
      self.assertEqual(set(['README']), self.git.changed_files(from_commit='HEAD^'))

      # Create a change on this branch that is incompatible with the change to master
      with open(self.readme_file, 'w') as readme:
        readme.write('Conflict')

      subprocess.check_call(['git', 'commit', '-am', 'Conflict'])

      self.assertEquals(set([]), self.git.changed_files(include_untracked=True, from_commit='HEAD'))
      with self.assertRaises(Scm.LocalException):
        self.git.refresh(leave_clean=False)
      # The repo is dirty
      self.assertEquals(set(['README']), self.git.changed_files(include_untracked=True, from_commit='HEAD'))

      with environment_as(GIT_DIR=self.gitdir, GIT_WORK_TREE=self.worktree):
        subprocess.check_call(['git', 'reset', '--hard', 'HEAD'])

      # Now try with leave_clean
      with self.assertRaises(Scm.LocalException):
        self.git.refresh(leave_clean=True)
      # The repo is clean
      self.assertEquals(set([]), self.git.changed_files(include_untracked=True, from_commit='HEAD'))

  def test_commit_with_new_untracked_file_adds_file(self):
    new_file = os.path.join(self.worktree, 'untracked_file')

    touch(new_file)

    self.assertEqual({'untracked_file'}, self.git.changed_files(include_untracked=True))

    self.git.add(new_file)

    self.assertEqual({'untracked_file'}, self.git.changed_files())

    self.git.commit('API Changes.')

    self.assertEqual(set([]), self.git.changed_files(include_untracked=True))
