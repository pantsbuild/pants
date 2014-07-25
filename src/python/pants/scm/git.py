# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
import subprocess

from pants.scm.scm import Scm


class Git(Scm):
  """An Scm implementation backed by git."""

  def __init__(self, binary='git', gitdir=None, worktree=None, remote=None, branch=None, log=None):
    """Creates a git scm proxy that assumes the git repository is in the cwd by default.

    binary:    The path to the git binary to use, 'git' by default.
    gitdir:    The path to the repository's git metadata directory (typically '.git').
    workspace: The path to the git repository working tree directory (typically '.').
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

  @property
  def commit_id(self):
    return self._check_output(['rev-parse', 'HEAD'], raise_type=Scm.LocalException)

  @property
  def tag_name(self):
    tag = self._check_output(['describe', '--tags', '--always'], raise_type=Scm.LocalException)
    return None if b'cannot' in tag else tag

  @property
  def branch_name(self):
    branch = self._check_output(['rev-parse', '--abbrev-ref', 'HEAD'],
                                raise_type=Scm.LocalException)
    return None if branch == 'HEAD' else branch

  def changed_files(self, from_commit=None, include_untracked=False):
    uncommitted_changes = self._check_output(['diff', '--name-only', 'HEAD'],
                                             raise_type=Scm.LocalException)

    files = set(uncommitted_changes.split())
    if from_commit:
      # Grab the diff from the merge-base to HEAD using ... syntax.  This ensures we have just
      # the changes that have occurred on the current branch.
      committed_changes = self._check_output(['diff', '--name-only', '%s...HEAD' % from_commit],
                                             raise_type=Scm.LocalException)
      files.update(committed_changes.split())
    if include_untracked:
      untracked = self._check_output(['ls-files', '--other', '--exclude-standard'],
                                     raise_type=Scm.LocalException)
      files.update(untracked.split())
    return files

  def changelog(self, from_commit=None, files=None):
    args = ['whatchanged', '--stat', '--find-renames', '--find-copies']
    if from_commit:
      args.append('%s..HEAD' % from_commit)
    if files:
      args.append('--')
      args.extend(files)
    return self._check_output(args, raise_type=Scm.LocalException)

  def refresh(self):
    remote, merge = self._get_upstream()
    self._check_call(['pull', '--ff-only', '--tags', remote, merge], raise_type=Scm.RemoteException)

  def tag(self, name, message=None):
    # We use -a here instead of --annotate to maintain maximum git compatibility.
    # --annotate was only introduced in 1.7.8 via:
    #   https://github.com/git/git/commit/c97eff5a95d57a9561b7c7429e7fcc5d0e3a7f5d
    self._check_call(['tag', '-a', '--message=%s' % (message or ''), name],
                     raise_type=Scm.LocalException)
    self._push('refs/tags/%s' % name)

  def commit(self, message):
    self._check_call(['commit', '--all', '--message=%s' % message], raise_type=Scm.LocalException)
    self._push()

  def _push(self, *refs):
    remote, merge = self._get_upstream()
    self._check_call(['push', remote, merge] + list(refs), raise_type=Scm.RemoteException)

  def _get_upstream(self):
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

    # We let stderr flow to wherever its currently mapped for this process - generally to the
    # terminal where the user can see the error.
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    out, _ = process.communicate()

    self._check_result(cmd, process.returncode, failure_msg, raise_type)
    return self._cleanse(out)

  def _create_git_cmdline(self, args):
    return [self._gitcmd, '--git-dir=%s' % self._gitdir, '--work-tree=%s' % self._worktree] + args

  def _log_call(self, cmd):
    self._log.debug('Executing: %s' % ' '.join(cmd))

  def _check_result(self, cmd, result, failure_msg=None, raise_type=Scm.ScmException):
    if result != 0:
      raise raise_type(failure_msg or '%s failed with exit code %d' % (' '.join(cmd), result))

  def _cleanse(self, output):
    return output.strip().decode('utf-8')
