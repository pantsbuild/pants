# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
import subprocess
import traceback

from pants.scm.scm import Scm


class Git(Scm):
  """An Scm implementation backed by git."""

  @classmethod
  def detect_worktree(cls):
    """Detect the git working tree above cwd and return it; else, return None."""
    cmd = ['git', 'rev-parse', '--show-toplevel']
    process, out = cls._invoke(cmd)
    try:
      cls._check_result(cmd, process.returncode, raise_type=Scm.ScmException)
    except Scm.ScmException:
      return None
    return cls._cleanse(out)

  @classmethod
  def _invoke(cls, cmd):
    """Invoke the given command, and return a tuple of process and raw binary output.

    stderr flows to wherever its currently mapped for the parent process - generally to
    the terminal where the user can see the error.
    """
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    out, _ = process.communicate()
    return (process, out)

  @classmethod
  def _cleanse(cls, output):
    return output.strip().decode('utf-8')

  @classmethod
  def _check_result(cls, cmd, result, failure_msg=None, raise_type=Scm.ScmException):
    if result != 0:
      raise raise_type(failure_msg or '%s failed with exit code %d' % (' '.join(cmd), result))

  def __init__(self, binary='git', gitdir=None, worktree=None, remote=None, branch=None, log=None):
    """Creates a git scm proxy that assumes the git repository is in the cwd by default.

    binary:    The path to the git binary to use, 'git' by default.
    gitdir:    The path to the repository's git metadata directory (typically '.git').
    worktree:  The path to the git repository working tree directory (typically '.').
    remote:    The default remote to use.
    branch:    The default remote branch to use.
    log:       A log object that supports debug, info, and warn methods.
    """
    Scm.__init__(self)

    self._gitcmd = binary
    self._worktree = os.path.realpath(worktree or os.getcwd())
    self._gitdir = os.path.realpath(gitdir) if gitdir else os.path.join(self._worktree, '.git')
    self._remote = remote
    self._branch = branch

    if log:
      self._log = log
    else:
      from twitter.common import log as c_log
      self._log = c_log

  def current_rev_identifier(self):
    return 'HEAD'

  @property
  def commit_id(self):
    return self._check_output(['rev-parse', 'HEAD'], raise_type=Scm.LocalException)

  @property
  def server_url(self):
    git_output = self._check_output(['remote', '--verbose'], raise_type=Scm.LocalException)
    origin_push_line = [line.split()[1] for line in git_output.splitlines()
                                        if 'origin' in line and '(push)' in line]
    if len(origin_push_line) != 1:
      raise Scm.LocalException('Unable to find origin remote amongst: ' + git_output)
    return origin_push_line[0]

  @property
  def tag_name(self):
    tag = self._check_output(['describe', '--tags', '--always'], raise_type=Scm.LocalException)
    return None if b'cannot' in tag else tag

  @property
  def branch_name(self):
    branch = self._check_output(['rev-parse', '--abbrev-ref', 'HEAD'],
                                raise_type=Scm.LocalException)
    return None if branch == 'HEAD' else branch

  def changed_files(self, from_commit=None, include_untracked=False, relative_to=None):
    relative_to = relative_to or self._worktree
    rel_suffix = ['--', relative_to]
    uncommitted_changes = self._check_output(['diff', '--name-only', 'HEAD'] + rel_suffix,
                                             raise_type=Scm.LocalException)

    files = set(uncommitted_changes.split())
    if from_commit:
      # Grab the diff from the merge-base to HEAD using ... syntax.  This ensures we have just
      # the changes that have occurred on the current branch.
      committed_cmd = ['diff', '--name-only', '%s...HEAD' % from_commit] + rel_suffix
      committed_changes = self._check_output(committed_cmd,
                                             raise_type=Scm.LocalException)
      files.update(committed_changes.split())
    if include_untracked:
      untracked_cmd = ['ls-files', '--other', '--exclude-standard'] + rel_suffix
      untracked = self._check_output(untracked_cmd,
                                     raise_type=Scm.LocalException)
      files.update(untracked.split())
    # git will report changed files relative to the worktree: re-relativize to relative_to
    def fix_git_relative_path(worktree_path):
      return os.path.relpath(os.path.join(self._worktree, worktree_path), relative_to)
    return set(fix_git_relative_path(f) for f in files)

  def changelog(self, from_commit=None, files=None):
    args = ['whatchanged', '--stat', '--find-renames', '--find-copies']
    if from_commit:
      args.append('%s..HEAD' % from_commit)
    if files:
      args.append('--')
      args.extend(files)
    return self._check_output(args, raise_type=Scm.LocalException)

  def merge_base(self, left='master', right='HEAD'):
    """Returns the merge-base of master and HEAD in bash: `git merge-base left right`"""
    return self._check_output(['merge-base', left, right], raise_type=Scm.LocalException)

  def refresh(self, leave_clean=False):
    """Attempt to pull-with-rebase from upstream.  This is implemented as fetch-plus-rebase
       so that we can distinguish between errors in the fetch stage (likely network errors)
       and errors in the rebase stage (conflicts).  If leave_clean is true, then in the event
       of a rebase failure, the branch will be rolled back.  Otherwise, it will be left in the
       conflicted state.
    """
    remote, merge = self._get_upstream()
    self._check_call(['fetch', '--tags', remote, merge], raise_type=Scm.RemoteException)
    try:
      self._check_call(['rebase', 'FETCH_HEAD'], raise_type=Scm.LocalException)
    except Scm.LocalException as e:
      if leave_clean:
        self._log.debug('Cleaning up after failed rebase')
        try:
          self._check_call(['rebase', '--abort'], raise_type=Scm.LocalException)
        except Scm.LocalException as abort_exc:
          self._log.debug('Failed to up after failed rebase')
          self._log.debug(traceback.format_exc(abort_exc))
          # But let the original exception propagate, since that's the more interesting one
      raise e

  def tag(self, name, message=None):
    # We use -a here instead of --annotate to maintain maximum git compatibility.
    # --annotate was only introduced in 1.7.8 via:
    #   https://github.com/git/git/commit/c97eff5a95d57a9561b7c7429e7fcc5d0e3a7f5d
    self._check_call(['tag', '-a', '--message=%s' % (message or ''), name],
                     raise_type=Scm.LocalException)
    self.push('refs/tags/%s' % name)

  def commit(self, message):
    self._check_call(['commit', '--all', '--message=%s' % message], raise_type=Scm.LocalException)

  def commit_date(self, commit_reference):
    return self._check_output(['log', '-1', '--pretty=tformat:%ci', commit_reference],
                              raise_type=Scm.LocalException)

  def push(self, *refs):
    remote, merge = self._get_upstream()
    self._check_call(['push', remote, merge] + list(refs), raise_type=Scm.RemoteException)

  def _get_upstream(self):
    """Return the remote and remote merge branch for the current branch"""
    if not self._remote or not self._branch:
      branch = self.branch_name
      if not branch:
        raise Scm.LocalException('Failed to determine local branch')

      def get_local_config(key):
        value = self._check_output(['config', '--local', '--get', key],
                                   raise_type=Scm.LocalException)
        return value.strip()

      self._remote = self._remote or get_local_config('branch.%s.remote' % branch)
      self._branch = self._branch or get_local_config('branch.%s.merge' % branch)
    return self._remote, self._branch

  def _check_call(self, args, failure_msg=None, raise_type=None):
    cmd = self._create_git_cmdline(args)
    self._log_call(cmd)
    result = subprocess.call(cmd)
    self._check_result(cmd, result, failure_msg, raise_type)

  def _check_output(self, args, failure_msg=None, raise_type=None):
    cmd = self._create_git_cmdline(args)
    self._log_call(cmd)

    process, out = self._invoke(cmd)

    self._check_result(cmd, process.returncode, failure_msg, raise_type)
    return self._cleanse(out)

  def _create_git_cmdline(self, args):
    return [self._gitcmd, '--git-dir=%s' % self._gitdir, '--work-tree=%s' % self._worktree] + args

  def _log_call(self, cmd):
    self._log.debug('Executing: %s' % ' '.join(cmd))
