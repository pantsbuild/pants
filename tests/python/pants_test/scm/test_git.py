# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import subprocess
import types
import unittest
from contextlib import contextmanager
from textwrap import dedent
from unittest import skipIf

from pants.scm.git import Git
from pants.scm.scm import Scm
from pants.util.contextutil import environment_as, pushd, temporary_dir
from pants.util.dirutil import chmod_plus_x, safe_mkdir, safe_mkdtemp, safe_open, safe_rmtree, touch
from pants_test.testutils.git_util import MIN_REQUIRED_GIT_VERSION, git_version


@skipIf(git_version() < MIN_REQUIRED_GIT_VERSION,
        'The GitTest requires git >= {}.'.format(MIN_REQUIRED_GIT_VERSION))
class GitTest(unittest.TestCase):

  @staticmethod
  def init_repo(remote_name, remote):
    # TODO (peiyu) clean this up, use `git_util.initialize_repo`.
    subprocess.check_call(['git', 'init'])
    subprocess.check_call(['git', 'config', 'user.email', 'you@example.com'])
    subprocess.check_call(['git', 'config', 'user.name', 'Your Name'])
    subprocess.check_call(['git', 'remote', 'add', remote_name, remote])

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
      safe_mkdir(os.path.join(self.worktree, 'dir'))
      with open(os.path.join(self.worktree, 'dir', 'f'), 'w') as f:
        f.write("file in subdir")

      # Make some symlinks
      os.symlink('f', os.path.join(self.worktree, 'dir', 'relative-symlink'))
      os.symlink('no-such-file', os.path.join(self.worktree, 'dir', 'relative-nonexistent'))
      os.symlink('dir/f', os.path.join(self.worktree, 'dir', 'not-absolute\u2764'))
      os.symlink('../README', os.path.join(self.worktree, 'dir', 'relative-dotdot'))
      os.symlink('dir', os.path.join(self.worktree, 'link-to-dir'))
      os.symlink('README/f', os.path.join(self.worktree, 'not-a-dir'))
      os.symlink('loop1', os.path.join(self.worktree, 'loop2'))
      os.symlink('loop2', os.path.join(self.worktree, 'loop1'))

      subprocess.check_call(['git', 'add', 'README', 'dir', 'loop1', 'loop2',
                             'link-to-dir', 'not-a-dir'])
      subprocess.check_call(['git', 'commit', '-am', 'initial commit with decode -> \x81b'])
      self.initial_rev = subprocess.check_output(['git', 'rev-parse', 'HEAD']).strip()
      subprocess.check_call(['git', 'tag', 'first'])
      subprocess.check_call(['git', 'push', '--tags', 'depot', 'master'])
      subprocess.check_call(['git', 'branch', '--set-upstream', 'master', 'depot/master'])

      with safe_open(self.readme_file, 'w') as readme:
        readme.write('Hello World.\u2764'.encode('utf-8'))
      subprocess.check_call(['git', 'commit', '-am', 'Update README.'])

      self.current_rev = subprocess.check_output(['git', 'rev-parse', 'HEAD']).strip()

    self.clone2 = safe_mkdtemp()
    with pushd(self.clone2):
      self.init_repo('origin', self.origin)
      subprocess.check_call(['git', 'pull', '--tags', 'origin', 'master:master'])

      with safe_open(os.path.realpath('README'), 'a') as readme:
        readme.write('--')
      subprocess.check_call(['git', 'commit', '-am', 'Update README 2.'])
      subprocess.check_call(['git', 'push', '--tags', 'origin', 'master'])

    self.git = Git(gitdir=self.gitdir, worktree=self.worktree)

  @contextmanager
  def mkremote(self, remote_name):
    with temporary_dir() as remote_uri:
      subprocess.check_call(['git', 'remote', 'add', remote_name, remote_uri])
      try:
        yield remote_uri
      finally:
        subprocess.check_call(['git', 'remote', 'remove', remote_name])

  def tearDown(self):
    safe_rmtree(self.origin)
    safe_rmtree(self.gitdir)
    safe_rmtree(self.worktree)
    safe_rmtree(self.clone2)

  def test_listdir(self):
    reader = self.git.repo_reader(self.initial_rev)

    for dirname in '.', './.':
      results = reader.listdir(dirname)
      self.assertEquals(['README',
                         'dir',
                         'link-to-dir',
                         'loop1',
                         'loop2',
                         'not-a-dir'],
                        sorted(results))

    for dirname in 'dir', './dir':
      results = reader.listdir(dirname)
      self.assertEquals(['f',
                         'not-absolute\u2764'.encode('utf-8'),
                         'relative-dotdot',
                         'relative-nonexistent',
                         'relative-symlink'],
                        sorted(results))

    results = reader.listdir('link-to-dir')
    self.assertEquals(['f',
                       'not-absolute\u2764'.encode('utf-8'),
                       'relative-dotdot',
                       'relative-nonexistent',
                       'relative-symlink'],
                      sorted(results))

    with self.assertRaises(reader.MissingFileException):
      with reader.listdir('bogus'):
        pass

  def test_lstat(self):
    reader = self.git.repo_reader(self.initial_rev)
    def lstat(*components):
      return type(reader.lstat(os.path.join(*components)))
    self.assertEquals(reader.Symlink, lstat('dir', 'relative-symlink'))
    self.assertEquals(reader.Symlink, lstat('not-a-dir'))
    self.assertEquals(reader.File, lstat('README'))
    self.assertEquals(reader.Dir, lstat('dir'))
    self.assertEquals(types.NoneType, lstat('nope-not-here'))

  def test_readlink(self):
    reader = self.git.repo_reader(self.initial_rev)
    def readlink(*components):
      return reader.readlink(os.path.join(*components))
    self.assertEquals('dir/f', readlink('dir', 'relative-symlink'))
    self.assertEquals(None, readlink('not-a-dir'))
    self.assertEquals(None, readlink('README'))
    self.assertEquals(None, readlink('dir'))
    self.assertEquals(None, readlink('nope-not-here'))

  def test_open(self):
    reader = self.git.repo_reader(self.initial_rev)

    with reader.open('README') as f:
      self.assertEquals('', f.read())

    with reader.open('dir/f') as f:
      self.assertEquals('file in subdir', f.read())

    with self.assertRaises(reader.MissingFileException):
      with reader.open('no-such-file') as f:
        self.assertEquals('', f.read())

    with self.assertRaises(reader.MissingFileException):
      with reader.open('dir/no-such-file') as f:
        pass

    with self.assertRaises(reader.IsDirException):
      with reader.open('dir') as f:
        self.assertEquals('', f.read())

    current_reader = self.git.repo_reader(self.current_rev)

    with current_reader.open('README') as f:
      self.assertEquals('Hello World.\u2764'.encode('utf-8'), f.read())

    with current_reader.open('link-to-dir/f') as f:
      self.assertEquals('file in subdir', f.read())

    with current_reader.open('dir/relative-symlink') as f:
      self.assertEquals('file in subdir', f.read())

    with self.assertRaises(current_reader.SymlinkLoopException):
      with current_reader.open('loop1') as f:
        pass

    with self.assertRaises(current_reader.MissingFileException):
      with current_reader.open('dir/relative-nonexistent') as f:
        pass

    with self.assertRaises(current_reader.NotADirException):
      with current_reader.open('not-a-dir') as f:
        pass

    with self.assertRaises(current_reader.MissingFileException):
      with current_reader.open('dir/not-absolute\u2764') as f:
        pass

    with self.assertRaises(current_reader.MissingFileException):
      with current_reader.open('dir/relative-nonexistent') as f:
        pass

    with current_reader.open('dir/relative-dotdot') as f:
      self.assertEquals('Hello World.\u2764'.encode('utf-8'), f.read())

  def test_integration(self):
    self.assertEqual(set(), self.git.changed_files())
    self.assertEqual({'README'}, self.git.changed_files(from_commit='HEAD^'))

    tip_sha = self.git.commit_id
    self.assertTrue(tip_sha)

    self.assertTrue(tip_sha in self.git.changelog())

    merge_base = self.git.merge_base()
    self.assertTrue(merge_base)

    self.assertTrue(merge_base in self.git.changelog())

    with self.assertRaises(Scm.LocalException):
      self.git.server_url

    with environment_as(GIT_DIR=self.gitdir, GIT_WORK_TREE=self.worktree):
      with self.mkremote('origin') as origin_uri:
        # We shouldn't be fooled by remotes with origin in their name.
        with self.mkremote('temp_origin'):
          origin_url = self.git.server_url
          self.assertEqual(origin_url, origin_uri)

    self.assertTrue(self.git.tag_name.startswith('first-'), msg='un-annotated tags should be found')
    self.assertEqual('master', self.git.branch_name)

    def edit_readme():
      with open(self.readme_file, 'a') as fp:
        fp.write('More data.')

    edit_readme()
    with open(os.path.join(self.worktree, 'INSTALL'), 'w') as untracked:
      untracked.write('make install')
    self.assertEqual({'README'}, self.git.changed_files())
    self.assertEqual({'README', 'INSTALL'}, self.git.changed_files(include_untracked=True))

    # Confirm that files outside of a given relative_to path are ignored
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
        self.assertEqual({'README', 'CHANGES'}, git.changed_files(from_commit='first'))

        self.assertEqual('master', git.branch_name)
        self.assertEqual('second', git.tag_name, msg='annotated tags should be found')

  def test_detect_worktree(self):
    with temporary_dir() as _clone:
      with pushd(_clone):
        clone = os.path.realpath(_clone)

        self.init_repo('origin', self.origin)
        subprocess.check_call(['git', 'pull', '--tags', 'origin', 'master:master'])

        def worktree_relative_to(cwd, expected):
          # Given a cwd relative to the worktree, tests that the worktree is detected as 'expected'.
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

  def test_detect_worktree_no_cwd(self):
    with temporary_dir() as _clone:
      with pushd(_clone):
        clone = os.path.realpath(_clone)

        self.init_repo('origin', self.origin)
        subprocess.check_call(['git', 'pull', '--tags', 'origin', 'master:master'])

        def worktree_relative_to(some_dir, expected):
          # Given a directory relative to the worktree, tests that the worktree is detected as 'expected'.
          subdir = os.path.join(clone, some_dir)
          if not os.path.isdir(subdir):
            os.mkdir(subdir)
          actual = Git.detect_worktree(subdir=subdir)
          self.assertEqual(expected, actual)

        worktree_relative_to('..', None)
        worktree_relative_to('.', clone)
        worktree_relative_to('is', clone)
        worktree_relative_to('is/a', clone)
        worktree_relative_to('is/a/dir', clone)

  @property
  def test_changes_in(self):
    """Test finding changes in a diffspecs

    To some extent this is just testing functionality of git not pants, since all pants says
    is that it will pass the diffspec to git diff-tree, but this should serve to at least document
    the functionality we belive works.
    """
    with environment_as(GIT_DIR=self.gitdir, GIT_WORK_TREE=self.worktree):
      def commit_contents_to_files(content, *files):
        for path in files:
          with safe_open(os.path.join(self.worktree, path), 'w') as fp:
            fp.write(content)
        subprocess.check_call(['git', 'add', '.'])
        subprocess.check_call(['git', 'commit', '-m', 'change {}'.format(files)])
        return subprocess.check_output(['git', 'rev-parse', 'HEAD']).strip()

      # We can get changes in HEAD or by SHA
      c1 = commit_contents_to_files('1', 'foo')
      self.assertEqual({'foo'}, self.git.changes_in('HEAD'))
      self.assertEqual({'foo'}, self.git.changes_in(c1))

      # Changes in new HEAD, from old-to-new HEAD, in old HEAD, or from old-old-head to new.
      commit_contents_to_files('2', 'bar')
      self.assertEqual({'bar'}, self.git.changes_in('HEAD'))
      self.assertEqual({'bar'}, self.git.changes_in('HEAD^..HEAD'))
      self.assertEqual({'foo'}, self.git.changes_in('HEAD^'))
      self.assertEqual({'foo'}, self.git.changes_in('HEAD~1'))
      self.assertEqual({'foo', 'bar'}, self.git.changes_in('HEAD^^..HEAD'))

      # New commit doesn't change results-by-sha
      self.assertEqual({'foo'}, self.git.changes_in(c1))

      # Files changed in multiple diffs within a range
      c3 = commit_contents_to_files('3', 'foo')
      self.assertEqual({'foo', 'bar'}, self.git.changes_in('{}..{}'.format(c1, c3)))

      # Changes in a tag
      subprocess.check_call(['git', 'tag', 'v1'])
      self.assertEqual({'foo'}, self.git.changes_in('v1'))

      # Introduce a new filename
      c4 = commit_contents_to_files('4', 'baz')
      self.assertEqual({'baz'}, self.git.changes_in('HEAD'))

      # Tag-to-sha
      self.assertEqual({'baz'}, self.git.changes_in('{}..{}'.format('v1', c4)))

      # We can get multiple changes from one ref
      commit_contents_to_files('5', 'foo', 'bar')
      self.assertEqual({'foo', 'bar'}, self.git.changes_in('HEAD'))
      self.assertEqual({'foo', 'bar', 'baz'}, self.git.changes_in('HEAD~4..HEAD'))
      self.assertEqual({'foo', 'bar', 'baz'}, self.git.changes_in('{}..HEAD'.format(c1)))
      self.assertEqual({'foo', 'bar', 'baz'}, self.git.changes_in('{}..{}'.format(c1, c4)))

  def test_changelog_utf8(self):
    with environment_as(GIT_DIR=self.gitdir, GIT_WORK_TREE=self.worktree):
      def commit_contents_to_files(message, encoding, content, *files):
        for path in files:
          with safe_open(os.path.join(self.worktree, path), 'w') as fp:
            fp.write(content)
        subprocess.check_call(['git', 'add', '.'])

        subprocess.check_call(['git', 'config', '--local', '--add', 'i18n.commitencoding',
                               encoding])
        try:
          subprocess.check_call(['git', 'commit', '-m', message.encode(encoding)])
        finally:
          subprocess.check_call(['git', 'config', '--local', '--unset-all', 'i18n.commitencoding'])

        return subprocess.check_output(['git', 'rev-parse', 'HEAD']).strip()

      # Mix in a non-UTF-8 author to all commits to exercise the corner described here does not
      # adversely impact the ability to render the changelog (even if rendering for certain
      # characters is incorrect): http://comments.gmane.org/gmane.comp.version-control.git/262685
      # NB: This method of override requires we include `user.name` and `user.email` even though we
      # only use `user.name` to exercise non-UTF-8.  Without `user.email`, it will be unset and
      # commits can then fail on machines without a proper hostname setup for git to fall back to
      # when concocting a last-ditch `user.email`.
      non_utf8_config = dedent("""
      [user]
        name = Noralf Trønnes
        email = noralf@example.com
      """).encode('iso-8859-1')

      with open(os.path.join(self.gitdir, 'config'), 'wb') as fp:
        fp.write(non_utf8_config)

      # Note the copyright symbol is used as the non-ascii character in the next 3 commits
      commit_contents_to_files('START1 © END', 'iso-8859-1', '1', 'foo')
      commit_contents_to_files('START2 © END', 'latin1', '1', 'bar')
      commit_contents_to_files('START3 © END', 'utf-8', '1', 'baz')

      commit_contents_to_files('START4 ~ END', 'us-ascii', '1', 'bip')

      # Prove our non-utf-8 encodings were stored in the commit metadata.
      log = subprocess.check_output(['git', 'log', '--format=%e'])
      self.assertEqual(['us-ascii', 'latin1', 'iso-8859-1'], filter(None, log.strip().splitlines()))

      # And show that the git log successfully transcodes all the commits none-the-less to utf-8
      changelog = self.git.changelog()

      # The ascii commit should combine with the iso-8859-1 author an fail to transcode the
      # o-with-stroke character, and so it should be replaced with the utf-8 replacement character
      # \uFFF or �.
      self.assertIn('Noralf Tr�nnes', changelog)
      self.assertIn('Noralf Tr\uFFFDnnes', changelog)

      # For the other 3 commits, each of iso-8859-1, latin1 and utf-8 have an encoding for the
      # o-with-stroke character - \u00F8 or ø - so we should find it;
      self.assertIn('Noralf Trønnes', changelog)
      self.assertIn('Noralf Tr\u00F8nnes', changelog)

      self.assertIn('START1 © END', changelog)
      self.assertIn('START2 © END', changelog)
      self.assertIn('START3 © END', changelog)
      self.assertIn('START4 ~ END', changelog)

  def test_refresh_with_conflict(self):
    with environment_as(GIT_DIR=self.gitdir, GIT_WORK_TREE=self.worktree):
      self.assertEqual(set(), self.git.changed_files())
      self.assertEqual({'README'}, self.git.changed_files(from_commit='HEAD^'))
      self.assertEqual({'README'}, self.git.changes_in('HEAD'))

      # Create a change on this branch that is incompatible with the change to master
      with open(self.readme_file, 'w') as readme:
        readme.write('Conflict')

      subprocess.check_call(['git', 'commit', '-am', 'Conflict'])

      self.assertEquals(set(), self.git.changed_files(include_untracked=True, from_commit='HEAD'))
      with self.assertRaises(Scm.LocalException):
        self.git.refresh(leave_clean=False)
      # The repo is dirty
      self.assertEquals({'README'},
                        self.git.changed_files(include_untracked=True, from_commit='HEAD'))

      with environment_as(GIT_DIR=self.gitdir, GIT_WORK_TREE=self.worktree):
        subprocess.check_call(['git', 'reset', '--hard', 'HEAD'])

      # Now try with leave_clean
      with self.assertRaises(Scm.LocalException):
        self.git.refresh(leave_clean=True)
      # The repo is clean
      self.assertEquals(set(), self.git.changed_files(include_untracked=True, from_commit='HEAD'))

  def test_commit_with_new_untracked_file_adds_file(self):
    new_file = os.path.join(self.worktree, 'untracked_file')

    touch(new_file)

    self.assertEqual({'untracked_file'}, self.git.changed_files(include_untracked=True))

    self.git.add(new_file)

    self.assertEqual({'untracked_file'}, self.git.changed_files())

    self.git.commit('API Changes.')

    self.assertEqual(set(), self.git.changed_files(include_untracked=True))


class DetectWorktreeFakeGitTest(unittest.TestCase):

  @contextmanager
  def empty_path(self):
    with temporary_dir() as path:
      with environment_as(PATH=path):
        yield path

  @contextmanager
  def unexecutable_git(self):
    with self.empty_path() as path:
      git = os.path.join(path, 'git')
      touch(git)
      yield git

  @contextmanager
  def executable_git(self):
    with self.unexecutable_git() as git:
      chmod_plus_x(git)
      yield git

  def test_detect_worktree_no_git(self):
    with self.empty_path():
      self.assertIsNone(Git.detect_worktree())

  def test_detect_worktree_unexectuable_git(self):
    with self.unexecutable_git() as git:
      self.assertIsNone(Git.detect_worktree())
      self.assertIsNone(Git.detect_worktree(binary=git))

  def test_detect_worktree_invalid_executable_git(self):
    with self.executable_git() as git:
      self.assertIsNone(Git.detect_worktree())
      self.assertIsNone(Git.detect_worktree(binary=git))

  def test_detect_worktree_failing_git(self):
    with self.executable_git() as git:
      with open(git, 'w') as fp:
        fp.write('#!/bin/sh\n')
        fp.write('exit 1')
      self.assertIsNone(Git.detect_worktree())
      self.assertIsNone(Git.detect_worktree(git))

  def test_detect_worktree_working_git(self):
    expected_worktree_dir = '/a/fake/worktree/dir'
    with self.executable_git() as git:
      with open(git, 'w') as fp:
        fp.write('#!/bin/sh\n')
        fp.write('echo ' + expected_worktree_dir)
      self.assertEqual(expected_worktree_dir, Git.detect_worktree())
      self.assertEqual(expected_worktree_dir, Git.detect_worktree(binary=git))
